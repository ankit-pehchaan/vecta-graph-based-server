"""
Agno Agent Service - Tool-Based Architecture.

Provides agent management with tool-based conversation flow.
Replaces EducationPipeline with single agent + tools approach.
"""

import os
import logging
from typing import Optional, Callable, Any
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.postgres import PostgresDb
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.config import settings
from app.core.prompts import (
    AGENT_PROMPT_V2,
    FINANCIAL_ADVISER_SYSTEM_PROMPT,
    GREETING_FIRST_TIME,
    GREETING_RETURNING_WITH_SUMMARY,
    GREETING_RETURNING_NO_SUMMARY,
)

# Configure logger (set to WARNING to disable verbose debug logs)
logger = logging.getLogger("agno_agent_service")
logger.setLevel(logging.WARNING)


class AgnoAgentService:
    """Service for managing Agno financial educator agents with tools.

    Creates and reuses agents per user for performance (per .cursorrules).
    Each user gets their own agent instance with session history and tools.
    Uses db_manager for fresh database sessions per operation.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._agents: dict[str, Agent] = {}  # Cache agents per user
        self._legacy_agents: dict[str, Agent] = {}  # Legacy agents without tools

        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

        logger.info("AgnoAgentService initialized with tool-based architecture (PostgreSQL storage)")

    def _create_session_tools(self, session_id: str) -> list[Callable]:
        """
        Create session-bound tool functions for the agent.

        Uses synchronous versions of tools to avoid asyncio event loop conflicts
        when Agno runs tools in separate threads.

        IMPORTANT: Tool names match what the prompt references (e.g., extract_financial_facts, not session_extract_facts).
        """
        from app.tools.sync_tools import (
            sync_classify_goal,
            sync_extract_financial_facts,
            sync_determine_required_info,
            sync_calculate_risk_profile,
            sync_generate_visualization,
        )

        # Get sync database URL from settings
        from app.core.config import settings
        db_url = settings.SYNC_DATABASE_URL

        def classify_goal(user_goal: str) -> dict:
            """
            Classifies the user's financial goal into categories.

            Categories: small_purchase, medium_purchase, large_purchase, luxury, life_event, investment, emergency.

            Args:
                user_goal: The user's stated goal (e.g., "I want to buy a house")

            Returns:
                dict with:
                - classification: The goal category
                - reasoning: Brief explanation of why this category
                - message: Confirmation message

            When to call:
            - When user first mentions a goal (directly or indirectly)
            - Only call ONCE per conversation
            - Don't call if goal already classified
            """
            return sync_classify_goal(user_goal, db_url, session_id)

        def extract_financial_facts(user_message: str, agent_last_question: str = "") -> dict:
            """
            Extracts financial facts from user's message using LLM.

            Args:
                user_message: The user's latest message
                agent_last_question: Your previous question for context (e.g., "What's your monthly income?")

            Returns:
                dict with:
                - extracted_facts: Financial data extracted (age, income, debts, etc.)
                - probing_suggestions: If a fact reveals a potential goal (e.g., high debt → goal to clear it)
                - goal_confirmed/goal_denied: If user was responding to a previous goal probe
                - stated_goals_added: Any goals mentioned by user

            When to call:
            - EVERY turn after goal is classified
            - Always call this FIRST before other tools
            - Pass your last question for context so the tool knows what the user is answering
            - Even if you think nothing new was mentioned (let the tool decide)

            If probing_suggestions is returned:
            - Ask the probe_question immediately
            - Next turn, this tool will detect if they confirmed or denied
            - If confirmed → Goal added to discovered_goals
            - If denied but critical → Tracked as critical_concern (bring up in Phase 3)
            """
            return sync_extract_financial_facts(user_message, agent_last_question, db_url, session_id)

        def determine_required_info() -> dict:
            """
            Determines what information is still needed based on goal type.

            Returns:
                dict with:
                - goal_type: The classified goal type
                - required_fields: All fields needed for this goal
                - missing_fields: Fields still needed (empty = ready for Phase 3)
                - populated_fields: Fields already collected
                - message: Summary of status

            When to call:
            - EVERY turn after extract_financial_facts
            - This tells you what questions to ask next
            - Check the "missing_fields" in the response
            - If missing_fields is empty → Move to Phase 3
            """
            return sync_determine_required_info(db_url, session_id)

        def calculate_risk_profile() -> dict:
            """
            Calculates objective risk assessment based on complete financial situation.

            Returns:
                dict with:
                - risk_appetite: low, medium, or high
                - agent_reason: Detailed explanation with specific numbers
                - key_concerns: List of financial vulnerabilities
                - strengths: List of financial strengths
                - message: Summary

            When to call:
            - ONLY when missing_fields is EMPTY (all info gathered)
            - Call this once before giving final analysis in Phase 3
            - Don't call if missing_fields has items
            """
            return sync_calculate_risk_profile(db_url, session_id)

        def generate_visualization(viz_type: str, params: dict = None) -> dict:
            """
            Generates charts and visualizations to help explain concepts.

            Args:
                viz_type: Type of visualization
                    - "profile_snapshot": Balance sheet, asset mix, cashflow overview
                    - "loan_amortization": Loan repayment trajectory (needs: principal, annual_rate_percent, term_years)
                    - "goal_projection": Savings/expense projection over time (needs: label, monthly_amount, years)
                params: Type-specific parameters (optional for profile_snapshot)

            Returns:
                dict with:
                - success: Whether visualization was generated
                - visualizations: List of visualization data
                - message: Status message

            When to call:
            - In Phase 3 (Analysis) to show the user their financial picture
            - When explaining loan scenarios or projections
            - When user asks to "see" or "visualize" their situation
            """
            return sync_generate_visualization(viz_type, db_url, session_id, params)

        # Return tools with names matching prompt references
        return [
            classify_goal,
            extract_financial_facts,
            determine_required_info,
            calculate_risk_profile,
            generate_visualization
        ]

    async def get_agent_with_session(self, username: str, session: AsyncSession) -> Agent:
        """
        Get or create a tool-enabled Agno agent for a user.

        This is the new tool-based agent that uses:
        - classify_goal
        - extract_financial_facts
        - determine_required_info
        - calculate_risk_profile
        - generate_visualization

        Args:
            username: Username to get agent for
            session: Database session (used for user lookup only, tools create own sessions)

        Returns:
            Agent instance with tools (cached per user)
        """
        logger.debug(f"[GET_AGENT_V2] Requested tool-based agent for user: {username}")

        # Return cached agent if exists
        if username in self._agents:
            logger.debug(f"[GET_AGENT_V2] Returning CACHED agent for: {username}")
            return self._agents[username]

        # Get user info
        user_repo = UserRepository(session)
        user = await user_repo.get_by_email(username)
        user_name = user.get("name") if user else None
        logger.debug(f"[GET_AGENT_V2] User name resolved: {user_name or 'Unknown'}")

        # Create tools (they create their own sessions internally)
        tools = self._create_session_tools(username)
        logger.debug(f"[GET_AGENT_V2] Created {len(tools)} tools: {[t.__name__ for t in tools]}")

        # Build instructions with user name if available
        instructions = AGENT_PROMPT_V2
        if user_name:
            instructions = f"{AGENT_PROMPT_V2}\n\nYou're speaking with {user_name}."

        # Create agent with PostgreSQL storage for scalability
        agent = Agent(
            id=f"finance-educator-{username}",
            name="Vecta - Financial Educator",
            model=OpenAIChat(id="gpt-4o"),  # Use gpt-4o (gpt-4.1 doesn't exist)
            instructions=instructions,
            tools=tools,
            db=PostgresDb(
                db_url=settings.SYNC_DATABASE_URL,
                session_table="agno_sessions"
            ),
            user_id=username,
            add_history_to_context=True,
            num_history_runs=5,
            enable_session_summaries=True,
            markdown=True,
            debug_mode=True  # Enable to see tool calls
        )

        # Cache the agent
        self._agents[username] = agent
        logger.info(f"[GET_AGENT_V2] Created and CACHED tool-based agent for: {username}")
        return agent

    async def get_agent(self, username: str) -> Agent:
        """
        Get or create an Agno agent for a user (legacy method without tools).

        Maintained for backward compatibility. For new code, use get_agent_with_session().

        Args:
            username: Username to get agent for

        Returns:
            Agent instance for the user (without tools)
        """
        logger.debug(f"[GET_AGENT_LEGACY] Requested agent for user: {username}")

        if username in self._legacy_agents:
            logger.debug(f"[GET_AGENT_LEGACY] Returning cached agent for: {username}")
            return self._legacy_agents[username]

        logger.debug(f"[GET_AGENT_LEGACY] Creating new legacy agent for: {username}")

        # Get user info with fresh session
        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)

        user_name = user.get("name") if user else None
        logger.debug(f"[GET_AGENT_LEGACY] User name resolved: {user_name or 'Unknown'}")

        instructions = FINANCIAL_ADVISER_SYSTEM_PROMPT
        if user_name:
            instructions = f"{FINANCIAL_ADVISER_SYSTEM_PROMPT}\n\nYou're speaking with {user_name}."

        # Create agent with PostgreSQL storage (no tools)
        agent = Agent(
            name="Jamie (Financial Educator)",
            model=OpenAIChat(id="gpt-4o"),
            instructions=instructions,
            db=PostgresDb(
                db_url=settings.SYNC_DATABASE_URL,
                session_table="agno_sessions_legacy"
            ),
            user_id=username,
            add_history_to_context=True,
            num_history_runs=10,
            markdown=True,
            debug_mode=False
        )

        # Cache agent for reuse
        self._legacy_agents[username] = agent
        logger.info(f"[GET_AGENT_LEGACY] Created and cached legacy agent for: {username}")

        return agent

    async def is_first_time_user(self, username: str) -> bool:
        """
        Check if this is the first time the user is using the education service.

        Args:
            username: Username to check

        Returns:
            True if first time, False otherwise
        """
        logger.debug(f"[FIRST_TIME_CHECK] Checking for user: {username}")

        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username)
            is_first = profile is None
            logger.debug(f"[FIRST_TIME_CHECK] User {username} is first time: {is_first}")
            return is_first

        logger.debug(f"[FIRST_TIME_CHECK] Session failed for {username}, defaulting to first-time")
        return True

    async def get_conversation_summary(self, username: str) -> Optional[str]:
        """
        Get a summary of previous conversations for returning users.

        Args:
            username: Username to get summary for

        Returns:
            Summary string or None if no previous conversations
        """
        logger.debug(f"[SUMMARY] Getting conversation summary for: {username}")

        profile = None
        async for session in self.db_manager.get_session():
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username)

        if not profile:
            logger.debug(f"[SUMMARY] No profile found for: {username}")
            return None

        # Build summary from profile
        summary_parts = []

        if profile.get("goals"):
            goal_count = len(profile.get("goals", []))
            summary_parts.append(f"discussed {goal_count} financial goal(s)")
            logger.debug(f"[SUMMARY] Found {goal_count} goals")

        if profile.get("assets"):
            asset_count = len(profile.get("assets", []))
            summary_parts.append(f"reviewed {asset_count} asset(s)")
            logger.debug(f"[SUMMARY] Found {asset_count} assets")

        if profile.get("liabilities"):
            liability_count = len(profile.get("liabilities", []))
            summary_parts.append(f"reviewed {liability_count} liability(ies)")
            logger.debug(f"[SUMMARY] Found {liability_count} liabilities")

        if profile.get("financial_stage"):
            summary_parts.append(f"assessed financial stage: {profile.get('financial_stage')}")

        if profile.get("income"):
            summary_parts.append(f"discussed income of ${profile.get('income'):,.0f}")

        if summary_parts:
            summary = "Previously, we " + ", ".join(summary_parts) + "."
            logger.debug(f"[SUMMARY] Generated summary: {summary}")
            return summary

        logger.debug(f"[SUMMARY] No summary data for: {username}")
        return None

    async def generate_greeting(self, username: str) -> str:
        """
        Generate appropriate greeting for user (first-time or returning).

        Args:
            username: Username to generate greeting for

        Returns:
            Greeting message
        """
        logger.info(f"[GREETING] Generating greeting for: {username}")

        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)

        user_name = user.get("name") if user else username
        logger.debug(f"[GREETING] User name: {user_name}")

        is_first_time = await self.is_first_time_user(username)
        logger.debug(f"[GREETING] Is first time: {is_first_time}")

        if is_first_time:
            greeting = GREETING_FIRST_TIME.format(user_name=user_name)
            logger.info(f"[GREETING] First-time greeting for: {username}")
        else:
            summary = await self.get_conversation_summary(username)
            if summary:
                clean_summary = summary.lower().replace('previously, we ', '')
                greeting = GREETING_RETURNING_WITH_SUMMARY.format(
                    user_name=user_name,
                    summary=clean_summary
                )
                logger.info(f"[GREETING] Returning user greeting with summary for: {username}")
            else:
                greeting = GREETING_RETURNING_NO_SUMMARY.format(user_name=user_name)
                logger.info(f"[GREETING] Returning user greeting without summary for: {username}")

        logger.debug(f"[GREETING] Generated: {greeting[:50]}...")
        return greeting

    def clear_agent_cache(self, username: Optional[str] = None):
        """
        Clear cached agents.

        Args:
            username: Specific user to clear, or None to clear all
        """
        if username:
            self._agents.pop(username, None)
            self._legacy_agents.pop(username, None)
            logger.info(f"[CACHE] Cleared agent cache for: {username}")
        else:
            self._agents.clear()
            self._legacy_agents.clear()
            logger.info("[CACHE] Cleared all agent caches")

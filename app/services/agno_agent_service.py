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
from app.tools.sync_tools import _get_sync_session, _get_user_store
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

    def _build_profile_context(self, username: str) -> str:
        """
        Build a summary of the user's existing profile data for agent context.

        This allows the agent to reference previous data without needing to call tools first.
        """
        try:
            session = _get_sync_session(settings.SYNC_DATABASE_URL)
            try:
                store = _get_user_store(session, username)
            finally:
                session.close()

            parts = []

            # Goals
            if store.get("user_goal"):
                parts.append(f"Primary goal: {store['user_goal']} (classified as {store.get('goal_classification', 'unknown')})")
            if store.get("stated_goals"):
                parts.append(f"Other goals mentioned: {', '.join(store['stated_goals'])}")

            # Financial situation
            if store.get("age"):
                parts.append(f"Age: {store['age']}")
            if store.get("monthly_income"):
                parts.append(f"Monthly income: ${store['monthly_income']:,.0f}")
            if store.get("monthly_expenses"):
                parts.append(f"Monthly expenses: ${store['monthly_expenses']:,.0f}")
            if store.get("savings"):
                parts.append(f"Savings: ${store['savings']:,.0f}")
            if store.get("emergency_fund"):
                parts.append(f"Emergency fund: ${store['emergency_fund']:,.0f}")

            # Debts/Liabilities
            debts = store.get("debts", [])
            if debts:
                debt_items = []
                for d in debts:
                    if d.get("type") and d.get("type") != "none":
                        debt_str = f"{d['type']}"
                        if d.get("amount"):
                            debt_str += f": ${d['amount']:,.0f}"
                        if d.get("interest_rate"):
                            debt_str += f" at {d['interest_rate']}%"
                        if d.get("tenure_months"):
                            years = d['tenure_months'] / 12
                            debt_str += f" ({years:.1f} years remaining)"
                        debt_items.append(debt_str)
                if debt_items:
                    parts.append(f"Debts: {'; '.join(debt_items)}")

            # Investments
            investments = store.get("investments", [])
            if investments:
                inv_items = []
                for inv in investments:
                    if inv.get("type") and inv.get("type") != "none":
                        inv_str = f"{inv['type']}"
                        if inv.get("value"):
                            inv_str += f": ${inv['value']:,.0f}"
                        inv_items.append(inv_str)
                if inv_items:
                    parts.append(f"Investments: {'; '.join(inv_items)}")

            # Superannuation
            super_data = store.get("superannuation", {})
            if super_data and super_data.get("balance"):
                parts.append(f"Superannuation: ${super_data['balance']:,.0f}")

            # Other info
            if store.get("marital_status"):
                parts.append(f"Marital status: {store['marital_status']}")
            if store.get("dependents"):
                parts.append(f"Dependents: {store['dependents']}")
            if store.get("job_stability"):
                parts.append(f"Job stability: {store['job_stability']}")

            if not parts:
                return ""

            # Build visualization hints based on available data
            viz_hints = []
            debts = store.get("debts", [])
            for d in debts:
                if d.get("type") and d.get("type") != "none":
                    debt_type = d.get("type", "").lower()
                    if debt_type in ["home_loan", "mortgage", "housing_loan"]:
                        if d.get("amount") and d.get("interest_rate"):
                            viz_hints.append(f"loan_amortization (home loan: ${d['amount']:,.0f} at {d['interest_rate']}%)")
                    elif d.get("monthly_payment") or d.get("tenure_months"):
                        emi = d.get("monthly_payment", 0)
                        months = d.get("tenure_months", 0)
                        if emi and months:
                            viz_hints.append(f"goal_projection for {debt_type} (EMI: ${emi:,.0f}/month, {months} months)")

            if store.get("monthly_income") or store.get("monthly_expenses") or store.get("savings"):
                viz_hints.append("profile_snapshot (has income/expenses/savings)")

            profile_section = "\n\n## User's Current Financial Profile:\n" + "\n".join(f"- {p}" for p in parts)

            if viz_hints:
                profile_section += "\n\n## Available Visualizations (use when user asks to 'show' or 'visualize'):\n"
                profile_section += "\n".join(f"- {v}" for v in viz_hints)

            return profile_section

        except Exception as e:
            logger.warning(f"[PROFILE_CONTEXT] Error building profile context: {e}")
            return ""

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
            sync_confirm_loan_data,
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

        def extract_financial_facts(user_message: str, agent_last_question: str) -> dict:
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
                    - "loan_amortization": Loan repayment trajectory with interest breakdown
                      Needs: principal, annual_rate_percent, term_years
                      Use when: User wants to see how loan balance decreases over time, or interest vs principal split
                    - "goal_projection": Cumulative payment/savings projection over time
                      Needs: label, monthly_amount, years
                      Use when: User gives EMI + tenure and wants total payment, OR savings projection

                params: Type-specific parameters
                    For loan_amortization:
                    - principal: Loan amount (the original loan value)
                    - annual_rate_percent: Interest rate (e.g., 6.5)
                    - term_years: Loan term in years
                    - extra_payment: (optional) Additional payment per month

                    For goal_projection:
                    - label: Description (e.g., "Personal Loan Payments", "Emergency Fund")
                    - monthly_amount: Amount per month (EMI or savings)
                    - years: Duration in years (tenure_months / 12)

            CHOOSING THE RIGHT VIZ TYPE:
            - User says "2k EMI for 36 months, show total" → goal_projection (label="Personal Loan", monthly_amount=2000, years=3)
            - User says "500k loan at 7% for 20 years" → loan_amortization (principal=500000, annual_rate_percent=7, term_years=20)
            - User wants balance trajectory with interest → loan_amortization
            - User wants simple EMI × months total → goal_projection

            Returns:
                dict with success, visualization, message
            """
            return sync_generate_visualization(viz_type, db_url, session_id, params)

        def confirm_loan_data(loan_type: str, principal: float, annual_rate_percent: float, term_years: int) -> dict:
            """
            Saves confirmed loan data to user's profile.

            Call this ONLY when user confirms the loan details are their actual loan,
            not just a hypothetical scenario.

            Args:
                loan_type: Type of loan (e.g., "home_loan", "car_loan", "personal_loan")
                principal: Loan amount
                annual_rate_percent: Interest rate
                term_years: Loan term in years

            Returns:
                dict with confirmation message

            When to call:
            - AFTER showing a loan visualization
            - ONLY when user confirms "yes, this is my actual loan"
            - Do NOT call for hypothetical "what if" scenarios
            """
            return sync_confirm_loan_data(loan_type, principal, annual_rate_percent, term_years, db_url, session_id)

        # Return tools with names matching prompt references
        return [
            classify_goal,
            extract_financial_facts,
            determine_required_info,
            calculate_risk_profile,
            generate_visualization,
            confirm_loan_data,
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

        # Always create fresh agent to ensure profile context is up-to-date
        # Agent conversation history is still persisted in PostgreSQL
        if username in self._agents:
            logger.debug(f"[GET_AGENT_V2] Clearing cached agent to refresh profile context for: {username}")
            del self._agents[username]

        # Get user info
        user_repo = UserRepository(session)
        user = await user_repo.get_by_email(username)
        user_name = user.get("name") if user else None
        logger.debug(f"[GET_AGENT_V2] User name resolved: {user_name or 'Unknown'}")

        # Create tools (they create their own sessions internally)
        tools = self._create_session_tools(username)
        logger.debug(f"[GET_AGENT_V2] Created {len(tools)} tools: {[t.__name__ for t in tools]}")

        # Build instructions with user context
        instructions = AGENT_PROMPT_V2

        # Add user name
        if user_name:
            instructions += f"\n\nYou're speaking with {user_name}."

        # Add existing profile context for returning users
        profile_context = self._build_profile_context(username)
        if profile_context:
            instructions += profile_context
            instructions += """

## MANDATORY: CHECK PROFILE BEFORE EVERY QUESTION
Look at the profile data above. DO NOT ask about any field that already has a value:
- Savings/cash shows value → DON'T ask about savings/cash/emergency fund
- Age shows value → DON'T ask about age
- Debts shows entries → DON'T ask about debts
- Monthly income shows value → DON'T ask about income
- User JUST told you something → DON'T ask about it again

Ask only about fields that are MISSING from the profile above.
Use stored data for 'what if' scenarios (e.g., loan projections).
Violating this rule frustrates users!"""

        # Create agent with PostgreSQL storage for scalability
        agent = Agent(
            id=f"finance-educator-{username}",
            name="Vecta - Financial Educator",
            model=OpenAIChat(id="gpt-4.1"),
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
            model=OpenAIChat(id="gpt-4.1"),
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

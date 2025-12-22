"""
Agno Agent Service.

Provides agent management and greeting generation.
The main conversation processing is now handled by EducationPipeline.
This service is maintained for backward compatibility and greeting logic.
"""

import os
import logging
from typing import Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.config import settings
from app.core.prompts import (
    FINANCIAL_ADVISER_SYSTEM_PROMPT,
    GREETING_FIRST_TIME,
    GREETING_RETURNING_WITH_SUMMARY,
    GREETING_RETURNING_NO_SUMMARY,
)

# Configure logger
logger = logging.getLogger("agno_agent_service")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


class AgnoAgentService:
    """Service for managing Agno financial educator agents.

    Creates and reuses agents per user for performance (per .cursorrules).
    Each user gets their own agent instance with session history.
    Uses db_manager for fresh database sessions per operation.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._agents: dict[str, Agent] = {}  # Cache agents per user
        self._db_dir = "tmp/agents"

        # Create directory for agent databases if it doesn't exist
        os.makedirs(self._db_dir, exist_ok=True)

        # Set OpenAI API key from config if available
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

        logger.info("AgnoAgentService initialized")

    def _get_agent_instructions(self, user_name: Optional[str] = None) -> str:
        """Get instructions for the financial educator agent."""
        if user_name:
            return f"{FINANCIAL_ADVISER_SYSTEM_PROMPT}\n\nYou're speaking with {user_name}."
        return FINANCIAL_ADVISER_SYSTEM_PROMPT

    async def get_agent(self, username: str) -> Agent:
        """
        Get or create an Agno agent for a user.

        Reuses existing agent if available (per .cursorrules - never create agents in loops).

        Args:
            username: Username to get agent for

        Returns:
            Agent instance for the user
        """
        logger.debug(f"[GET_AGENT] Requested agent for user: {username}")

        if username in self._agents:
            logger.debug(f"[GET_AGENT] Returning cached agent for: {username}")
            return self._agents[username]

        logger.debug(f"[GET_AGENT] Creating new agent for: {username}")

        # Get user info with fresh session
        user = None
        async for session in self.db_manager.get_session():
            user_repo = UserRepository(session)
            user = await user_repo.get_by_email(username)

        user_name = user.get("name") if user else None
        logger.debug(f"[GET_AGENT] User name resolved: {user_name or 'Unknown'}")

        # Create agent with per-user database
        db_file = os.path.join(self._db_dir, f"agent_{username}.db")

        agent = Agent(
            name="Jamie (Financial Educator)",
            model=OpenAIChat(id="gpt-4o"),
            instructions=self._get_agent_instructions(user_name),
            db=SqliteDb(db_file=db_file),
            user_id=username,
            add_history_to_context=True,
            num_history_runs=10,  # Keep last 10 conversations in context
            markdown=True,
            debug_mode=False
        )

        # Cache agent for reuse
        self._agents[username] = agent
        logger.info(f"[GET_AGENT] Created and cached new agent for: {username}")

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
        return True  # Default to first-time if session fails

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

"""Context manager for maintaining conversation and financial context."""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.repositories.goal_state_repository import GoalStateRepository
from app.repositories.agent_session_repository import AgentSessionRepository
from app.models.financial import Goal
from sqlalchemy import select

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages context for multi-agent conversations."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    async def get_context(self, username: str) -> Dict[str, Any]:
        """
        Get complete context for a user including profile, goals, and session.
        
        Args:
            username: User email/username
            
        Returns:
            Dictionary with:
            - session: Current agent session
            - profile: Financial profile
            - goals: List of goals with states
            - user_id: User ID
        """
        async for session in self.db_manager.get_session():
            # Get user ID from profile
            profile_repo = FinancialProfileRepository(session)
            profile = await profile_repo.get_by_username(username) or {}
            
            if not profile:
                return {
                    "session": None,
                    "profile": {},
                    "goals": [],
                    "user_id": None,
                    "username": username,
                }
            
            user_id = profile.get("user_id")
            if not user_id:
                # Try to get from User model
                from app.repositories.user_repository import UserRepository
                user_repo = UserRepository(session)
                user = await user_repo.get_by_email(username)
                if user:
                    user_id = user.get("id")
            
            if not user_id:
                return {
                    "session": None,
                    "profile": profile,
                    "goals": [],
                    "user_id": None,
                    "username": username,
                }
            
            # Get goals with states
            goals = await self._get_goals_with_states(session, user_id)
            
            # Get or create session
            session_repo = AgentSessionRepository(session)
            agent_session = await session_repo.get_latest_by_user_id(user_id)
            if not agent_session:
                agent_session = await session_repo.create_session(user_id, phase="discovery")
            
            return {
                "session": agent_session,
                "profile": profile,
                "goals": goals,
                "user_id": user_id,
                "username": username,
            }

    async def _get_goals_with_states(
        self, session: AsyncSession, user_id: int
    ) -> list[Dict[str, Any]]:
        """Get all goals with their states."""
        # Get goals
        stmt = select(Goal).where(Goal.user_id == user_id).order_by(Goal.created_at.desc())
        result = await session.execute(stmt)
        goals = result.scalars().all()
        
        # Get goal states
        goal_state_repo = GoalStateRepository(session)
        all_states = await goal_state_repo.get_all_by_user_id(user_id)
        states_by_goal_id = {gs["goal_id"]: gs for gs in all_states}
        
        # Combine goals with states
        goals_with_states = []
        for goal in goals:
            goal_dict = goal.to_dict()
            goal_id = goal_dict["id"]
            goal_dict["state"] = states_by_goal_id.get(goal_id)
            goals_with_states.append(goal_dict)
        
        return goals_with_states

    async def update_session_phase(
        self, username: str, phase: str
    ) -> Optional[Dict[str, Any]]:
        """Update the current session phase."""
        context = await self.get_context(username)
        if not context.get("session"):
            return None
        
        session_id = context["session"]["session_id"]
        async for session in self.db_manager.get_session():
            session_repo = AgentSessionRepository(session)
            updated = await session_repo.update_phase(session_id, phase)
            return updated
        
        return None

    async def get_phase(self, username: str) -> str:
        """Get the current conversation phase."""
        context = await self.get_context(username)
        if context.get("session"):
            return context["session"].get("phase", "discovery")
        return "discovery"



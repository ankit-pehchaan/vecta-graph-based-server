"""Orchestrator agent coordinating all workflows - simplified to use AdvisorTeam."""
import logging
from typing import Dict, Any, Optional
from app.agents.advisor_team import AdvisorTeam
from app.agents.memory.context_manager import ContextManager

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    """
    Main orchestrator - simplified to delegate to AdvisorTeam.
    
    The AdvisorTeam uses LLM-based decision making instead of manual if/else logic.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.context_manager = ContextManager(db_manager)
        # AdvisorTeam instances are created per user/session
        self._advisor_teams: Dict[str, AdvisorTeam] = {}

    def _get_advisor_team(self, username: str, user_id: int) -> AdvisorTeam:
        """Get or create advisor team for user."""
        key = f"{username}_{user_id}"
        if key not in self._advisor_teams:
            self._advisor_teams[key] = AdvisorTeam(
                user_id=user_id,
                username=username,
                session_id=f"session_{user_id}",
            )
        return self._advisor_teams[key]

    async def process_message(
        self, username: str, message: str
    ) -> Dict[str, Any]:
        """
        Process a user message through the AdvisorTeam.
        
        The AdvisorTeam (Manager Agent) uses LLM to decide what to do next,
        eliminating manual if/else logic.
        
        Args:
            username: User email
            message: User's message
            
        Returns:
            Response dictionary with agent response and any visualizations
        """
        logger.info(f"Processing message from {username}")
        
        # Get user_id from context
        context = await self.context_manager.get_context(username)
        user_id = context.get("user_id")
        
        if not user_id:
            # Try to get from User model
            from app.repositories.user_repository import UserRepository
            async for session in self.db_manager.get_session():
                user_repo = UserRepository(session)
                user = await user_repo.get_by_email(username)
                if user:
                    user_id = user.get("id")
                    break
        
        if not user_id:
            return {
                "response": "I need to identify your account. Please ensure you're logged in.",
                "phase": "error",
                "visualization": None,
            }
        
        # Get or create advisor team
        advisor_team = self._get_advisor_team(username, user_id)
        
        # Process message through advisor team
        result = await advisor_team.process_message(message)
        
        return {
            "response": result.get("response", "I'm here to help with your financial goals."),
            "phase": result.get("phase", "discovery"),
            "visualization": result.get("visualization"),
        }


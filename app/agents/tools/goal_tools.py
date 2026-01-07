"""Goal management tools for agents."""
import logging
from typing import Dict, Any, Optional, List
from app.core.database import db_manager
from app.repositories.goal_state_repository import GoalStateRepository
from app.models.financial import Goal
from sqlalchemy import select

logger = logging.getLogger(__name__)


class GoalToolkit:
    """Tools for managing financial goals."""
    
    def __init__(self, user_id: int):
        """
        Initialize goal toolkit.
        
        Args:
            user_id: User ID for all operations
        """
        self.user_id = user_id
    
    async def save_goal(
        self,
        description: str,
        timeline_years: Optional[float] = None,
        amount: Optional[float] = None,
        motivation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save a new financial goal.
        
        Args:
            description: Goal description (e.g., "Buy a house", "Retire at 65")
            timeline_years: Years from now to achieve this goal
            amount: Target amount if mentioned
            motivation: Why this goal is important
            
        Returns:
            Dictionary with goal data including id
        """
        async for session in db_manager.get_session():
            # Check if goal already exists
            stmt = select(Goal).where(
                Goal.user_id == self.user_id,
                Goal.description == description
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing goal
                if timeline_years is not None:
                    existing.timeline_years = timeline_years
                if amount is not None:
                    existing.amount = amount
                if motivation is not None:
                    existing.motivation = motivation
                await session.flush()
                await session.refresh(existing)
                goal_dict = existing.to_dict()
            else:
                # Create new goal
                goal = Goal(
                    user_id=self.user_id,
                    description=description,
                    timeline_years=timeline_years,
                    amount=amount,
                    motivation=motivation,
                )
                session.add(goal)
                await session.flush()
                await session.refresh(goal)
                goal_dict = goal.to_dict()
            
            # Create or update goal state
            goal_state_repo = GoalStateRepository(session)
            goal_state = await goal_state_repo.create_or_update(
                goal_id=goal_dict["id"],
                user_id=self.user_id,
                status="discovered",
            )
            goal_dict["state"] = goal_state
            
            logger.info(f"Saved goal: {description} (ID: {goal_dict['id']})")
            return goal_dict
    
    async def get_goals(self) -> List[Dict[str, Any]]:
        """
        Get all goals for the user.
        
        Returns:
            List of goal dictionaries with states
        """
        async for session in db_manager.get_session():
            stmt = select(Goal).where(Goal.user_id == self.user_id).order_by(Goal.created_at.desc())
            result = await session.execute(stmt)
            goals = result.scalars().all()
            
            # Get goal states
            goal_state_repo = GoalStateRepository(session)
            all_states = await goal_state_repo.get_all_by_user_id(self.user_id)
            states_by_goal_id = {gs["goal_id"]: gs for gs in all_states}
            
            goals_with_states = []
            for goal in goals:
                goal_dict = goal.to_dict()
                goal_id = goal_dict["id"]
                goal_dict["state"] = states_by_goal_id.get(goal_id)
                goals_with_states.append(goal_dict)
            
            return goals_with_states
    
    async def check_goals_completeness(self) -> Dict[str, Any]:
        """
        Check if all goals have required information (timelines).
        
        Returns:
            Dictionary with:
            - all_complete: bool
            - goals_with_timelines: int
            - total_goals: int
            - missing_timelines: List[str] (goal descriptions)
        """
        goals = await self.get_goals()
        
        goals_with_timelines = [g for g in goals if g.get("timeline_years") is not None]
        missing_timelines = [
            g["description"] for g in goals 
            if g.get("timeline_years") is None
        ]
        
        return {
            "all_complete": len(goals_with_timelines) == len(goals) and len(goals) > 0,
            "goals_with_timelines": len(goals_with_timelines),
            "total_goals": len(goals),
            "missing_timelines": missing_timelines,
        }
    
    async def delete_goal(self, goal_id: int) -> bool:
        """
        Delete a goal.
        
        Args:
            goal_id: Goal ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        async for session in db_manager.get_session():
            stmt = select(Goal).where(
                Goal.id == goal_id,
                Goal.user_id == self.user_id
            )
            result = await session.execute(stmt)
            goal = result.scalar_one_or_none()
            
            if goal:
                await session.delete(goal)
                await session.flush()
                logger.info(f"Deleted goal ID: {goal_id}")
                return True
            return False



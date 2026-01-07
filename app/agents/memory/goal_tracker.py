"""Goal tracker for managing goal states and transitions."""
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.goal_state_repository import GoalStateRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.models.financial import Goal
from sqlalchemy import select

logger = logging.getLogger(__name__)


class GoalTracker:
    """Tracks goal states and manages goal lifecycle."""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    async def create_goal_state(
        self,
        user_id: int,
        goal_description: str,
        timeline_years: Optional[float] = None,
        amount: Optional[float] = None,
        motivation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new goal and its initial state.
        
        Args:
            user_id: User ID
            goal_description: Goal description
            timeline_years: Timeline in years
            amount: Target amount if mentioned
            motivation: Motivation for the goal
            
        Returns:
            Goal state dictionary
        """
        async for session in self.db_manager.get_session():
            # Create goal
            goal = Goal(
                user_id=user_id,
                description=goal_description,
                timeline_years=timeline_years,
                amount=amount,
                motivation=motivation,
            )
            session.add(goal)
            await session.flush()
            await session.refresh(goal)
            
            # Create goal state
            goal_state_repo = GoalStateRepository(session)
            goal_state = await goal_state_repo.create_or_update(
                goal_id=goal.id,
                user_id=user_id,
                status="discovered",
            )
            
            goal_dict = goal.to_dict()
            goal_dict["state"] = goal_state
            return goal_dict

    async def update_goal_state(
        self,
        goal_id: int,
        user_id: int,
        status: str,
        priority_rank: Optional[int] = None,
        priority_rationale: Optional[str] = None,
        completeness_score: Optional[int] = None,
        next_actions: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a goal state."""
        async for session in self.db_manager.get_session():
            goal_state_repo = GoalStateRepository(session)
            updated = await goal_state_repo.create_or_update(
                goal_id=goal_id,
                user_id=user_id,
                status=status,
                priority_rank=priority_rank,
                priority_rationale=priority_rationale,
                completeness_score=completeness_score,
                next_actions=next_actions,
            )
            return updated

    async def get_goals_by_status(
        self, user_id: int, status: str
    ) -> List[Dict[str, Any]]:
        """Get all goals with a specific status."""
        async for session in self.db_manager.get_session():
            goal_state_repo = GoalStateRepository(session)
            all_states = await goal_state_repo.get_all_by_user_id(user_id)
            
            # Filter by status
            filtered_states = [gs for gs in all_states if gs.get("status") == status]
            
            # Get goal details
            goals_with_states = []
            for state in filtered_states:
                goal_id = state["goal_id"]
                stmt = select(Goal).where(Goal.id == goal_id)
                result = await session.execute(stmt)
                goal = result.scalar_one_or_none()
                if goal:
                    goal_dict = goal.to_dict()
                    goal_dict["state"] = state
                    goals_with_states.append(goal_dict)
            
            return goals_with_states

    async def get_prioritized_goals(
        self, user_id: int
    ) -> List[Dict[str, Any]]:
        """Get all goals sorted by priority rank."""
        async for session in self.db_manager.get_session():
            goal_state_repo = GoalStateRepository(session)
            all_states = await goal_state_repo.get_all_by_user_id(user_id)
            
            # Sort by priority_rank (None goes last)
            sorted_states = sorted(
                all_states,
                key=lambda x: (x.get("priority_rank") is None, x.get("priority_rank") or 999)
            )
            
            # Get goal details
            goals_with_states = []
            for state in sorted_states:
                goal_id = state["goal_id"]
                stmt = select(Goal).where(Goal.id == goal_id)
                result = await session.execute(stmt)
                goal = result.scalar_one_or_none()
                if goal:
                    goal_dict = goal.to_dict()
                    goal_dict["state"] = state
                    goals_with_states.append(goal_dict)
            
            return goals_with_states

    async def detect_contradictions(
        self, user_id: int, new_goal_data: Dict[str, Any]
    ) -> List[str]:
        """
        Detect contradictions between new goal data and existing goals.
        
        Returns:
            List of contradiction descriptions
        """
        contradictions = []
        
        async for session in self.db_manager.get_session():
            # Get existing goals
            stmt = select(Goal).where(Goal.user_id == user_id)
            result = await session.execute(stmt)
            existing_goals = result.scalars().all()
            
            new_timeline = new_goal_data.get("timeline_years")
            new_amount = new_goal_data.get("amount")
            
            for existing_goal in existing_goals:
                existing_timeline = existing_goal.timeline_years
                existing_amount = existing_goal.amount
                
                # Check for timeline conflicts
                if new_timeline and existing_timeline:
                    # If timelines overlap significantly and amounts are similar, might be duplicate
                    timeline_diff = abs(new_timeline - existing_timeline)
                    if timeline_diff < 2 and new_amount and existing_amount:
                        amount_diff_pct = abs(new_amount - existing_amount) / max(new_amount, existing_amount)
                        if amount_diff_pct < 0.1:  # Within 10%
                            contradictions.append(
                                f"Similar goal already exists: {existing_goal.description} "
                                f"(timeline: {existing_timeline} years, amount: ${existing_amount:,.0f})"
                            )
        
        return contradictions

    async def mark_goal_complete(self, goal_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Mark a goal as completed."""
        return await self.update_goal_state(
            goal_id=goal_id,
            user_id=user_id,
            status="completed",
        )

    async def cancel_goal(self, goal_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Cancel a goal."""
        return await self.update_goal_state(
            goal_id=goal_id,
            user_id=user_id,
            status="cancelled",
        )



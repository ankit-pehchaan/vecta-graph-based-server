"""Analysis workflow for holistic view and decision."""
import logging
from typing import Dict, Any
from app.agents.analysis.holistic_view import HolisticViewBuilder
from app.agents.decision.decision_agent import DecisionAgent
from app.agents.memory.context_manager import ContextManager
from app.repositories.holistic_snapshot_repository import HolisticSnapshotRepository

logger = logging.getLogger(__name__)


class AnalysisWorkflow:
    """Workflow for building holistic view and making decisions."""

    def __init__(self, db_manager, context_manager: ContextManager):
        self.db_manager = db_manager
        self.context_manager = context_manager
        self.holistic_builder = HolisticViewBuilder()
        self.decision_agent = DecisionAgent()

    async def run(
        self,
        username: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run analysis workflow.
        
        Args:
            username: User email
            context: Current context
            
        Returns:
            Workflow result with holistic view and priorities
        """
        user_id = context.get("user_id")
        goals = context.get("goals", [])
        profile = context.get("profile", {})
        
        if not user_id:
            return {"error": "No user ID in context"}
        
        # Step 1: Build holistic view
        logger.info("Building holistic view")
        holistic_view = await self.holistic_builder.build_holistic_view(
            user_id=user_id,
            user_data=profile,
            goals=goals,
        )
        
        # Step 2: Store holistic snapshot
        async for session in self.db_manager.get_session():
            snapshot_repo = HolisticSnapshotRepository(session)
            await snapshot_repo.create(
                user_id=user_id,
                snapshot_data=holistic_view,
                gaps_identified=holistic_view.get("gaps_identified", []),
                opportunities=holistic_view.get("opportunities", []),
                risks=holistic_view.get("risks", []),
            )
        
        # Step 3: Prioritize goals
        logger.info("Prioritizing goals")
        decision_result = await self.decision_agent.prioritize_goals(
            goals=goals,
            holistic_view=holistic_view,
            user_data=profile,
        )
        
        # Step 4: Update goal states with priorities
        if user_id:
            from app.agents.memory.goal_tracker import GoalTracker
            goal_tracker = GoalTracker(self.db_manager)
            
            for priority in decision_result.priorities:
                await goal_tracker.update_goal_state(
                    goal_id=priority.goal_id,
                    user_id=user_id,
                    status="prioritized",
                    priority_rank=priority.rank,
                    priority_rationale=priority.rationale,
                )
            
            # Mark anchor goal as in_progress
            await goal_tracker.update_goal_state(
                goal_id=decision_result.anchor_goal_id,
                user_id=user_id,
                status="in_progress",
            )
        
        return {
            "phase": "education",
            "holistic_view": holistic_view,
            "priorities": decision_result.priorities,
            "anchor_goal_id": decision_result.anchor_goal_id,
            "anchor_goal_rationale": decision_result.anchor_goal_rationale,
        }



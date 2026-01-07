"""Discovery workflow for goal and fact finding."""
import logging
from typing import Dict, Any
from app.agents.discovery.goal_discovery import GoalDiscoveryAgent
from app.agents.discovery.fact_finding import FactFindingAgent
from app.agents.memory.goal_tracker import GoalTracker

logger = logging.getLogger(__name__)


class DiscoveryWorkflow:
    """Workflow for discovering goals and gathering facts."""

    def __init__(self, db_manager, goal_tracker: GoalTracker):
        self.db_manager = db_manager
        self.goal_tracker = goal_tracker
        self.goal_discovery = GoalDiscoveryAgent()
        self.fact_finding = FactFindingAgent()

    async def run(
        self,
        username: str,
        user_message: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run discovery workflow with HOLISTIC approach.
        
        CRITICAL: First discover ALL goals holistically, then gather ALL facts holistically.
        Do NOT dive into specific goals until holistic discovery is complete.
        
        Args:
            username: User email
            user_message: User's message
            context: Current context
            
        Returns:
            Workflow result with goals, facts, and next action
        """
        user_id = context.get("user_id")
        existing_goals = context.get("goals", [])
        profile = context.get("profile", {})
        phase = context.get("session", {}).get("phase", "discovery")
        
        # PHASE 1: HOLISTIC GOAL DISCOVERY
        if phase == "discovery":
            # Discover goals holistically
            discovery_result = await self.goal_discovery.discover_goals(
                user_message=user_message,
                existing_goals=existing_goals,
                user_profile=profile,
            )
            
            # Create new goals in database
            new_goals = []
            for discovered_goal in discovery_result.goals:
                # Check if goal already exists
                existing = next(
                    (g for g in existing_goals if g.get("description") == discovered_goal.description),
                    None
                )
                
                if not existing and user_id:
                    goal = await self.goal_tracker.create_goal_state(
                        user_id=user_id,
                        goal_description=discovered_goal.description,
                        timeline_years=discovered_goal.timeline_years_from_now,
                        amount=discovered_goal.amount_mentioned,
                        motivation=discovered_goal.motivation,
                    )
                    new_goals.append(goal)
            
            # Get all goals (existing + new)
            all_goals = existing_goals + new_goals
            
            # Check if ALL goals have timelines (holistic completion check)
            goals_with_timelines = [g for g in all_goals if g.get("timeline_years") is not None]
            all_goals_have_timelines = len(goals_with_timelines) > 0 and len(goals_with_timelines) == len(all_goals)
            
            if all_goals_have_timelines and discovery_result.ready_for_fact_finding:
                # ALL goals discovered with timelines - move to holistic fact finding
                logger.info(f"Holistic goal discovery complete: {len(all_goals)} goals with timelines")
                # Get first fact finding question
                fact_result = await self.fact_finding.identify_gaps(
                    goals=all_goals,
                    current_profile=profile,
                )
                return {
                    "phase": "fact_finding",
                    "goals_discovered": len(new_goals),
                    "total_goals": len(all_goals),
                    "ready_for_fact_finding": True,
                    "next_question": fact_result.next_question or "Now let me understand your complete financial picture. Tell me about your income and expenses.",
                    "ready_for_analysis": False,
                }
            else:
                # Still discovering goals or need timelines
                missing_count = len(all_goals) - len(goals_with_timelines)
                return {
                    "phase": "discovery",
                    "goals_discovered": len(new_goals),
                    "total_goals": len(all_goals),
                    "goals_with_timelines": len(goals_with_timelines),
                    "missing_timelines": discovery_result.missing_timelines,
                    "next_question": discovery_result.next_question or 
                                   (f"I see you have {len(all_goals)} goal(s). " +
                                    f"{'Let me know when you want to achieve each one.' if missing_count > 0 else 'Now let me understand your financial situation.'}"),
                    "ready_for_analysis": False,
                }
        
        # PHASE 2: HOLISTIC FACT FINDING
        elif phase == "fact_finding":
            # Gather facts holistically for ALL goals, not just one
            all_goals = existing_goals
            fact_result = await self.fact_finding.identify_gaps(
                goals=all_goals,
                current_profile=profile,
            )
            
            # Check holistic completeness (need 75%+ for all goals combined)
            completeness = fact_result.completeness_percentage
            ready_for_analysis = fact_result.ready_for_analysis and completeness >= 75
            
            if ready_for_analysis:
                logger.info(f"Holistic fact finding complete: {completeness}% completeness")
                return {
                    "phase": "fact_finding",
                    "completeness": completeness,
                    "next_question": "Perfect! I have a complete picture of your financial situation. Let me analyze everything holistically.",
                    "ready_for_analysis": True,
                }
            else:
                # Still gathering facts holistically
                return {
                    "phase": "fact_finding",
                    "fact_gaps": fact_result.gaps,
                    "completeness": completeness,
                    "next_question": fact_result.next_question or "I need a bit more information to give you comprehensive advice.",
                    "ready_for_analysis": False,
                }
        
        else:
            # Should not reach here in discovery workflow
            return {
                "phase": phase,
                "next_question": "Let me help you with your financial goals.",
                "ready_for_analysis": False,
            }


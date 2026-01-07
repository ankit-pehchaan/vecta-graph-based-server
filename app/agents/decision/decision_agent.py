"""Decision and prioritization agent."""
import os
import logging
from typing import Dict, Any, List, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.schemas.agent_schemas import DecisionResult, GoalPriority
from app.core.config import settings

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class DecisionAgent:
    """Agent for deciding goal priorities and selecting anchor goal."""

    def __init__(self, model_id: str = None):
        from app.core.config import settings
        self.model_id = model_id or settings.DECISION_MODEL
        self._agent: Optional[Agent] = None

    def _get_agent(self) -> Agent:
        """Get or create the agent instance."""
        if self._agent is None:
            instructions = """You are a financial decision and prioritization specialist. Your role is to:
1. Analyze all goals considering:
   - Urgency (timelines, age-dependent factors)
   - Impact (what's at stake)
   - Dependencies (foundation goals vs aspirational)
   - User preferences (stated priorities, risk tolerance)
   - Resource constraints (can't do everything at once)
2. Create priority ranking with clear rationale
3. Identify "anchor goal" to focus education on
4. Detect conflicting goals
5. Identify foundational gaps (e.g., "Need emergency fund first")

Return structured DecisionResult with priorities and anchor goal selection."""
            
            self._agent = Agent(
                name="Decision Agent",
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=DecisionResult,
                markdown=False,
                debug_mode=False,
            )
            logger.debug("Created Decision Agent")
        return self._agent

    async def prioritize_goals(
        self,
        goals: List[Dict[str, Any]],
        holistic_view: Dict[str, Any],
        user_data: Dict[str, Any],
    ) -> DecisionResult:
        """
        Prioritize goals and select anchor goal.
        
        Args:
            goals: List of goals with states
            holistic_view: Complete holistic view
            user_data: User financial profile
            
        Returns:
            DecisionResult with priorities
        """
        agent = self._get_agent()
        
        # Format goals for context
        goals_text = []
        for goal in goals:
            goal_id = goal.get("id")
            description = goal.get("description", "Unknown")
            timeline = goal.get("timeline_years")
            amount = goal.get("amount")
            state = goal.get("state", {})
            status = state.get("status", "discovered")
            
            goal_text = f"Goal ID {goal_id}: {description}"
            if timeline:
                goal_text += f" (timeline: {timeline} years)"
            if amount:
                goal_text += f" (amount: ${amount:,.0f})"
            goal_text += f" [Status: {status}]"
            goals_text.append(goal_text)
        
        goals_summary = "\n".join(goals_text) if goals_text else "No goals yet."
        
        # Format gaps and opportunities
        gaps = holistic_view.get("gaps_identified", [])
        opportunities = holistic_view.get("opportunities", [])
        
        prompt = f"""Prioritize these goals and select an anchor goal for education:

GOALS:
{goals_summary}

HOLISTIC VIEW:
- Gaps: {len(gaps)} identified
- Opportunities: {len(opportunities)} identified
- Readiness Score: {holistic_view.get('overall_readiness_score', 0)}/100

USER PROFILE:
- Age: {user_data.get('age', 'Unknown')}
- Income: ${user_data.get('income', 0):,.0f}/year
- Risk Tolerance: {user_data.get('risk_tolerance', 'Unknown')}

Consider:
1. Urgency (timelines, age factors)
2. Impact (what's at stake)
3. Dependencies (foundation goals first)
4. Resource constraints
5. User preferences

Return DecisionResult with:
- Priority ranking (1 = highest)
- Anchor goal ID and rationale
- Conflicting goals
- Foundational gaps"""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            
            if hasattr(response, 'content') and isinstance(response.content, DecisionResult):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = DecisionResult(**response.content)
            else:
                # Fallback: simple prioritization
                result = self._fallback_prioritization(goals)
            
            logger.info(f"Prioritized {len(result.priorities)} goals, anchor: {result.anchor_goal_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Decision prioritization failed: {e}")
            return self._fallback_prioritization(goals)

    def _fallback_prioritization(self, goals: List[Dict[str, Any]]) -> DecisionResult:
        """Fallback prioritization if agent fails."""
        if not goals:
            return DecisionResult(
                priorities=[],
                anchor_goal_id=0,
                anchor_goal_rationale="No goals to prioritize",
                conflicting_goals=[],
                foundational_gaps=[],
            )
        
        # Simple prioritization: by timeline (shorter first)
        sorted_goals = sorted(
            goals,
            key=lambda g: g.get("timeline_years", 999) or 999
        )
        
        priorities = []
        for idx, goal in enumerate(sorted_goals, 1):
            priorities.append(GoalPriority(
                goal_id=goal.get("id", 0),
                rank=idx,
                rationale=f"Prioritized by timeline",
                urgency_score=10 - idx,
                impact_score=8,
                feasibility_score=7,
            ))
        
        anchor_goal = sorted_goals[0]
        
        return DecisionResult(
            priorities=priorities,
            anchor_goal_id=anchor_goal.get("id", 0),
            anchor_goal_rationale="Shortest timeline goal selected",
            conflicting_goals=[],
            foundational_gaps=[],
        )


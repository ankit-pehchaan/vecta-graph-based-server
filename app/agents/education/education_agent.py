"""Education agent for personalized goal explanations."""
import os
import logging
from typing import Dict, Any, List, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.schemas.agent_schemas import EducationContent
from app.core.config import settings

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class EducationAgent:
    """Agent for educating users on prioritized goals."""

    def __init__(self, model_id: str = None):
        from app.core.config import settings
        self.model_id = model_id or settings.EDUCATION_MODEL
        self._agent: Optional[Agent] = None

    def _get_agent(self) -> Agent:
        """Get or create the agent instance."""
        if self._agent is None:
            instructions = """You are a financial education specialist. Your role is to:
1. Explain the prioritization decision in simple terms
2. Educate on the selected goal with user's specific data
3. Provide actionable next steps
4. Highlight trade-offs and alternatives
5. Quantify impact of recommendations

Be conversational, clear, and avoid jargon. Use the user's actual numbers."""
            
            self._agent = Agent(
                name="Education Agent",
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=EducationContent,
                markdown=True,
                debug_mode=False,
            )
            logger.debug("Created Education Agent")
        return self._agent

    async def educate_on_goal(
        self,
        goal: Dict[str, Any],
        holistic_view: Dict[str, Any],
        decision_result: Dict[str, Any],
        user_data: Dict[str, Any],
    ) -> EducationContent:
        """
        Generate education content for a goal.
        
        Args:
            goal: Goal to educate on
            holistic_view: Complete holistic view
            decision_result: Decision prioritization result
            user_data: User financial profile
            
        Returns:
            EducationContent with explanation and steps
        """
        agent = self._get_agent()
        
        goal_description = goal.get("description", "")
        timeline = goal.get("timeline_years")
        amount = goal.get("amount")
        
        anchor_rationale = decision_result.get("anchor_goal_rationale", "")
        
        # Get relevant specialist analysis
        specialist_analyses = holistic_view.get("specialist_analyses", {})
        
        prompt = f"""Educate the user on this prioritized goal:

GOAL: {goal_description}
Timeline: {timeline} years
Target Amount: ${amount:,.0f} if applicable

WHY THIS GOAL WAS PRIORITIZED:
{anchor_rationale}

USER'S CURRENT SITUATION:
- Income: ${user_data.get('income', 0):,.0f}/year
- Assets: ${sum(a.get('value', 0) or 0 for a in user_data.get('assets', [])):,.0f}
- Liabilities: ${sum(l.get('amount', 0) or 0 for l in user_data.get('liabilities', [])):,.0f}

RELEVANT ANALYSIS:
{self._format_analysis_for_goal(goal, specialist_analyses)}

Provide:
1. Clear explanation of the goal and current state
2. Key insights specific to their situation
3. Actionable next steps (3-5 steps)
4. Trade-offs and alternatives
5. Quantified impact if possible"""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            
            if hasattr(response, 'content') and isinstance(response.content, EducationContent):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = EducationContent(**response.content)
            else:
                # Fallback
                result = EducationContent(
                    goal_id=goal.get("id", 0),
                    explanation=f"Let's work on your goal: {goal_description}",
                    key_insights=[],
                    actionable_steps=["Review your current situation", "Set specific targets"],
                    trade_offs=[],
                )
            
            logger.info(f"Generated education content for goal {goal.get('id')}")
            return result
            
        except Exception as e:
            logger.error(f"Education generation failed: {e}")
            return EducationContent(
                goal_id=goal.get("id", 0),
                explanation=f"Let's work on your goal: {goal_description}",
                key_insights=[],
                actionable_steps=[],
                trade_offs=[],
            )

    def _format_analysis_for_goal(
        self, goal: Dict[str, Any], specialist_analyses: Dict[str, Any]
    ) -> str:
        """Format relevant specialist analysis for the goal."""
        goal_desc = goal.get("description", "").lower()
        
        parts = []
        
        if "retire" in goal_desc:
            retirement = specialist_analyses.get("retirement", {})
            if retirement:
                gap = retirement.get("gap_analysis", {})
                parts.append(f"Retirement Analysis: {gap.get('status', 'N/A')}")
        
        if "debt" in goal_desc or "loan" in goal_desc:
            debt = specialist_analyses.get("debt", {})
            if debt:
                total = debt.get("total_debt", 0)
                parts.append(f"Total Debt: ${total:,.0f}")
        
        return "\n".join(parts) if parts else "Analysis available"


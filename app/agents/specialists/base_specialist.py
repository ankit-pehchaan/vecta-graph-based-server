"""Base specialist class with common patterns."""
import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.core.config import settings

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class BaseSpecialist(ABC):
    """Base class for all specialist agents."""

    def __init__(
        self,
        name: str,
        model_id: str = None,
        instructions: str = "",
    ):
        from app.core.config import settings
        self.name = name
        self.model_id = model_id or settings.SPECIALIST_MODEL
        self.instructions = instructions
        self._agent: Optional[Agent] = None

    def _get_agent(self) -> Agent:
        """Get or create the agent instance (reused for performance)."""
        if self._agent is None:
            self._agent = Agent(
                name=self.name,
                model=OpenAIChat(id=self.model_id),
                instructions=self.instructions,
                markdown=True,
                debug_mode=False,
            )
            logger.debug(f"Created {self.name} agent")
        return self._agent

    @abstractmethod
    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze user data and goals.
        
        Args:
            user_data: Complete user financial profile
            goals: List of goals with states
            
        Returns:
            Structured analysis result
        """
        pass

    @abstractmethod
    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate recommendations based on analysis.
        
        Args:
            analysis_result: Result from analyze()
            
        Returns:
            List of recommendations with actions and impacts
        """
        pass

    async def estimate_impact(
        self, recommendation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Estimate the impact of a recommendation.
        
        Args:
            recommendation: Recommendation dictionary
            
        Returns:
            Impact estimation with quantified benefits
        """
        agent = self._get_agent()
        
        prompt = f"""Estimate the impact of this financial recommendation:

{recommendation.get('action', 'N/A')}

Provide:
1. Quantified benefit (e.g., "Save $X over Y years")
2. Time to see results
3. Risk level
4. Implementation difficulty

Return as structured data."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            impact_text = response.content if hasattr(response, 'content') else str(response)
            
            return {
                "quantified_benefit": impact_text,
                "recommendation": recommendation,
            }
        except Exception as e:
            logger.error(f"Error estimating impact: {e}")
            return {
                "quantified_benefit": "Impact analysis unavailable",
                "recommendation": recommendation,
            }

    def _format_user_data_summary(self, user_data: Dict[str, Any]) -> str:
        """Format user data for agent context."""
        parts = []
        
        if user_data.get("income"):
            parts.append(f"Income: ${user_data['income']:,.0f}/year")
        
        if user_data.get("expenses"):
            parts.append(f"Monthly Expenses: ${user_data['expenses']:,.0f}")
        
        assets = user_data.get("assets", [])
        if assets:
            total_assets = sum(a.get("value", 0) or 0 for a in assets)
            parts.append(f"Total Assets: ${total_assets:,.0f}")
        
        liabilities = user_data.get("liabilities", [])
        if liabilities:
            total_liabilities = sum(l.get("amount", 0) or 0 for l in liabilities)
            parts.append(f"Total Liabilities: ${total_liabilities:,.0f}")
        
        goals = user_data.get("goals", [])
        if goals:
            goal_descriptions = [g.get("description", "Unknown") for g in goals]
            parts.append(f"Goals: {', '.join(goal_descriptions)}")
        
        return "\n".join(parts) if parts else "Limited financial data available."


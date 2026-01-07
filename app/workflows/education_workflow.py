"""Education workflow for goal education and visualization."""
import os
import logging
from typing import Dict, Any, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.agents.education.education_agent import EducationAgent
from app.agents.education.visualization_agent import VisualizationAgent
from app.agents.analysis.scenario_modeling import ScenarioModelingAgent
from app.repositories.visualization_repository import VisualizationRepository
from app.core.config import settings
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class SpecialistSelection(BaseModel):
    """Result from specialist selection agent."""
    primary_specialist: str = Field(..., description="Primary specialist type: retirement, investment, tax, risk, cashflow, debt, asset")
    secondary_specialists: list[str] = Field(default_factory=list, description="Additional relevant specialists")
    reasoning: str = Field(..., description="Why this specialist is most relevant")


class EducationWorkflow:
    """Workflow for educating on prioritized goal with visualizations."""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.education_agent = EducationAgent()
        self.visualization_agent = VisualizationAgent()
        self.scenario_agent = ScenarioModelingAgent()
        self._specialist_selector: Optional[Agent] = None

    async def run(
        self,
        username: str,
        anchor_goal: Dict[str, Any],
        holistic_view: Dict[str, Any],
        decision_result: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run education workflow.
        
        Args:
            username: User email
            anchor_goal: Goal to educate on
            holistic_view: Complete holistic view
            decision_result: Decision prioritization result
            context: Current context
            
        Returns:
            Workflow result with education content and visualization
        """
        user_id = context.get("user_id")
        profile = context.get("profile", {})
        
        # Step 1: Generate education content
        logger.info(f"Generating education for goal {anchor_goal.get('id')}")
        education_content = await self.education_agent.educate_on_goal(
            goal=anchor_goal,
            holistic_view=holistic_view,
            decision_result=decision_result,
            user_data=profile,
        )
        
        # Step 2: Run scenario modeling
        scenarios = await self.scenario_agent.run_scenarios(
            goal=anchor_goal,
            user_data=profile,
        )
        
        # Step 3: Get relevant specialist analysis (LLM decides which specialist is most relevant)
        specialist_analyses = holistic_view.get("specialist_analyses", {})
        relevant_analysis = await self._get_relevant_analysis(anchor_goal, specialist_analyses)
        
        # Step 4: Generate visualization
        logger.info("Generating visualization")
        visualization = await self.visualization_agent.generate_visualization(
            goal=anchor_goal,
            analysis=relevant_analysis,
            scenarios=[s.model_dump() if hasattr(s, 'model_dump') else s for s in scenarios],
            education_content=education_content.model_dump() if hasattr(education_content, 'model_dump') else education_content,
        )
        
        # Step 5: Store visualization
        if user_id:
            async for session in self.db_manager.get_session():
                viz_repo = VisualizationRepository(session)
                await viz_repo.create(
                    user_id=user_id,
                    goal_id=anchor_goal.get("id"),
                    viz_type=visualization.chart.kind if visualization.chart else "line",
                    spec_data=visualization.model_dump(),
                )
        
        return {
            "phase": "education",
            "education_content": education_content.model_dump() if hasattr(education_content, 'model_dump') else education_content,
            "visualization": visualization.model_dump() if hasattr(visualization, 'model_dump') else visualization,
            "scenarios": [s.model_dump() if hasattr(s, 'model_dump') else s for s in scenarios],
        }

    def _get_specialist_selector(self) -> Agent:
        """Get or create the specialist selection agent."""
        if self._specialist_selector is None:
            instructions = """You are a specialist selection agent. Your role is to analyze a financial goal and determine which specialist analysis is most relevant.

Available specialists:
- retirement: For retirement planning, superannuation, retirement income goals
- investment: For investment strategy, asset allocation, portfolio optimization
- tax: For tax planning, tax optimization, tax-efficient strategies
- risk: For risk management, insurance, emergency funds, risk assessment
- cashflow: For cash flow management, budgeting, savings strategies
- debt: For debt management, loan analysis, debt payoff strategies
- asset: For asset analysis, property, investment assets, asset optimization

Analyze the goal description, timeline, and amount to determine which specialist's analysis would be most relevant for educating the user about this goal.

Return the primary specialist and optionally secondary specialists that might also be relevant."""
            
            from app.core.config import settings
            self._specialist_selector = Agent(
                name="Specialist Selector",
                model=OpenAIChat(id=settings.ORCHESTRATOR_MODEL),
                instructions=instructions,
                output_schema=SpecialistSelection,
                markdown=False,
                debug_mode=False,
            )
            logger.debug("Created Specialist Selector agent")
        return self._specialist_selector

    async def _get_relevant_analysis(
        self, goal: Dict[str, Any], specialist_analyses: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get relevant specialist analysis for a goal using LLM to decide.
        
        Args:
            goal: Goal dictionary
            specialist_analyses: All available specialist analyses
            
        Returns:
            Most relevant specialist analysis dictionary
        """
        if not specialist_analyses:
            return {}
        
        agent = self._get_specialist_selector()
        
        goal_description = goal.get("description", "")
        timeline = goal.get("timeline_years")
        amount = goal.get("amount")
        
        # Format available specialists for context
        available_specialists = list(specialist_analyses.keys())
        
        prompt = f"""Analyze this financial goal and determine which specialist analysis is most relevant:

GOAL:
Description: {goal_description}
Timeline: {timeline} years (if known)
Target Amount: ${amount:,.0f} (if known)

AVAILABLE SPECIALIST ANALYSES:
{', '.join(available_specialists)}

Determine which specialist's analysis would be most relevant for educating the user about this specific goal. Consider the goal's nature, timeline, and financial aspects."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            
            if hasattr(response, 'content') and isinstance(response.content, SpecialistSelection):
                selection = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                selection = SpecialistSelection(**response.content)
            else:
                # Fallback: return first available analysis
                logger.warning("Specialist selection failed, using fallback")
                return specialist_analyses.get(list(specialist_analyses.keys())[0], {}) if specialist_analyses else {}
            
            # Get the primary specialist analysis
            primary_analysis = specialist_analyses.get(selection.primary_specialist, {})
            
            logger.info(
                f"Selected specialist: {selection.primary_specialist} "
                f"(reasoning: {selection.reasoning[:100]}...)"
            )
            
            # Optionally merge with secondary specialists if needed
            if selection.secondary_specialists and len(primary_analysis) == 0:
                # If primary not found, try secondary
                for secondary in selection.secondary_specialists:
                    if secondary in specialist_analyses:
                        primary_analysis = specialist_analyses[secondary]
                        break
            
            return primary_analysis
            
        except Exception as e:
            logger.error(f"Specialist selection failed: {e}")
            # Fallback: return first available analysis
            return specialist_analyses.get(list(specialist_analyses.keys())[0], {}) if specialist_analyses else {}


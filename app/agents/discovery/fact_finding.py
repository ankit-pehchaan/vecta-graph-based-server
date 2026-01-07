"""Fact finding agent for gathering financial facts for goals."""
import os
import logging
from typing import Dict, Any, List, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.schemas.agent_schemas import FactFindingResult, FactGap
from app.core.config import settings
from app.core.agent_storage import get_agent_storage
from app.agents.tools.profile_tools import ProfileToolkit

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class FactFindingAgent:
    """Agent for gathering financial facts needed for goal analysis."""

    def __init__(self, model_id: str = None, user_id: int = None, username: str = None, session_id: str = None):
        from app.core.config import settings
        self.model_id = model_id or settings.DISCOVERY_MODEL
        self.user_id = user_id
        self.username = username
        self.session_id = session_id or f"fact_finding_{user_id}" if user_id else "fact_finding"
        self._agent: Optional[Agent] = None
        self._profile_toolkit: Optional[ProfileToolkit] = None

    def _get_profile_toolkit(self) -> ProfileToolkit:
        """Get or create profile toolkit."""
        if self._profile_toolkit is None and self.user_id and self.username:
            self._profile_toolkit = ProfileToolkit(user_id=self.user_id, username=self.username)
        return self._profile_toolkit

    def _get_agent(self) -> Agent:
        """Get or create the agent instance with storage and history."""
        if self._agent is None:
            instructions = """You are a financial fact-finding specialist focused on HOLISTIC fact gathering.

CRITICAL: Your job is to gather ALL financial facts needed for ALL goals BEFORE moving to analysis.

Your role:
1. Review ALL discovered goals holistically and identify what financial facts are needed across ALL goals
2. Conversationally gather facts without feeling like an interrogation
3. Identify gaps in financial information holistically (not goal-by-goal, but overall picture)
4. Prioritize which facts are most critical to gather first (foundational facts first)
5. Generate natural questions to ask the user
6. Continue gathering until you have a COMPLETE financial picture (75%+ completeness)

Facts needed holistically (for ALL goals):
- Life foundation: age, family status, dependents, location, career stage
- Financial foundation: income, monthly income, expenses, savings rate
- Assets: all assets (cash, investments, property, superannuation) with values
- Liabilities: all debts (mortgages, loans, credit cards) with amounts, rates, payments
- Insurance: coverage across all types (life, health, income protection, etc.)
- Risk tolerance and preferences

For specific goal types, additional facts:
- Retirement: desired retirement age, current super balance, contribution rates
- Home purchase: down payment target, current savings, location preferences
- Emergency fund: monthly expenses, existing cash, job stability
- Education: number of children, ages, target schools, current savings
- Debt payoff: all debts with amounts, interest rates, minimum payments

CRITICAL RULES:
- Gather facts holistically - don't focus on one goal at a time
- Get foundational facts first (income, expenses, assets, liabilities)
- Then get goal-specific facts if needed
- Only mark ready_for_analysis when completeness is 75%+ for ALL goals combined

Return structured FactFindingResult with gaps and suggested questions."""
            
            # Don't use tools - handle DB operations separately for reliability
            # Tools can cause hanging issues with async operations
            self._agent = Agent(
                name="Fact Finding Agent",
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=FactFindingResult,
                db=get_agent_storage(),
                user_id=str(self.user_id) if self.user_id else self.session_id,
                add_history_to_context=True,
                num_history_runs=10,
                markdown=False,
                debug_mode=False,
            )
            logger.debug(f"Created Fact Finding Agent with storage for user {self.user_id}")
        return self._agent

    async def identify_gaps(
        self,
        goals: List[Dict[str, Any]],
        current_profile: Dict[str, Any],
    ) -> FactFindingResult:
        """
        Identify gaps in financial facts needed for goals.
        
        Args:
            goals: List of goals with states
            current_profile: Current financial profile
            
        Returns:
            FactFindingResult with gaps and completeness
        """
        agent = self._get_agent()
        
        # Format goals for context
        goals_text = []
        for goal in goals:
            goal_desc = goal.get("description", "Unknown")
            timeline = goal.get("timeline_years")
            amount = goal.get("amount")
            goal_text = f"- {goal_desc}"
            if timeline:
                goal_text += f" (timeline: {timeline} years)"
            if amount:
                goal_text += f" (amount: ${amount:,.0f})"
            goals_text.append(goal_text)
        
        goals_summary = "\n".join(goals_text) if goals_text else "No goals yet."
        
        # Format current profile
        profile_summary = self._format_profile(current_profile)
        
        prompt = f"""Review ALL goals holistically and current profile to identify what financial facts are still needed.

CRITICAL: Think holistically across ALL goals, not goal-by-goal. Gather foundational facts first (income, expenses, assets, liabilities), then goal-specific facts if needed.

ALL GOALS:
{goals_summary}

CURRENT PROFILE:
{profile_summary}

Holistically identify:
1. Foundational facts missing (income, expenses, assets, liabilities, age, family status)
2. Goal-specific facts missing (only if foundational facts are complete)
3. What facts are partially known (need clarification)
4. Suggested natural questions to ask (one at a time, conversationally)

Calculate overall completeness percentage (0-100) for ALL goals combined.
- 0-50%: Need foundational facts (income, expenses, basic assets/liabilities)
- 50-75%: Need more details (specific amounts, rates, timelines)
- 75%+: Ready for holistic analysis

Return FactFindingResult with gaps, completeness, and next question. Only mark ready_for_analysis when completeness >= 75%."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            
            if hasattr(response, 'content') and isinstance(response.content, FactFindingResult):
                result = response.content
            elif hasattr(response, 'content') and isinstance(response.content, dict):
                result = FactFindingResult(**response.content)
            else:
                result = FactFindingResult(gaps=[], completeness_percentage=0)
            
            logger.info(f"Identified {len(result.gaps)} fact gaps, completeness: {result.completeness_percentage}%")
            
            return result
            
        except Exception as e:
            logger.error(f"Fact finding failed: {e}")
            return FactFindingResult(gaps=[], completeness_percentage=0)

    async def generate_question(
        self,
        gap: FactGap,
        conversation_context: str = "",
    ) -> str:
        """Generate a natural question to ask about a specific gap."""
        agent = self._get_agent()
        
        prompt = f"""Generate a natural, conversational question to gather this financial fact:

FIELD: {gap.field_name}
TYPE: {gap.field_type}
IMPORTANCE: {gap.importance}

CONTEXT: {conversation_context}

Make it sound natural, not like a form. Be warm and conversational."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            question = response.content if hasattr(response, 'content') else str(response)
            return question.strip()
        except Exception as e:
            logger.error(f"Failed to generate question: {e}")
            return gap.suggested_question or f"Can you tell me about your {gap.field_name}?"

    def _format_profile(self, profile: Dict[str, Any]) -> str:
        """Format profile for agent context."""
        parts = []
        
        if profile.get("income"):
            parts.append(f"Income: ${profile['income']:,.0f}/year")
        
        if profile.get("expenses"):
            parts.append(f"Monthly Expenses: ${profile['expenses']:,.0f}")
        
        assets = profile.get("assets", [])
        if assets:
            total = sum(a.get("value", 0) or 0 for a in assets)
            parts.append(f"Assets: {len(assets)} items, ${total:,.0f} total")
        
        liabilities = profile.get("liabilities", [])
        if liabilities:
            total = sum(l.get("amount", 0) or 0 for l in liabilities)
            parts.append(f"Liabilities: {len(liabilities)} items, ${total:,.0f} total")
        
        superannuation = profile.get("superannuation", [])
        if superannuation:
            total = sum(s.get("balance", 0) or 0 for s in superannuation)
            parts.append(f"Superannuation: ${total:,.0f}")
        
        return "\n".join(parts) if parts else "Limited profile data available."


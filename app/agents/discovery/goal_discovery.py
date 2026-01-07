"""Goal discovery agent for eliciting all user goals with timelines."""
import os
import logging
from typing import Dict, Any, List, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.schemas.agent_schemas import GoalDiscoveryResult, DiscoveredGoal
from app.core.config import settings
from app.core.agent_storage import get_agent_storage
from app.agents.tools.goal_tools import GoalToolkit

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class GoalDiscoveryAgent:
    """Agent for discovering all user goals with explicit timelines."""

    def __init__(self, model_id: str = None, user_id: int = None, session_id: str = None):
        from app.core.config import settings
        self.model_id = model_id or settings.DISCOVERY_MODEL
        self.user_id = user_id
        self.session_id = session_id or f"goal_discovery_{user_id}" if user_id else "goal_discovery"
        self._agent: Optional[Agent] = None
        self._goal_toolkit: Optional[GoalToolkit] = None

    def _get_goal_toolkit(self) -> GoalToolkit:
        """Get or create goal toolkit."""
        if self._goal_toolkit is None and self.user_id:
            self._goal_toolkit = GoalToolkit(user_id=self.user_id)
        return self._goal_toolkit

    def _get_agent(self) -> Agent:
        """Get or create the agent instance with storage and history."""
        if self._agent is None:
            instructions = """You are a financial goal discovery specialist focused on HOLISTIC discovery.

CRITICAL: Your job is to discover ALL of the user's financial goals BEFORE diving into any specific goal.

Your role:
1. Conversationally discover ALL financial goals holistically (retirement, home, education, emergency fund, debt payoff, etc.)
2. For EACH goal mentioned, ALWAYS ask "When do you want to achieve this?" - NEVER assume timelines
3. Extract specific timelines from user answers (e.g., "in 3 years", "by age 65", "2027")
4. If timeline not stated, ask follow-up: "What's your target timeframe for this?"
5. Identify implicit goals from life context (e.g., family = likely education goal, age = retirement planning)
6. Use the save_goal tool to persist goals as you discover them
7. Use get_goals tool to check what goals have been discovered
8. Use check_goals_completeness tool to verify all goals have timelines
9. Continue exploring until you've discovered ALL goals - don't rush to fact finding

CRITICAL RULES:
- NEVER categorize goals as "short-term" or "long-term" without asking for timeline
- NEVER assume retirement age - always ask "When are you hoping to retire?"
- NEVER dive into specific goal details until ALL goals are discovered
- For home purchase, ask "When are you planning to buy?"
- For education goals, ask "When will the children start college/university?"
- Ask exploratory questions: "What other financial goals do you have?" "Is there anything else you're saving for?"
- Extract timeline as stated, then calculate years from now if possible
- Remember previous conversation - don't ask the same questions twice

Return structured GoalDiscoveryResult with all discovered goals and their timelines. Only mark ready_for_fact_finding when you're confident you've discovered ALL goals."""
            
            # Don't use tools - handle DB operations separately for reliability
            # Tools can cause hanging issues with async operations
            self._agent = Agent(
                name="Goal Discovery Agent",
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=GoalDiscoveryResult,
                db=get_agent_storage(),
                user_id=str(self.user_id) if self.user_id else self.session_id,
                add_history_to_context=True,
                num_history_runs=10,
                markdown=False,
                debug_mode=False,
            )
            logger.debug(f"Created Goal Discovery Agent with storage for user {self.user_id}")
        return self._agent

    async def discover_goals(
        self,
        user_message: str,
        existing_goals: List[Dict[str, Any]] = None,
        user_profile: Dict[str, Any] = None,
    ) -> GoalDiscoveryResult:
        """
        Discover goals from user message.
        
        Args:
            user_message: User's message
            existing_goals: Previously discovered goals
            user_profile: User's financial profile
            
        Returns:
            GoalDiscoveryResult with discovered goals
        """
        agent = self._get_agent()
        
        # Build context
        context_parts = []
        
        if user_profile:
            age = user_profile.get("age")
            if age:
                context_parts.append(f"User is {age} years old")
            
            family_status = user_profile.get("family_status")
            if family_status:
                context_parts.append(f"Family: {family_status}")
        
        if existing_goals:
            goal_descriptions = [g.get("description", "Unknown") for g in existing_goals]
            context_parts.append(f"Previously discovered goals: {', '.join(goal_descriptions)}")
        
        context = "\n".join(context_parts) if context_parts else "No prior context."
        
        prompt = f"""Analyze this user message to discover financial goals. Remember to ask about timelines for each goal.

CONTEXT:
{context}

USER MESSAGE:
{user_message}

Identify:
1. All goals mentioned (explicit or implicit)
2. For each goal, extract timeline if stated, or note that timeline needs to be asked
3. Any life context that suggests additional goals

Return GoalDiscoveryResult with all discovered goals and their timeline information."""
        
        try:
            logger.info(f"Calling goal discovery agent with prompt length: {len(prompt)}")
            # Use arun for async execution
            response = await agent.arun(prompt)
            logger.info(f"Goal discovery agent responded, type: {type(response)}")
            
            # Extract content from response
            if hasattr(response, 'content'):
                content = response.content
                logger.info(f"Response has content, type: {type(content)}")
                
                if isinstance(content, GoalDiscoveryResult):
                    result = content
                elif isinstance(content, dict):
                    result = GoalDiscoveryResult(**content)
                elif isinstance(content, str):
                    # Try to parse as JSON if it's a string
                    import json
                    try:
                        parsed = json.loads(content)
                        result = GoalDiscoveryResult(**parsed)
                    except:
                        logger.warning(f"Could not parse string content: {content}")
                        result = GoalDiscoveryResult(goals=[])
                else:
                    logger.warning(f"Unexpected content type: {type(content)}, value: {content}")
                    result = GoalDiscoveryResult(goals=[])
            elif hasattr(response, 'text'):
                # Fallback: try text attribute
                logger.info("Response has text attribute, trying to parse")
                import json
                try:
                    parsed = json.loads(response.text)
                    result = GoalDiscoveryResult(**parsed)
                except:
                    result = GoalDiscoveryResult(goals=[])
            else:
                logger.warning(f"Response has no content/text attribute, response: {response}, type: {type(response)}")
                # Last resort: create empty result with a question
                result = GoalDiscoveryResult(
                    goals=[],
                    next_question="Tell me about your financial goals.",
                    ready_for_fact_finding=False
                )
            
            logger.info(f"Discovered {len(result.goals)} goals")
            if result.next_question:
                logger.info(f"Next question: {result.next_question[:100]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Goal discovery failed: {e}", exc_info=True)
            # Return a helpful response even on error
            return GoalDiscoveryResult(
                goals=[],
                next_question="I'm here to help you plan your financial goals. What would you like to achieve?",
                ready_for_fact_finding=False
            )

    async def ask_timeline_followup(
        self, goal_description: str
    ) -> str:
        """Generate a follow-up question to ask about timeline for a goal."""
        agent = self._get_agent()
        
        prompt = f"""Generate a natural, conversational question to ask about the timeline for this goal:

GOAL: {goal_description}

Ask when they want to achieve this goal. Be specific and natural, not robotic."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            question = response.content if hasattr(response, 'content') else str(response)
            return question.strip()
        except Exception as e:
            logger.error(f"Failed to generate timeline question: {e}")
            return f"When do you want to achieve this goal: {goal_description}?"


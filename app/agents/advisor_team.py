"""Advisor Team - Manager agent coordinating all specialized agents."""
import os
import logging
from typing import Dict, Any, Optional
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.core.config import settings
from app.core.agent_storage import get_agent_storage
from app.agents.discovery.goal_discovery import GoalDiscoveryAgent
from app.agents.discovery.fact_finding import FactFindingAgent
from app.agents.tools.goal_tools import GoalToolkit
from app.agents.tools.profile_tools import ProfileToolkit

logger = logging.getLogger(__name__)

# Set OpenAI API key from settings
if settings.OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY


class AdvisorTeam:
    """
    Financial Advisor Manager Agent - The "Brain" that coordinates all workflows.
    
    This agent uses LLM-based decision making instead of manual if/else logic.
    It manages the holistic discovery flow:
    1. Discover ALL goals
    2. Gather ALL facts
    3. Present goals for user selection
    4. Deep dive into selected goal
    """
    
    def __init__(self, user_id: int, username: str, session_id: str = None):
        """
        Initialize the advisor team.
        
        Args:
            user_id: User ID
            username: User email/username
            session_id: Session ID for conversation history
        """
        self.user_id = user_id
        self.username = username
        self.session_id = session_id or f"advisor_{user_id}"
        
        # Initialize toolkits
        self.goal_toolkit = GoalToolkit(user_id=user_id)
        self.profile_toolkit = ProfileToolkit(user_id=user_id, username=username)
        
        # Initialize specialized agents
        self.goal_discovery = GoalDiscoveryAgent(user_id=user_id, session_id=f"{self.session_id}_goals")
        self.fact_finding = FactFindingAgent(
            user_id=user_id, 
            username=username, 
            session_id=f"{self.session_id}_facts"
        )
        
        # Manager agent (the brain)
        self._manager_agent: Optional[Agent] = None
    
    def _get_manager_agent(self) -> Agent:
        """Get or create the manager agent."""
        if self._manager_agent is None:
            instructions = """You are the Financial Advisor Manager - the coordinating brain of the financial advisory system.

Your role is to manage the conversation flow and delegate to specialized agents based on the current phase.

WORKFLOW PHASES (must be followed in order):

PHASE 1: HOLISTIC GOAL DISCOVERY
- Your job: Discover ALL of the user's financial goals before moving forward
- Delegate to: GoalDiscoveryAgent
- Continue until: ALL goals have been discovered with timelines
- Use tools: get_goals, check_goals_completeness
- Only move to Phase 2 when ALL goals have timelines

PHASE 2: HOLISTIC FACT FINDING
- Your job: Gather ALL financial facts needed for ALL goals
- Delegate to: FactFindingAgent
- Continue until: Profile completeness >= 75%
- Use tools: get_profile, get_profile_gaps
- Only move to Phase 3 when profile is complete enough

PHASE 3: GOAL PRESENTATION
- Your job: Present all discovered goals to the user and ask which one to deep dive into
- Format: List all goals clearly with timelines and amounts
- Ask: "Which goal would you like to explore in detail?"
- Wait for user selection

PHASE 4: DEEP DIVE ANALYSIS
- Your job: Provide detailed analysis and education for the selected goal
- Delegate to: Analysis and Education agents (to be implemented)
- Provide: Detailed recommendations, visualizations, scenarios

CRITICAL RULES:
- NEVER skip phases - always complete holistic discovery first
- NEVER dive into specific goals until ALL goals are discovered
- Use conversation history to avoid repetitive questions
- Remember what has been asked/answered
- Be conversational and natural, not robotic
- Track current phase in your memory

When the user sends a message:
1. Check current phase using tools
2. Delegate to appropriate agent or handle directly
3. Return natural, conversational response
4. Update phase when transitioning"""
            
            # Don't use tools - we handle phase management programmatically
            # Tools can cause hanging issues with async operations
            self._manager_agent = Agent(
                name="Financial Advisor Manager",
                model=OpenAIChat(id=settings.ORCHESTRATOR_MODEL),
                instructions=instructions,
                db=get_agent_storage(),
                user_id=self.session_id,
                add_history_to_context=True,
                num_history_runs=20,  # More history for manager
                markdown=False,
                debug_mode=False,
            )
            logger.debug(f"Created Advisor Manager Agent for user {self.user_id}")
        
        return self._manager_agent
    
    async def process_message(self, message: str) -> Dict[str, Any]:
        """
        Process a user message through the advisor team.
        
        Args:
            message: User's message
            
        Returns:
            Dictionary with response and metadata
        """
        manager = self._get_manager_agent()
        
        # Get current state
        goals = await self.goal_toolkit.get_goals()
        goals_completeness = await self.goal_toolkit.check_goals_completeness()
        profile = await self.profile_toolkit.get_profile()
        
        # Build context for manager
        context_parts = []
        
        if goals:
            context_parts.append(f"Discovered {len(goals)} goal(s):")
            for goal in goals:
                desc = goal.get("description", "Unknown")
                timeline = goal.get("timeline_years")
                amount = goal.get("amount")
                timeline_str = f" (timeline: {timeline} years)" if timeline else " (timeline missing)"
                amount_str = f" (amount: ${amount:,.0f})" if amount else ""
                context_parts.append(f"  - {desc}{timeline_str}{amount_str}")
        else:
            context_parts.append("No goals discovered yet.")
        
        if goals_completeness.get("all_complete"):
            context_parts.append("All goals have timelines - ready for fact finding.")
        else:
            missing = goals_completeness.get("missing_timelines", [])
            if missing:
                context_parts.append(f"Goals missing timelines: {', '.join(missing)}")
        
        # Get profile gaps for context and phase determination
        profile_gaps = await self.profile_toolkit.get_profile_gaps(goals)
        completeness = profile_gaps.get("completeness_percentage", 0)
        
        if profile:
            context_parts.append(f"Profile completeness: {completeness}%")
            if completeness >= 75:
                context_parts.append("Profile is complete enough for analysis.")
            else:
                context_parts.append(f"Profile gaps: {', '.join(profile_gaps.get('critical_gaps', []))}")
        
        context = "\n".join(context_parts)
        
        # Determine which agent to use based on current state
        # Phase 1: Goal Discovery - Check if all goals have timelines
        if not goals_completeness.get("all_complete") or len(goals) == 0:
            logger.info("Phase 1: Goal Discovery")
            try:
                import asyncio
                # Add timeout to prevent hanging
                discovery_result = await asyncio.wait_for(
                    self.goal_discovery.discover_goals(
                        user_message=message,
                        existing_goals=goals,
                        user_profile=profile,
                    ),
                    timeout=30.0  # 30 second timeout
                )
                logger.info(f"Discovery result: {len(discovery_result.goals)} goals, next_question: {discovery_result.next_question}")
                
                # Save discovered goals
                for discovered_goal in discovery_result.goals:
                    try:
                        await self.goal_toolkit.save_goal(
                            description=discovered_goal.description,
                            timeline_years=discovered_goal.timeline_years_from_now,
                            amount=discovered_goal.amount_mentioned,
                            motivation=discovered_goal.motivation,
                        )
                    except Exception as e:
                        logger.error(f"Error saving goal: {e}")
                
                response_text = discovery_result.next_question or "Tell me about your financial goals."
                logger.info(f"Returning response: {response_text[:100]}...")
                return {
                    "response": response_text,
                    "phase": "discovery",
                    "goals_discovered": len(discovery_result.goals),
                }
            except asyncio.TimeoutError:
                logger.error("Goal discovery timed out after 30 seconds")
                return {
                    "response": "I'm taking a bit longer than usual. Could you tell me about your financial goals?",
                    "phase": "discovery",
                    "goals_discovered": 0,
                }
            except Exception as e:
                logger.error(f"Error in goal discovery: {e}", exc_info=True)
                return {
                    "response": "I'm having trouble understanding your goals. Could you tell me about your financial goals?",
                    "phase": "discovery",
                    "goals_discovered": 0,
                }
        
        # Phase 2: Fact Finding - Check profile completeness
        
        if completeness < 75:
            logger.info("Phase 2: Fact Finding")
            try:
                import asyncio
                # Add timeout to prevent hanging
                fact_result = await asyncio.wait_for(
                    self.fact_finding.identify_gaps(
                        goals=goals,
                        current_profile=profile,
                    ),
                    timeout=30.0  # 30 second timeout
                )
                
                return {
                    "response": fact_result.next_question or "I need a bit more information about your financial situation.",
                    "phase": "fact_finding",
                    "completeness": fact_result.completeness_percentage,
                }
            except asyncio.TimeoutError:
                logger.error("Fact finding timed out after 30 seconds")
                return {
                    "response": "I'm taking a bit longer than usual. Could you tell me about your income and expenses?",
                    "phase": "fact_finding",
                    "completeness": completeness,
                }
            except Exception as e:
                logger.error(f"Error in fact finding: {e}", exc_info=True)
                return {
                    "response": "I need a bit more information about your financial situation. Could you tell me about your income?",
                    "phase": "fact_finding",
                    "completeness": completeness,
                }
        
        # Phase 3: Goal Presentation - Present goals for selection
        elif len(goals) > 0 and not any(g.get("selected_for_deep_dive") for g in goals):
            # Phase 3: Goal Presentation
            logger.info("Phase 3: Goal Presentation")
            goals_list = "\n".join([
                f"{i+1}. {g['description']} "
                f"(Timeline: {g.get('timeline_years', 'N/A')} years, "
                f"Amount: ${g.get('amount', 0):,.0f})"
                for i, g in enumerate(goals)
            ])
            
            response = f"""Great! I've discovered all your financial goals:

{goals_list}

Which goal would you like to explore in detail? Just tell me the number or describe the goal."""
            
            return {
                "response": response,
                "phase": "goal_selection",
                "goals": goals,
            }
        
        else:
            # Phase 4: Deep Dive (to be implemented with analysis agents)
            logger.info("Phase 4: Deep Dive Analysis")
            # For now, simple response
            return {
                "response": "I'm ready to provide detailed analysis for your selected goal. This feature is being enhanced.",
                "phase": "deep_dive",
            }


"""
Agents module for Vecta.

Agents:
1. StateResolverAgent - Extract facts from user input
2. GoalExplorationAgent - Socratic deep-dive into goal motivations
3. ConversationAgent - Unified brain (intent, goals, questions, flow)
4. GoalInferenceAgent - Infer goals from completed node data
5. ScenarioFramerAgent - Emotional scenario pivot for inferred goals
6. VisualizationAgent - Generate charts and calculations

Compliance rules are embedded directly in each response-generating agent's
system prompt (conversation, goal_exploration, scenario_framer) instead of
running a separate ComplianceAgent LLM call.
"""

from agents.conversation_agent import ConversationAgent, ConversationResponse, GoalCandidate
from agents.goal_exploration_agent import GoalExplorationAgent, GoalExplorationResponse
from agents.scenario_framer_agent import ScenarioFramerAgent, ScenarioFramerResponse
from agents.state_resolver_agent import StateResolverAgent, StateResolverResponse

__all__ = [
    # Main agents
    "StateResolverAgent",
    "GoalExplorationAgent",
    "ConversationAgent",
    "ScenarioFramerAgent",
    # Response types
    "StateResolverResponse",
    "GoalExplorationResponse",
    "ConversationResponse",
    "ScenarioFramerResponse",
    "GoalCandidate",
]

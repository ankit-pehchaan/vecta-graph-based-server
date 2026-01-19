"""
Agents module for Vecta - 5 Agent Architecture.

Agents:
1. StateResolverAgent - Extract facts from user input
2. ConversationAgent - Unified brain (intent, goals, questions, flow)
3. ScenarioFramerAgent - Emotional scenario pivot for inferred goals
4. VisualizationAgent - Generate charts and calculations
5. ComplianceAgent - Filter all outputs for regulatory compliance
"""

from agents.compliance_agent import ComplianceAgent, ComplianceResponse
from agents.conversation_agent import ConversationAgent, ConversationResponse, GoalCandidate
from agents.scenario_framer_agent import ScenarioFramerAgent, ScenarioFramerResponse
from agents.state_resolver_agent import StateResolverAgent, StateResolverResponse
from agents.visualization_agent import VisualizationAgent

__all__ = [
    # Main agents
    "StateResolverAgent",
    "ConversationAgent",
    "ScenarioFramerAgent",
    "VisualizationAgent",
    "ComplianceAgent",
    # Response types
    "StateResolverResponse",
    "ConversationResponse",
    "ScenarioFramerResponse",
    "ComplianceResponse",
    "GoalCandidate",
]

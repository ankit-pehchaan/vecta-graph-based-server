"""
Agents module for Vecta v2.

Agents:
1. VectaAgent - Unified conversational agent (single voice, phase-aware)
2. FactExtractor - Parallel fact extraction from user messages
3. GoalInferenceAgent - Infer goals from completed node data
4. ScenarioFramerAgent - Emotional scenario pivot for inferred goals

Compliance rules are embedded directly in VectaAgent and ScenarioFramerAgent
system prompts instead of running a separate ComplianceAgent.
"""

from agents.vecta_agent import VectaAgent, VectaResponse, GoalCandidate
from agents.fact_extractor import FactExtractor, FactExtractorResponse
from agents.goal_inference_agent import GoalInferenceAgent, GoalInferenceResponse
from agents.scenario_framer_agent import ScenarioFramerAgent, ScenarioFramerResponse

__all__ = [
    # Primary agents
    "VectaAgent",
    "FactExtractor",
    "GoalInferenceAgent",
    "ScenarioFramerAgent",
    # Response types
    "VectaResponse",
    "FactExtractorResponse",
    "GoalInferenceResponse",
    "ScenarioFramerResponse",
    "GoalCandidate",
]

"""
CalculationAgent - Performs financial calculations using graph data.

This agent uses read-only tools to access graph data and performs
financial calculations like net profit, net worth, debt-to-income ratio, etc.
"""

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config
from memory.graph_memory import GraphMemory
from agents.tools.calculation_engine_tool import CalculationEngineTool


class GraphDataTool:
    """Read-only tool for accessing graph data.
    
    Agno automatically detects methods in this class and makes them available as tools.
    """
    
    def __init__(self, graph_memory: GraphMemory):
        """Initialize tool with graph memory."""
        self.graph_memory = graph_memory
    
    def get_node_data(self, node_name: str) -> dict[str, Any]:
        """Get data for a specific node from graph."""
        return self.graph_memory.get_node_data(node_name) or {}
    
    def has_node(self, node_name: str) -> bool:
        """Check if node exists in graph."""
        return node_name in self.graph_memory.node_snapshots
    
    def get_nodes_data(self, node_names: list[str]) -> dict[str, dict[str, Any]]:
        """Get data for multiple nodes."""
        return {
            name: self.graph_memory.get_node_data(name) or {}
            for name in node_names
        }

    def get_numeric_value(self, node_name: str, field: str, default: float = 0.0) -> float:
        """
        Fetch a numeric field from a node snapshot, coercing None/empty to 0.

        This is intentionally simple and deterministic: it only handles direct fields.
        """
        data = self.graph_memory.get_node_data(node_name) or {}
        val = data.get(field)
        if val in (None, "", []):
            return float(default)
        try:
            return float(val)
        except Exception:
            return float(default)


class CalculationItem(BaseModel):
    """One calculation (deterministic tool-backed or agent fallback)."""

    calculation_type: str = Field(description="Calculator key (engine) or 'custom'")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Inputs used for the calculation")
    result: dict[str, Any] = Field(default_factory=dict, description="Calculation results")
    can_calculate: bool = Field(default=False, description="Whether calculation succeeded")
    missing_data: list[str] = Field(default_factory=list, description="Missing required fields (if any)")
    data_used: list[str] = Field(default_factory=list, description="Which nodes/fields were used")
    deterministic: bool = Field(default=True, description="True if produced via calculation_engine tool")
    formula_summary: str | None = Field(default=None, description="Short formula/approach summary")
    defaulted_fields: list[str] = Field(default_factory=list, description="Which input paths were defaulted to 0")


class CalculationResponse(BaseModel):
    """Structured response from CalculationAgent (supports multiple calcs)."""

    calculations: list[CalculationItem] = Field(default_factory=list, description="One or more calculations")
    summary: str | None = Field(default=None, description="Short summary across calculations")


class CalculationAgent:
    """
    Agent for performing financial calculations.
    
    This agent:
    - Uses tools to access graph data (read-only)
    - Performs financial calculations
    - Returns results or missing data requirements
    - Never requests data collection (orchestrator handles that)
    """
    
    def __init__(self, model_id: str | None = None, graph_memory: GraphMemory | None = None):
        """Initialize CalculationAgent with model and graph memory."""
        self.model_id = model_id or Config.MODEL_ID
        self.graph_memory = graph_memory
        self._agent: Agent | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "calculation_agent_prompt.txt"
        return prompt_path.read_text()
    
    def get_agent(self) -> Agent:
        """Get or create agent (reuse for performance)."""
        if self._agent and self.graph_memory:
            return self._agent
        
        if not self.graph_memory:
            raise ValueError("GraphMemory must be provided to CalculationAgent")
        
        prompt_template = self._load_prompt()
        
        self._agent = Agent(
            model=OpenAIChat(id=self.model_id),
            tools=[GraphDataTool(self.graph_memory), CalculationEngineTool()],
            instructions=prompt_template,
            output_schema=CalculationResponse,
            markdown=False,
            debug_mode=False,
            use_json_mode=True
        )
        
        return self._agent
    
    def calculate(self, request: str) -> CalculationResponse:
        """
        Perform calculation using graph data.
        
        Args:
            request: User's calculation request
        
        Returns:
            CalculationResponse with results or missing data info
        """
        agent = self.get_agent()
        return agent.run(request).content
    
    def update_graph_memory(self, graph_memory: GraphMemory) -> None:
        """Update graph memory and recreate agent with new tools."""
        self.graph_memory = graph_memory
        self._agent = None  # Force recreation with new graph memory


"""
VisualizationAgent - Performs calculations and generates visualizations.

This agent:
- Uses GraphDataTool to access financial data
- Uses PythonTools to execute accurate financial calculations
- Generates visualization specifications
- Returns both calculation results AND chart specs
"""

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from pydantic import BaseModel, Field

from config import Config
from memory.graph_memory import GraphMemory


class GraphDataTool:
    """Read-only tool for accessing graph data."""
    
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
    
    def get_all_collected_data(self) -> dict[str, dict[str, Any]]:
        """Get all collected data from the graph memory."""
        return self.graph_memory.get_all_nodes_data()


class VisualizationResponse(BaseModel):
    """Structured response from VisualizationAgent."""
    # Calculation fields
    calculation_type: str = Field(description="Type of calculation performed")
    result: dict[str, Any] = Field(default_factory=dict, description="Calculation results")
    can_calculate: bool = Field(description="Whether calculation is possible")
    missing_data: list[str] = Field(default_factory=list, description="Required nodes/data not available")
    message: str = Field(description="Human-readable explanation of calculation and result")
    data_used: list[str] = Field(default_factory=list, description="Which nodes/sources were used")
    
    # Visualization fields (only if calculation succeeded)
    chart_type: str = Field(default="", description="Type of chart: bar, line, pie, donut, area, etc.")
    chart_data: dict[str, Any] = Field(default_factory=dict, description="Chart.js compatible data structure")
    chart_title: str = Field(default="", description="Chart title")
    chart_description: str = Field(default="", description="Chart description")
    chart_config: dict[str, Any] = Field(default_factory=dict, description="Chart configuration options")


class VisualizationAgent:
    """
    Agent for performing calculations and generating visualizations.
    
    This agent:
    - Uses tools to access graph data
    - Performs financial calculations
    - Generates appropriate visualizations
    - Returns both calculation results and chart specs in one response
    """
    
    def __init__(self, model_id: str | None = None, graph_memory: GraphMemory | None = None):
        """Initialize VisualizationAgent with model and graph memory."""
        self.model_id = model_id or Config.MODEL_ID
        self.graph_memory = graph_memory
        self._agent: Agent | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "visualization_agent_prompt.txt"
        return prompt_path.read_text()
    
    def get_agent(self) -> Agent:
        """Get or create agent (reuse for performance)."""
        if self._agent and self.graph_memory:
            return self._agent
        
        if not self.graph_memory:
            raise ValueError("GraphMemory must be provided to VisualizationAgent")
        
        prompt_template = self._load_prompt()
        
        # Use both GraphDataTool for data access and PythonTools for accurate calculations
        self._agent = Agent(
            model=OpenAIChat(id=self.model_id),
            tools=[GraphDataTool(self.graph_memory), PythonTools()],
            instructions=prompt_template,
            output_schema=VisualizationResponse,
            markdown=False,
            debug_mode=True,
            use_json_mode=True
        )
        
        return self._agent
    
    def calculate_and_visualize(self, request: str) -> VisualizationResponse:
        """
        Perform calculation and generate visualization in one step.
        
        Args:
            request: User's calculation/visualization request
        
        Returns:
            VisualizationResponse with both calculation results and chart specification
        """
        agent = self.get_agent()
        return agent.run(request).content
    
    def update_graph_memory(self, graph_memory: GraphMemory) -> None:
        """Update graph memory and recreate agent with new tools."""
        self.graph_memory = graph_memory
        self._agent = None  # Force recreation with new graph memory


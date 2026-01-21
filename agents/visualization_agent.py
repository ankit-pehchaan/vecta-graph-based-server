"""
VisualizationAgent - Extracts calculation intent and inputs for visualization.

This agent:
- Uses GraphDataTool to access financial data
- Extracts calculation type and required inputs
- Does NOT perform calculations (handled by calculation_engine)
"""

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
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


class VisualizationRequest(BaseModel):
    """Structured request from VisualizationAgent."""
    calculation_type: str | None = Field(default=None, description="Type of calculation requested")
    inputs: dict[str, Any] | None = Field(default=None, description="Inputs required for calculation")
    can_calculate: bool | None = Field(default=None, description="Whether calculation is possible with current data")
    missing_data: list[str] | None = Field(default=None, description="Required fields not available")
    message: str | None = Field(default=None, description="Human-readable explanation of what will be calculated")
    data_used: list[str] | None = Field(default=None, description="Which nodes/sources were used")


class ChartSpec(BaseModel):
    chart_type: str | None = Field(default=None, description="Type of chart: bar, line, pie, donut")
    data: dict[str, Any] | None = Field(default=None, description="Chart.js compatible data")
    title: str | None = Field(default=None, description="Chart title")
    description: str | None = Field(default=None, description="Chart description")
    config: dict[str, Any] | None = Field(default=None, description="Chart configuration options")


class VisualizationCharts(BaseModel):
    calculation_type: str | None = Field(default=None, description="Type of calculation")
    charts: list[ChartSpec] | None = Field(default=None, description="Charts for visualization")
    message: str | None = Field(default=None, description="Short explanation of what charts show")


class VisualizationAgent:
    """
    Agent for extracting calculation intent and inputs for visualization.
    """
    
    def __init__(self, model_id: str | None = None, graph_memory: GraphMemory | None = None):
        """Initialize VisualizationAgent with model and graph memory."""
        self.model_id = model_id or Config.MODEL_ID
        self.graph_memory = graph_memory
        self._agent: Agent | None = None
        self._renderer_agent: Agent | None = None
        self._renderer_prompt_template: str | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "calculation_agent_prompt.txt"
        return prompt_path.read_text()

    def _load_renderer_prompt(self) -> str:
        """Load renderer prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "visualization_agent_prompt.txt"
        return prompt_path.read_text()
    
    def get_agent(self) -> Agent:
        """Get or create agent (reuse for performance)."""
        if self._agent and self.graph_memory:
            return self._agent
        
        if not self.graph_memory:
            raise ValueError("GraphMemory must be provided to VisualizationAgent")
        
        prompt_template = self._load_prompt()
        
        # Use GraphDataTool for data access only (calculations handled by services)
        self._agent = Agent(
            model=OpenAIChat(id=self.model_id),
            tools=[GraphDataTool(self.graph_memory)],
            instructions=prompt_template,
            output_schema=VisualizationRequest,
            markdown=False,
            debug_mode=False,
            use_json_mode=True
        )
        
        return self._agent

    def get_renderer(self) -> Agent:
        """Get or create renderer agent (reuse for performance)."""
        if self._renderer_agent:
            return self._renderer_agent

        prompt_template = self._renderer_prompt_template or self._load_renderer_prompt()
        self._renderer_agent = Agent(
            model=OpenAIChat(id=self.model_id),
            instructions=prompt_template,
            output_schema=VisualizationCharts,
            markdown=False,
            debug_mode=False,
            use_json_mode=True,
        )
        return self._renderer_agent
    
    def calculate_and_visualize(self, request: str) -> VisualizationRequest:
        """
        Perform calculation and generate visualization in one step.
        
        Args:
            request: User's calculation/visualization request
        
        Returns:
            VisualizationRequest with calculation type and inputs
        """
        agent = self.get_agent()
        return agent.run(request).content

    def generate_charts(
        self,
        calculation_type: str,
        inputs: dict[str, Any],
        result: dict[str, Any],
        data_used: list[str] | None = None,
    ) -> VisualizationCharts:
        """Generate charts based on calculation outputs."""
        payload = {
            "calculation_type": calculation_type,
            "inputs": inputs,
            "result": result,
            "data_used": data_used or [],
        }
        renderer = self.get_renderer()
        return renderer.run(f"CALCULATION_JSON: {payload}").content
    
    def update_graph_memory(self, graph_memory: GraphMemory) -> None:
        """Update graph memory and recreate agent with new tools."""
        self.graph_memory = graph_memory
        self._agent = None  # Force recreation with new graph memory


"""
VisualizationAgent - Extracts calculation intent and inputs for visualization.

This agent:
- Uses GraphDataTool to access financial data
- Renders charts from already-computed calculation inputs/results
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
    Agent for rendering charts from calculation outputs.

    Note: calculation selection + numeric extraction is handled by CalculationAgent.
    """
    
    def __init__(self, model_id: str | None = None, graph_memory: GraphMemory | None = None):
        """Initialize VisualizationAgent with model and graph memory."""
        self.model_id = model_id or Config.MODEL_ID
        self.graph_memory = graph_memory
        self._renderer_agent: Agent | None = None
        self._renderer_prompt_template: str | None = None
    
    def _load_renderer_prompt(self) -> str:
        """Load renderer prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "visualization_agent_prompt.txt"
        return prompt_path.read_text()
    
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
        # Renderer does not depend on graph memory (only on provided payload)


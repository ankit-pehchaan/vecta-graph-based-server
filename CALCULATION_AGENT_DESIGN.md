# CalculationAgent Design Analysis

## The Question

Should CalculationAgent:
1. **Be a pure agent** (like DecisionAgent) that receives graph snapshot and returns missing_data?
2. **Use tools** to autonomously check/request data from graph?

## Analysis Against Agno Patterns

### Current Codebase Pattern

**InfoAgent & DecisionAgent:**
- Both are **pure agents** with structured output
- InfoAgent: Has conversation history, asks questions
- DecisionAgent: No history, pure reasoning
- Both follow: Input → Agent → Structured Output

**Key Principle from .cursorrules:**
> "Single Agent (90% of use cases): One clear task or domain, Can be solved with tools + instructions"

### Option 1: Pure Agent (Original Plan)

```python
# CalculationAgent receives full graph snapshot
calculation_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Calculate financial metrics...",
    output_schema=CalculationResponse,
)

# Orchestrator passes graph data
result = calculation_agent.run(
    f"Calculate net profit. Graph data: {graph_snapshot}"
).content

# If missing data, orchestrator handles collection
if not result.can_calculate:
    # Orchestrator invokes InfoAgent
    # Re-invokes CalculationAgent
```

**Pros:**
- ✅ Follows existing pattern (DecisionAgent style)
- ✅ Agent is deterministic and pure
- ✅ Clear separation: agent calculates, orchestrator collects
- ✅ Easy to test (just pass data)

**Cons:**
- ❌ Agent doesn't know what data it needs until it tries
- ❌ Large graph snapshots in prompt (token waste)
- ❌ Less flexible for new calculation types
- ❌ Agent can't autonomously check data availability

### Option 2: Agent with Tools (Recommended)

```python
# GraphDataTool provides read-only access
class GraphDataTool:
    def get_node_data(self, node_name: str) -> dict:
        """Get data for specific node."""
    
    def has_node(self, node_name: str) -> bool:
        """Check if node exists."""

# CalculationAgent uses tools
calculation_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GraphDataTool(graph_memory)],
    instructions="Use tools to access graph data, then calculate...",
    output_schema=CalculationResponse,
)

# Agent autonomously checks what it needs
result = calculation_agent.run("Calculate net profit").content
```

**Pros:**
- ✅ Follows Agno pattern: "tools for capabilities"
- ✅ Agent knows what data it needs (uses tools to check)
- ✅ Efficient: only accesses needed nodes
- ✅ Scalable: can add more calculation tools
- ✅ Agent is still deterministic (tools are read-only)
- ✅ Better for complex calculations requiring multiple data sources

**Cons:**
- ⚠️ Slightly more complex (tool implementation)
- ⚠️ Agent needs to "learn" to use tools (but LLMs are good at this)

### Option 3: Hybrid (Best of Both)

**CalculationAgent with Read-Only Tools:**
- Tools for **reading** graph data (deterministic, auditable)
- **No tools for requesting data** (that's orchestrator's job)
- Agent focuses on calculation logic
- Orchestrator handles missing data collection

```python
class GraphDataTool:
    """Read-only tool - never modifies graph."""
    def get_node_data(self, node_name: str) -> dict:
        # Read from GraphMemory
        return self.graph_memory.get_node_data(node_name)
    
    def has_node(self, node_name: str) -> bool:
        return node_name in self.graph_memory.node_snapshots

# Agent uses tools to read, returns missing_data if needed
# Orchestrator handles collection loop
```

## Recommendation: **Option 2/3 (Agent with Read-Only Tools)**

### Why This Is Better

1. **Aligns with Agno Philosophy:**
   - Tools are for capabilities (data access is a capability)
   - Agent focuses on reasoning (calculation logic)
   - Clear separation of concerns

2. **Scalability:**
   - Easy to add new calculation types
   - Agent can discover what data it needs
   - No need to pre-define all calculation requirements

3. **Efficiency:**
   - Only accesses needed nodes (not full graph snapshot)
   - Reduces token usage
   - Faster for large graphs

4. **Maintainability:**
   - Calculation logic stays in agent
   - Data access logic in tools
   - Orchestrator handles flow control

5. **Auditability:**
   - Tools are deterministic (read-only)
   - Can log which nodes were accessed
   - Clear separation: agent never modifies graph

### The Back-and-Forth Flow

**Question:** How will the back-and-forth work?

**Answer:** Orchestrator handles the loop, not the agent.

```
User: "Calculate net profit"
  ↓
IntentRouterAgent: intent = "calculation"
  ↓
Orchestrator.handle_calculation():
  ↓
CalculationAgent (with tools):
  - Uses tools to check for Income, Expenses nodes
  - If missing → returns missing_data=["Income", "Expenses"]
  - If available → calculates and returns result
  ↓
Orchestrator checks result.can_calculate:
  ↓
If False:
  - Orchestrator invokes InfoAgent for missing nodes
  - User provides data
  - GraphMemory updated
  - Orchestrator re-invokes CalculationAgent
  - Loop until success
  ↓
If True:
  - Return result to user
  - Ask: "Continue planning or explore something else?"
```

**Key Point:** CalculationAgent **never** requests data collection. It only:
1. Uses tools to **read** existing data
2. Returns `missing_data` if insufficient
3. Orchestrator handles the collection loop

### Is This Scalable?

**Yes, because:**

1. **Agent Reuse:**
   - CalculationAgent is created once per session (not per request)
   - Follows .cursorrules: "NEVER create agents in loops"
   - Tools are lightweight (just read operations)

2. **Modular Design:**
   - New calculation types = update agent instructions
   - New data sources = add tool methods
   - No changes to orchestrator flow

3. **Performance:**
   - Tools are fast (in-memory reads)
   - Agent only processes when needed
   - No unnecessary graph snapshots

4. **Extensibility:**
   - Can add CalculationTools (e.g., `calculate_net_worth()`)
   - Can add ValidationTools (e.g., `validate_data_completeness()`)
   - Agent orchestrates tool usage

## Implementation Example

```python
# agents/calculation_agent.py
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import Tool
from pydantic import BaseModel, Field
from typing import Any

class GraphDataTool(Tool):
    """Read-only tool for accessing graph data."""
    
    def __init__(self, graph_memory):
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

class CalculationResponse(BaseModel):
    calculation_type: str
    result: dict[str, Any]
    missing_data: list[str]
    can_calculate: bool
    message: str
    data_used: list[str] = Field(default_factory=list)

class CalculationAgent:
    def __init__(self, model_id: str | None = None, graph_memory=None):
        self.model_id = model_id or Config.MODEL_ID
        self.graph_memory = graph_memory
        self._agent = None
    
    def get_agent(self) -> Agent:
        """Get or create agent (reuse for performance)."""
        if self._agent:
            return self._agent
        
        self._agent = Agent(
            model=OpenAIChat(id=self.model_id),
            tools=[GraphDataTool(self.graph_memory)],
            instructions=self._load_prompt(),
            output_schema=CalculationResponse,
            markdown=False,
            debug_mode=False,
        )
        return self._agent
    
    def calculate(self, request: str) -> CalculationResponse:
        """Perform calculation using graph data."""
        agent = self.get_agent()
        return agent.run(request).content
```

## Final Answer

**Use Agent with Read-Only Tools** because:

1. ✅ Aligns with Agno best practices
2. ✅ Scalable and maintainable
3. ✅ Efficient (only accesses needed data)
4. ✅ Clear separation: agent calculates, orchestrator collects
5. ✅ Follows existing pattern (tools for capabilities)

**The back-and-forth is handled by Orchestrator, not the agent.** This keeps the agent pure (deterministic, auditable) while allowing flexible data access.


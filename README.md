# Financial Life Knowledge Graph - Information Gathering System

A production-grade system for collecting financial information using ephemeral agents and graph-based memory.

## Architecture

### Core Components

1. **Nodes** (`nodes/`) - Pydantic models representing financial life aspects
2. **Schema** (`nodes/schema.py`) - Node schema contract for agent consumption
3. **GraphMemory** (`memory/`) - Persistent storage for node snapshots and edges
4. **InfoAgent** (`agents/info_agent.py`) - Ephemeral agent for collecting node data
5. **DecisionAgent** (`agents/decision_agent.py`) - Ephemeral agent for deciding next node
6. **Orchestrator** (`orchestrator/`) - Main controller for the information gathering flow
7. **Prompts** (`prompts/`) - Prompt templates for agents

### System Flow

```
1. User provides initial goal
2. System starts with PersonalInfo node
3. InfoAgent is instantiated for that node
4. InfoAgent asks questions one by one
5. User answers or skips
6. InfoAgent returns complete:true with structured data
7. Code calls DecisionAgent
8. DecisionAgent returns next_node, reason, visited_all
9. Code builds edge between nodes
10. If visited_all is false → repeat with new InfoAgent
11. If visited_all is true → end flow
```

### Key Design Principles

- **Stateless Agents**: InfoAgent and DecisionAgent are ephemeral and disposable
- **Stateful Graph**: GraphMemory persists all collected data
- **Node Isolation**: InfoAgent only sees its node schema and conversation
- **Decision Isolation**: DecisionAgent only sees structured JSON data
- **Deterministic Orchestration**: Code controls the flow, agents provide reasoning

## Usage

### Basic Example

```python
from orchestrator import Orchestrator

# Initialize with user goal
orchestrator = Orchestrator(
    user_goal="I want to buy a car",
    model_id="gpt-4o"
)

# Run the information gathering flow
graph_memory = orchestrator.run()

# Get summary
summary = orchestrator.get_graph_summary()
print(summary)
```

### Node Schema

Node schemas are generated using Pydantic's built-in `model_json_schema()` method, which provides:
- Field definitions with types and descriptions
- Required/optional field information
- Enum values where applicable

### GraphMemory

Stores:
- `node_snapshots`: Collected node data
- `edges`: Relationships between nodes
- `traversal_order`: Order of node collection

Methods:
- `add_node_snapshot(node_name, data)`
- `add_edge(from_node, to_node, reason)`
- `get_all_nodes_data()`
- `get_last_node()`

## Folder Structure

```
.
├── nodes/              # Node definitions (Pydantic models)
│   ├── base.py         # BaseNode, Edge, BaseGraph
│   └── ...             # Specific node types
├── agents/             # Ephemeral agents
│   ├── info_agent.py   # Data collection agent
│   └── decision_agent.py # Node selection agent
├── memory/             # Persistent storage
│   └── graph_memory.py # GraphMemory class
├── orchestrator/       # Main controller
│   └── main.py        # Orchestrator class
└── prompts/            # Prompt templates
    ├── info_agent_prompt.txt
    └── decision_agent_prompt.txt
```

## Agent Behavior

### InfoAgent

- Asks ONE question at a time
- Tracks conversation history
- Never repeats questions
- Allows skip (marks as null)
- Returns `complete: true` when done
- Only sees its node schema and conversation

### DecisionAgent

- Receives user goal
- Receives all collected node data
- Receives previous node name
- Returns next_node, reason, visited_all
- Never sees raw conversation
- Only sees structured JSON data

## Production Considerations

- Agents are stateless and disposable (no memory leakage)
- Clean separation of concerns
- Easy debugging and replay
- Easy audit trail
- Enterprise-safe architecture


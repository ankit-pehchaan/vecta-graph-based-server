# Architecture Documentation

## System Overview

This is a **Stateless Agent Invocation with Stateful Graph Orchestration** system for collecting financial information.

### Key Characteristics

- **Ephemeral Agents**: InfoAgent, DecisionAgent, and StateResolverAgent are instantiated per task
- **Persistent Graph**: GraphMemory stores all collected data, relationships, and history
- **Global State Resolution**: StateResolverAgent intercepts all user input for cross-node extraction
- **Temporal Tracking**: Field-level history with conflict detection and resolution
- **Deterministic Control**: Orchestrator (code) controls the flow
- **Agentic Reasoning**: LLMs provide reasoning within controlled boundaries

## Component Details

### 1. Node Schema

Node schemas are generated using Pydantic's built-in `model_json_schema()` method.

**Usage:**
```python
from nodes.personal import Personal

schema = Personal.model_json_schema()  # Returns full JSON schema
```

### 2. GraphMemory (`memory/graph_memory.py`)

Persistent storage for:
- Node snapshots (node_name -> data)
- Edges (from_node -> to_node with reason)
- Traversal order
- Field history (temporal tracking with timestamps)
- Conflicts (value change detection)

**Core Methods:**
- `add_node_snapshot(node_name, data)` - Store/update node data
- `add_edge(from_node, to_node, reason)` - Record relationship
- `get_all_nodes_data()` - Get all collected data
- `get_last_node()` - Get last collected node name

**New History & Conflict Methods:**
- `apply_updates(updates)` - Apply structured updates from StateResolverAgent
- `get_field_history(node_name, field_name)` - Get history for specific field
- `mark_conflict(node_name, field_name, old_value, new_value)` - Mark conflict
- `get_node_with_history(node_name)` - Get node data with history metadata
- `has_conflicts(node_name)` - Check for conflicts

### 3. InfoAgent (`agents/info_agent.py`)

**Purpose**: Collect data for ONE node

**Behavior**:
- Asks ONE question at a time
- Tracks conversation history
- Never repeats questions
- Allows skip (marks as null)
- Returns `complete: true` when done

**Input**:
- Node name
- Node schema
- Current node data
- Conversation history

**Output**:
```json
{
  "complete": false,
  "field": "age",
  "question": "What is your age?"
}
```
or
```json
{
  "complete": true,
  "node_data": {...}
}
```

**Isolation**: Only sees its node schema and conversation

### 4. DecisionAgent (`agents/decision_agent.py`)

**Purpose**: Decide next node to collect

**Behavior**:
- Reasons about next best node
- Returns next_node, reason, visited_all
- Never sees raw conversation

**Input**:
- User goal
- All collected node data (structured JSON)
- Previous node name

**Output**:
```json
{
  "next_node": "Financial",
  "reason": "Income and expenses are needed",
  "visited_all": false
}
```
or
```json
{
  "visited_all": true,
  "reason": "All necessary data collected"
}
```

**Isolation**: Only sees structured JSON, never raw conversation

### 5. StateResolverAgent (`agents/state_resolver_agent.py`)

**Purpose**: Extract ALL facts from user input and route to correct nodes

**Behavior**:
- Intercepts EVERY user reply before InfoAgent
- Extracts facts across ALL nodes (cross-node extraction)
- Maps facts to correct node schemas
- Detects conflicts with existing graph data
- Tracks temporal context (past, present, future)
- Triggers priority shifts for major changes
- Preserves history and explainability

**Input**:
- User reply (raw message)
- Current node and question
- Full graph snapshot
- All node schemas

**Output**:
```json
{
  "updates": [
    {
      "node_name": "Income",
      "field_name": "annual_amount",
      "value": 80000,
      "confidence": 0.9,
      "temporal_context": "present",
      "is_correction": false,
      "reasoning": "User stated income"
    }
  ],
  "answer_consumed_for_current_node": true,
  "priority_shift": null,
  "conflicts_detected": false,
  "reasoning": "Extracted income data"
}
```

**Key Features**:
- Cross-node data capture (user can mention any data anytime)
- Conflict detection (user contradicts previous data)
- Priority shift triggering (job loss → emergency nodes)
- Temporal reasoning (past: "lost job", future: "will get promotion")
- History preservation (never lose data, only evolve it)

### 6. Orchestrator (`orchestrator/main.py`)

**Purpose**: Main controller for the flow

**Flow**:
```python
current_node = "Personal"
while True:
    node_data = run_info_agent(current_node)
    graph.add_node_snapshot(current_node, node_data)
    decision = run_decision_agent(graph)
    if decision.visited_all:
        break
    graph.add_edge(current_node, decision.next_node, decision.reason)
    current_node = decision.next_node
```

**Responsibilities**:
- Auto-discovers nodes from `nodes.__all__`
- Instantiates ephemeral agents
- Manages GraphMemory
- Controls node traversal
- Builds edges

**Node Registry**: Auto-generated from `nodes.__all__` - no manual registration needed!

## Data Flow

### New Flow with StateResolverAgent

```
User Reply
    ↓
StateResolverAgent (intercepts ALL input)
    ├─ Extract ALL facts (even cross-node)
    ├─ Map to correct node schemas
    ├─ Detect conflicts
    └─ Generate updates[]
    ↓
GraphMemory.apply_updates(updates)
    ├─ Update node snapshots
    ├─ Record field history
    └─ Mark conflicts
    ↓
Check priority_shift?
    ├─ Yes → DecisionAgent (immediate replan)
    └─ No → Continue
    ↓
InfoAgent (current node)
    ↓
Complete? → DecisionAgent → Next Node
```

### Original Flow (Enhanced)

```
User Goal
    ↓
Orchestrator
    ↓
InfoAgent (Personal) → Questions → User → Answers
    ↓
StateResolverAgent → Extract facts → Updates
    ↓
GraphMemory.apply_updates(updates)
    ↓
Node Complete? → DecisionAgent → next_node, reason
    ↓
If visited_all: END
    ↓
Else: GraphMemory.add_edge("Personal", "Financial", reason)
    ↓
InfoAgent (Financial) → ...
```

## Prompt Templates

### InfoAgent Prompt (`prompts/info_agent_prompt.txt`)

Key instructions:
- Collect information for ONE node only
- Ask one question at a time
- Never repeat questions
- Allow skip
- Return complete:true when done

### DecisionAgent Prompt (`prompts/decision_agent_prompt.txt`)

Key instructions:
- Decide next node based on goal and data
- Return next_node, reason, visited_all
- Do NOT ask questions
- Do NOT collect information

### StateResolverAgent Prompt (`prompts/state_resolver_prompt.txt`)

Key instructions:
- Extract ALL facts from user message
- Map facts to correct nodes (cross-node capable)
- Detect conflicts with existing graph state
- Determine if current question was answered
- Identify priority shifts (major financial changes)
- Track temporal context (past, present, future)
- Provide reasoning for all decisions

## Node Registry

The Orchestrator maintains a registry of available nodes:

- Personal
- UserProfile
- Family, Marriage, Parents
- Financial, Income, Expenses, Savings
- Assets, Liabilities, Loan
- Goals, Insurance, Investments, Retirement

## Error Handling

- InfoAgent fallback: If LLM fails, asks for first missing field
- DecisionAgent fallback: Defaults to "Financial" node
- Schema validation: Pydantic models ensure data structure

## Logging & Audit

The system logs:
- Each InfoAgent run
- Each DecisionAgent run
- Node traversal order
- Edge reasons
- All collected data

## Production Considerations

### Advantages

1. **No Memory Leakage**: Agents are ephemeral
2. **Clean Separation**: InfoAgent vs DecisionAgent vs Orchestrator
3. **Easy Debugging**: Deterministic flow, clear boundaries
4. **Easy Replay**: GraphMemory can be serialized/deserialized
5. **Easy Audit**: Complete trail of questions, answers, decisions
6. **Enterprise-Safe**: No agent confusion, no orchestration leakage

### Scalability

- Agents can be reused (not recreated in loops)
- GraphMemory can be persisted to database
- Node registry can be extended dynamically
- Prompt templates can be versioned

## State Resolution & Conflict Handling

### Field History Tracking

Each field update is tracked with:
- Value (current)
- Timestamp
- Source (user_input, calculation, etc.)
- Previous value
- Conflict resolved flag
- Reasoning

### Conflict Resolution Strategy

1. **Temporal Override**: Newer information overwrites older (history preserved)
2. **Explicit Contradiction**: User corrections ("Actually I was wrong") → immediate overwrite
3. **Priority Shift**: Major changes (job loss, bankruptcy) → trigger replanning
4. **History Preservation**: Never lose data, only evolve it

### Example Scenarios

**Scenario 1: Cross-Node Data**
- Current node: Personal (asking age)
- User: "I earn 80,000 dollars"
- StateResolver: Extracts to Income node, continues Personal questions

**Scenario 2: Contradiction**
- Day 1: Income = 80,000
- Day 2: User: "I lost my job, no income"
- StateResolver: Updates Income = 0, preserves history, triggers priority shift

**Scenario 3: Future Data**
- User: "I will get a promotion next month"
- StateResolver: Marks temporal_context="future", doesn't overwrite current income

## Extension Points

1. **New Nodes**: Just add to `nodes/__init__.py` - auto-discovered!
2. **Custom Prompts**: Update prompt templates
3. **Persistence**: Extend GraphMemory with database backend
4. **Validation**: Use Pydantic validators in node classes
5. **UI Integration**: Replace input() with API calls
6. **History Analysis**: Query field_history for temporal insights
7. **Conflict Review**: Audit conflicts for data quality


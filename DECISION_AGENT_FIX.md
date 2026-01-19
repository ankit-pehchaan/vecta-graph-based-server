# DecisionAgent Fix - Valid Node Selection

## Problem

The DecisionAgent was choosing invalid node names (e.g., "Contact") that don't exist in the system, causing errors:
```
Error: Unknown node: Contact
```

## Root Cause

1. The DecisionAgent prompt didn't include the list of available nodes
2. No validation was performed to ensure the chosen node exists
3. No conditional logic guidance for when to choose which node

## Solution

### 1. Updated DecisionAgent to Receive Available Nodes

**`agents/decision_agent.py`:**
```python
def decide_next_node(
    self,
    user_goal: str,
    graph_memory: GraphMemory,
    previous_node: str,
    available_nodes: list[str] | None = None,  # New parameter
) -> DecisionResponse:
    # Filter out already collected nodes
    collected_nodes = list(graph_memory.node_snapshots.keys())
    remaining_nodes = [n for n in available_nodes if n not in collected_nodes]
    
    # Pass to prompt
    nodes_list = "\n".join([f"- {node}" for node in remaining_nodes])
```

### 2. Updated Prompt with Available Nodes and Logic

**`prompts/decision_agent_prompt.txt`:**

Added:
- **AVAILABLE NODES** section listing valid nodes
- **CONDITIONAL LOGIC** section with smart rules:
  - If married → consider Family, Marriage
  - If has children → consider Dependents  
  - If has income → consider Financial, Income
  - If has loans → consider Liabilities
  - If has goals → consider Goals
  - If health concerns → consider Insurance
  - etc.

### 3. Added Validation in Orchestrator

**`orchestrator/main.py`:**
```python
if not decision.visited_all:
    # Validate next_node exists
    if decision.next_node not in self.NODE_REGISTRY:
        raise ValueError(
            f"Unknown node: {decision.next_node}. "
            f"Available nodes: {', '.join(self.NODE_REGISTRY.keys())}"
        )
```

## Available Nodes in System

The system has 18 valid nodes:
- Personal (starting point)
- Family, Marriage, Dependents, Parents
- Financial, Income, Expenses, Savings
- Assets
- Liabilities, Loan
- Goals
- Insurance, InsurancePolicy
- Investments
- Retirement
- UserProfile

## How It Works Now

1. **Orchestrator** passes list of available nodes to DecisionAgent
2. **DecisionAgent** filters out already collected nodes
3. **Prompt** shows only remaining nodes + conditional logic
4. **LLM** chooses from valid nodes based on collected data
5. **Orchestrator** validates the choice before proceeding

## Example Decision Flow

```
1. Start: Personal
   → Collect: age, marital_status=married, occupation, etc.

2. Decision: Based on married=true
   → Next: Marriage (collect spouse details)

3. Decision: Based on spouse_income exists
   → Next: Financial (collect household income)

4. Decision: Based on income collected
   → Next: Expenses (understand spending)

5. Decision: Based on user_goal="buy house"
   → Next: Assets (check existing property)
   → Then: Liabilities (check debts)
   → Then: Goals (formalize house goal)

6. Decision: All relevant nodes collected
   → visited_all: true
```

## Benefits

✅ No more invalid node names
✅ Intelligent conditional traversal
✅ Data-driven decision making
✅ Clear validation and error messages
✅ Reuses collected data to inform next steps


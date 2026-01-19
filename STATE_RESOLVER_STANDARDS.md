# StateResolver Conflict Classification Standards

## Problem Statement

Not all conflicts are equal. The system needs to distinguish between:
- Conflicts that require adding new nodes to traversal
- Conflicts that indicate financial emergency
- Conflicts that are just normal data updates

## Solution: Three-Category Classification System

### Category 1: TOPOLOGY CONFLICTS
**Definition**: Conflicts that require NEW NODES to be added to traversal

**When**: User contradicts data in a way that means we need to collect entirely new information

**Examples**:
- Single → Married: Need Marriage, Family, Dependents nodes
- No children → Has 2 children: Need Dependents, Insurance nodes
- No loans → Has mortgage: Need Liabilities, Loan nodes
- No health issues → Chronic illness: Need Insurance node
- Employed → Self-employed: Need Business, Assets nodes

**Rule**: If existing graph shows we SKIPPED a node type (null/no/none), and user now says they HAVE it, trigger priority_shift to add those nodes.

**Action**: 
- `is_correction=true`
- `conflicts_detected=true`
- `priority_shift=[list of nodes to add]`

---

### Category 2: SEVERITY CONFLICTS
**Definition**: Conflicts that cross critical financial thresholds

**When**: Values change dramatically enough to require emergency action

**Critical Thresholds**:
- Income/Savings → 0 (total loss): Emergency
- Income/Savings drops >50%: Warning level
- Debt increases >100%: Crisis
- Employment: Employed → Unemployed: Emergency
- Financial status: Stable → Bankrupt: Emergency

**Examples**:
- Savings: 20k → 0 (lost in game): SEVERITY CONFLICT
- Income: 80k → 0 (job loss): SEVERITY CONFLICT
- Income: 80k → 88k (10% increase): VALUE UPDATE (no shift)
- Savings: 20k → 18k (minor decrease): VALUE UPDATE (no shift)

**Rule**: If value change is <30% and doesn't reach zero, it's a normal update. If >50% drop or reaches zero, trigger priority_shift.

**Action**:
- `is_correction=true`
- `conflicts_detected=true`
- `priority_shift=["Emergency", "Insurance", "Liabilities", "Goals"]`

---

### Category 3: VALUE UPDATES
**Definition**: Simple data corrections or updates within same node

**When**: Minor changes that don't cross thresholds or add nodes

**Examples**:
- Income: 80k → 88k (10% increase)
- Savings: 20k → 18k (minor decrease)
- Age: 30 → 31
- Rent: 2000 → 2200 (10% increase)

**Rule**: Changes <30% that don't reach zero or critical status

**Action**:
- `is_correction=true`
- `conflicts_detected=true`
- `priority_shift=null` (no priority shift)

---

## Decision Tree

```
Conflict Detected
    ↓
1. Does this add a NEW NODE TYPE that wasn't needed before?
   (e.g., single→married, no kids→has kids)
    ↓ YES
    TOPOLOGY CONFLICT
    → Priority shift to add those nodes
    
    ↓ NO
    
2. Does this cross a SEVERITY THRESHOLD?
   - Value → 0 (total loss)
   - Value drops >50%
   - Status becomes critical (unemployed, bankrupt)
    ↓ YES
    SEVERITY CONFLICT
    → Priority shift to Emergency/protective nodes
    
    ↓ NO
    
3. VALUE UPDATE
   → Update data, no priority shift
```

## Real-World Examples

### Example 1: Marriage Status Change
**User**: "I am single" → Later: "Actually I am married"

**Analysis**:
- Category: TOPOLOGY CONFLICT
- Reason: Marriage node wasn't in traversal, now needs to be added
- Action: priority_shift = ["Marriage", "Family", "Dependents"]

**Why?** Because being married means we need to collect:
- Marriage node: spouse details, joint finances
- Family node: family structure
- Dependents node: potential children

---

### Example 2: Savings Lost in Game
**User**: "My savings is 20k" → Next day: "I lost it all in a game"

**Analysis**:
- Category: SEVERITY CONFLICT
- Reason: Savings dropped 100% to zero (crosses >50% threshold)
- Action: priority_shift = ["Emergency", "Goals", "Liabilities"]

**Why?** Because:
- No emergency fund now (emergency situation)
- Goals need re-evaluation (can't achieve with no savings)
- Liabilities might become problematic without buffer

---

### Example 3: Income Increase
**User**: "My income is 80k" → Later: "Actually it's 88k"

**Analysis**:
- Category: VALUE UPDATE
- Reason: Only 10% increase, no threshold crossed
- Action: priority_shift = null

**Why?** This is just a normal correction, doesn't require emergency action or new nodes.

---

## Thresholds Summary

| Metric | Minor Update | Warning | Emergency |
|--------|-------------|---------|-----------|
| Income/Savings change | <30% | 30-50% drop | >50% drop or →0 |
| Debt increase | <30% | 30-100% | >100% |
| Status change | Minor | - | Critical (unemployed, bankrupt) |
| Node addition | - | - | Any new node type needed |

## Benefits

1. **Consistent**: LLM follows clear rules, predictable behavior
2. **Intelligent**: Distinguishes urgent from non-urgent changes
3. **Flexible**: No hard-coded thresholds in code, all in prompt
4. **Explainable**: Clear categories and reasoning in output
5. **Scalable**: Add new rules without changing code

## Implementation

All rules are in the StateResolver prompt (`prompts/state_resolver_prompt.txt`). No code changes needed to adjust thresholds or categories - just update the prompt.

The LLM uses these standards to make consistent decisions across all scenarios while remaining flexible for edge cases.


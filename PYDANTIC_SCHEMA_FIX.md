# Pydantic Schema Fix for Agno Output Schema

## Problem

OpenAI's structured output API requires that all fields in `properties` must be listed in the `required` array. When using Pydantic with optional fields (with defaults), this causes a validation error:

```
Invalid schema for response_format: 'required' is required to be supplied 
and to be an array including every key in properties. 
Extra required key 'extracted_data' supplied.
```

## Root Cause

Pydantic generates JSON schemas where:
- Fields with defaults are NOT included in `required`
- OpenAI expects ALL fields in `required` (even optional ones)

## Solution

Make ALL fields in agent response schemas optional by adding `| None = None`:

### Before (Broken)
```python
class InfoAgentResponse(BaseModel):
    complete: bool  # Required field - causes error
    question: str | None = None
    extracted_data: dict[str, Any] = {}  # Has default but not None
```

### After (Fixed)
```python
class InfoAgentResponse(BaseModel):
    complete: bool | None = None  # All fields optional
    question: str | None = None
    extracted_data: dict[str, Any] | None = None
```

## Files Updated

1. **`agents/info_agent.py`**
   - `InfoAgentResponse`: Made `complete` and `extracted_data` optional

2. **`agents/decision_agent.py`**
   - `DecisionResponse`: Made `reason` and `visited_all` optional

3. **`orchestrator/main.py`**
   - Added `or False` / `or {}` fallbacks when accessing optional fields
   - Ensures safe handling of None values

## Why This Works

- Pydantic now marks ALL fields as optional in the JSON schema
- OpenAI accepts the schema because `required: []` (empty array)
- The LLM still returns all fields (as instructed by the prompt)
- Code handles None values gracefully with fallbacks

## Testing

```bash
# Verify schemas work
python3 -c "
from agents.info_agent import InfoAgentResponse
from agents.decision_agent import DecisionResponse

# Both should work with minimal fields
InfoAgentResponse(complete=True)
DecisionResponse(visited_all=False)
print('✓ All schemas validated')
"
```

## Best Practice for Agno

When using `output_schema` with Agno agents:
- Make ALL fields optional (`| None = None`)
- Handle None values in your code with fallbacks
- Let the prompt guide the LLM to return complete data
- Don't rely on Pydantic validation for required fields

This follows the Agno framework pattern where the LLM is guided by instructions, not schema constraints.


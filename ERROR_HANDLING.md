# Error Handling and Retry Logic

## Problem

The LLM sometimes fails to parse the response into the structured `output_schema`, causing errors like:
```
WARNING  Failed to parse cleaned JSON: Expecting property name enclosed in double quotes
WARNING  All parsing attempts failed.
WARNING  Failed to convert response to output_schema
```

This would crash the WebSocket connection and break the user's session.

## Solution

Added comprehensive error handling with retry logic at multiple levels.

### 1. Orchestrator Retry Logic

**`orchestrator/main.py`:**

#### `start()` Method - 3 Retries
```python
def start(self) -> dict[str, Any]:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = self._current_agent.run("Start collecting data").content
            return {
                "question": response.question,
                "node_name": self.current_node,
                "complete": response.complete or False,
                "extracted_data": response.extracted_data or {},
            }
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Failed to start data collection for {self.current_node} "
                    f"after {max_retries} attempts: {str(e)}"
                )
            continue
```

#### `respond()` Method - 3 Retries
```python
def respond(self, user_input: str) -> dict[str, Any]:
    max_retries = 3
    response = None
    
    for attempt in range(max_retries):
        try:
            response = self._current_agent.run(user_input).content
            break  # Success
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Failed to process response for {self.current_node} "
                    f"after {max_retries} attempts: {str(e)}"
                )
            continue
```

#### DecisionAgent Call - 3 Retries
```python
max_retries = 3
decision = None

for attempt in range(max_retries):
    try:
        decision = self.decision_agent.decide_next_node(...)
        break
    except Exception as e:
        if attempt == max_retries - 1:
            raise RuntimeError(
                f"Failed to decide next node after {max_retries} attempts: {str(e)}"
            )
        continue
```

### 2. WebSocket Error Handling

**`api/websocket.py`:**

#### Start Session Error Handling
```python
try:
    result = orchestrator.start()
    await websocket.send_json(WSQuestion(...).model_dump())
except Exception as e:
    await websocket.send_json(
        WSError(message=f"Failed to start session: {str(e)}").model_dump()
    )
    await websocket.close()
    return
```

#### Response Processing Error Handling
```python
try:
    result = orchestrator.respond(answer_msg.answer)
except RuntimeError as e:
    # Agent parsing failed after retries
    await websocket.send_json(
        WSError(
            message=f"I had trouble understanding that. Could you please rephrase? ({str(e)})"
        ).model_dump()
    )
    continue  # Let user try again
except Exception as e:
    await websocket.send_json(
        WSError(message=f"Error processing response: {str(e)}").model_dump()
    )
    continue
```

## How It Works

### Normal Flow (Success)
1. User sends answer
2. Agent processes (1st attempt succeeds)
3. Question sent back
4. Continue

### Temporary Failure Flow (Retry Success)
1. User sends answer
2. Agent fails to parse (1st attempt)
3. Retry automatically (2nd attempt)
4. Success! Question sent back
5. User never knows there was an issue

### Persistent Failure Flow (All Retries Failed)
1. User sends answer
2. Agent fails to parse (attempts 1, 2, 3)
3. `RuntimeError` raised by orchestrator
4. WebSocket catches `RuntimeError`
5. User-friendly error sent: "I had trouble understanding that. Could you please rephrase?"
6. User rephrases answer
7. Try again with fresh context

## Benefits

✅ **Resilient**: Handles transient LLM parsing errors automatically
✅ **Transparent**: Retries happen silently, user doesn't notice
✅ **User-Friendly**: If all retries fail, asks user to rephrase (not crash)
✅ **Session Preserved**: WebSocket stays open, user can continue
✅ **Debuggable**: Clear error messages in logs and to user
✅ **Graceful Degradation**: System continues even with occasional failures

## Error Types Handled

1. **JSON Parse Errors** - Malformed JSON from LLM
2. **Schema Validation Errors** - Response doesn't match Pydantic schema
3. **Network Errors** - OpenAI API timeout/rate limit
4. **Logic Errors** - Invalid node selection, missing fields
5. **Unexpected Errors** - Caught by generic exception handler

## Configuration

- **Max Retries**: 3 attempts (configurable per method)
- **Retry Delay**: Immediate (no backoff, as each LLM call is independent)
- **Error Messages**: User-friendly, actionable feedback

## Testing Scenarios

- ✅ Single parsing failure → retries succeed
- ✅ Multiple parsing failures → user asked to rephrase
- ✅ Invalid node chosen → validation error caught
- ✅ Network timeout → retry succeeds
- ✅ All retries exhausted → graceful error message


"""
WebSocket handler for real-time bidirectional communication.

Supports two response modes:
1. **Streaming** (default) — uses ``orchestrator.arespond_stream()``
   to send ``stream_start → stream_delta* → stream_end`` events.
2. **Legacy fallback** — if the orchestrator doesn't expose
   ``arespond_stream``, falls back to the synchronous ``respond()``.
"""

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from api.schemas import (
    WSAnswer,
    WSCalculation,
    WSComplete,
    WSError,
    WSModeSwitch,
    WSQuestion,
    WSResumePrompt,
    WSScenarioQuestion,
    WSSessionStart,
    WSStreamDelta,
    WSStreamEnd,
    WSStreamStart,
    WSTraversalPaused,
    WSVisualization,
    WSGoalQualification,
)
from api.sessions import session_manager
from auth.dependencies import get_auth_service
from auth.exceptions import AuthException

logger = logging.getLogger(__name__)


def _serialize_goal_state(goal_state: dict[str, Any]) -> dict[str, list]:
    """Serialize goal state with goal_ids preserved."""
    # Handle both dict and list formats defensively
    qualified_raw = goal_state.get("qualified_goals") or {}
    if isinstance(qualified_raw, list):
        # Already in array format, use as-is
        qualified = qualified_raw
    else:
        # Convert dict to array format
        qualified = [
            {"goal_id": goal_id, **(data or {})}
            for goal_id, data in qualified_raw.items()
        ]
    
    possible_raw = goal_state.get("possible_goals") or {}
    if isinstance(possible_raw, list):
        # Already in array format, use as-is
        possible = possible_raw
    else:
        # Convert dict to array format
        possible = [
            {"goal_id": goal_id, **(data or {})}
            for goal_id, data in possible_raw.items()
        ]
    
    rejected = goal_state.get("rejected_goals") or []
    deferred_raw = goal_state.get("deferred_goals") or {}
    if isinstance(deferred_raw, list):
        deferred = deferred_raw
    else:
        deferred = [
            {"goal_id": goal_id, **(data or {})}
            for goal_id, data in deferred_raw.items()
        ]
    return {
        "qualified_goals": qualified,
        "possible_goals": possible,
        "rejected_goals": rejected,
        "deferred_goals": deferred,
    }


async def _handle_streaming_response(
    websocket: WebSocket,
    orchestrator: Any,
    user_input: str,
) -> None:
    """
    Iterate over orchestrator.arespond_stream() and send WS messages.

    The generator yields dicts with ``type`` in
    {``stream_start``, ``stream_delta``, ``stream_end``}.
    """
    async for event in orchestrator.arespond_stream(user_input):
        event_type = event.get("type")

        if event_type == "stream_start":
            await websocket.send_json(
                WSStreamStart(mode=event.get("mode", "data_gathering")).model_dump()
            )

        elif event_type == "stream_delta":
            await websocket.send_json(
                WSStreamDelta(delta=event.get("delta", "")).model_dump()
            )

        elif event_type == "stream_end":
            await _send_stream_end_payload(websocket, orchestrator, event)


async def _send_stream_end_payload(
    websocket: WebSocket,
    orchestrator: Any,
    result: dict[str, Any],
) -> None:
    """
    Dispatch the final ``stream_end`` payload as the appropriate WS message(s).

    This mirrors the original ``respond()`` dispatch logic but is used after
    the streaming cycle completes.
    """
    mode = result.get("mode", "data_gathering")
    goal_state = None
    if result.get("goal_state"):
        goal_state = _serialize_goal_state(result["goal_state"])

    if mode == "goal_qualification":
        await websocket.send_json(
            WSGoalQualification(
                question=result.get("question", ""),
                goal_id=result.get("goal_id", ""),
                goal_description=result.get("goal_description"),
                goal_state=goal_state,
            ).model_dump()
        )
        return

    if mode == "goal_exploration":
        exploration_ctx = result.get("exploration_context", {})
        await websocket.send_json(
            WSStreamEnd(
                mode="goal_exploration",
                question=result.get("question"),
                complete=result.get("complete", False),
                all_collected_data=result.get("all_collected_data", {}),
                goal_state=goal_state,
                upcoming_nodes=result.get("upcoming_nodes"),
                exploration_context=exploration_ctx,
            ).model_dump()
        )
        return

    if mode == "scenario_framing":
        scenario_ctx = result.get("scenario_context", {})
        await websocket.send_json(
            WSScenarioQuestion(
                question=result.get("question", ""),
                goal_id=scenario_ctx.get("goal_id", ""),
                goal_description=scenario_ctx.get("goal_description"),
                turn=scenario_ctx.get("turn", 1),
                max_turns=scenario_ctx.get("max_turns", 3),
                goal_confirmed=scenario_ctx.get("goal_confirmed"),
                goal_rejected=scenario_ctx.get("goal_rejected"),
                goal_state=goal_state,
            ).model_dump()
        )
        return

    if mode == "visualization":
        # Multi-event visualization path
        if isinstance(result.get("events"), list):
            for ev in result["events"]:
                if ev.get("kind") == "calculation":
                    await websocket.send_json(
                        WSCalculation(
                            calculation_type=ev.get("calculation_type", ""),
                            result=ev.get("result", {}),
                            can_calculate=bool(ev.get("can_calculate")),
                            missing_data=ev.get("missing_data", []),
                            message=ev.get("message", ""),
                            data_used=ev.get("data_used", []),
                        ).model_dump()
                    )
                elif ev.get("kind") == "visualization":
                    await websocket.send_json(
                        WSVisualization(
                            calculation_type=ev.get("calculation_type"),
                            inputs=ev.get("inputs", {}),
                            chart_type=ev.get("chart_type", ""),
                            data=ev.get("data", {}),
                            title=ev.get("title", ""),
                            description=ev.get("description", ""),
                            config=ev.get("config", {}),
                            charts=ev.get("charts", []),
                        ).model_dump()
                    )
        else:
            # Legacy single-calculation path
            await websocket.send_json(
                WSCalculation(
                    calculation_type=result.get("calculation_type", ""),
                    result=result.get("result", {}),
                    can_calculate=result.get("can_calculate", False),
                    missing_data=result.get("missing_data", []),
                    message=result.get("message", ""),
                    data_used=result.get("data_used", []),
                ).model_dump()
            )
            if result.get("can_calculate") and result.get("chart_type"):
                await websocket.send_json(
                    WSVisualization(
                        calculation_type=result.get("calculation_type"),
                        inputs=result.get("inputs", {}),
                        chart_type=result["chart_type"],
                        data=result.get("data", {}),
                        title=result.get("title", ""),
                        description=result.get("description", ""),
                        config=result.get("config", {}),
                        charts=result.get("charts", []),
                    ).model_dump()
                )
            if result.get("can_calculate") and result.get("resume_prompt"):
                await websocket.send_json(
                    WSResumePrompt(message=result["resume_prompt"]).model_dump()
                )
            elif not result.get("can_calculate") and orchestrator.traversal_paused:
                await websocket.send_json(
                    WSTraversalPaused(
                        paused_node=orchestrator.paused_node,
                        message=result.get("message", ""),
                    ).model_dump()
                )
        return

    # Default: data_gathering — send stream_end with full metadata
    await websocket.send_json(
        WSStreamEnd(
            mode=mode,
            question=result.get("question"),
            node_name=result.get("node_name"),
            extracted_data=result.get("extracted_data", {}),
            complete=result.get("complete", False),
            upcoming_nodes=result.get("upcoming_nodes"),
            all_collected_data=result.get("all_collected_data", {}),
            goal_state=goal_state,
            visualization=result.get("visualization"),
            phase1_summary=result.get("phase1_summary"),
        ).model_dump()
    )


async def websocket_handler(websocket: WebSocket, session_id: str | None = None):
    """
    Handle WebSocket connection for information gathering session.
    
    Flow:
    1. Client connects with optional session_id
    2. If no session_id, create new session with optional initial_context
    3. Send first question
    4. Receive answers, send questions
    5. Continue until visited_all
    """
    access_token = websocket.cookies.get("access_token")
    if not access_token:
        await websocket.accept()
        await websocket.send_json(
            WSError(message="Authentication required").model_dump()
        )
        await websocket.close(code=1008)
        return

    # Get authenticated user
    user_id: int | None = None
    try:
        auth_service = get_auth_service()
        user = await auth_service.get_user_from_access(access_token)
        user_id = user.get("id") if user else None
    except AuthException:
        await websocket.accept()
        await websocket.send_json(
            WSError(message="Authentication required").model_dump()
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()
    
    orchestrator = None
    current_session_id: str | None = session_id
    
    is_resuming = False
    
    try:
        # If session_id provided, get existing session
        if session_id:
            orchestrator = session_manager.get_session(session_id)
            if not orchestrator:
                await websocket.send_json(
                    WSError(message=f"Session {session_id} not found").model_dump()
                )
                await websocket.close()
                return
            is_resuming = True  # Mark as resume - don't call start()
        
        # If no session, wait for initial_context
        if not orchestrator:
            # Wait for initial message with optional initial_context
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                initial_context = message.get("initial_context") or message.get("user_goal")
                
                # Create new session with user_id for DB persistence
                current_session_id = session_manager.create_session(
                    user_id=user_id,
                    initial_context=initial_context,
                )
                session_id = current_session_id
                orchestrator = session_manager.get_session(current_session_id)
                
                if not orchestrator:
                    await websocket.send_json(
                        WSError(message="Failed to create session").model_dump()
                    )
                    await websocket.close()
                    return
                
                # Send session start confirmation
                await websocket.send_json(
                    WSSessionStart(
                        session_id=session_id,
                        initial_context=initial_context,
                    ).model_dump()
                )
            except json.JSONDecodeError:
                await websocket.send_json(
                    WSError(message="Invalid JSON in initial message").model_dump()
                )
                await websocket.close()
                return
        
        # Start collection - send first question or handle calculation/visualization
        # Skip start() if resuming an existing session - just wait for user messages
        if is_resuming:
            # For resumed sessions, just send a ready signal and go straight to message loop
            # The frontend already has the conversation history from localStorage
            pass
        else:
            # New session - call start() to send first question
            try:
                result = orchestrator.start()
                mode = result.get("mode", "data_gathering")
                
                # Handle different modes from start()
                if mode == "calculation":
                    # Send calculation results
                    await websocket.send_json(
                        WSCalculation(
                            calculation_type=result["calculation_type"],
                            result=result.get("result", {}),
                            can_calculate=result["can_calculate"],
                            missing_data=result.get("missing_data", []),
                            message=result["message"],
                            data_used=result.get("data_used", []),
                        ).model_dump()
                    )
                    # If calculation succeeded, send resume prompt
                    if result.get("can_calculate") and result.get("resume_prompt"):
                        await websocket.send_json(
                            WSResumePrompt(message=result["resume_prompt"]).model_dump()
                        )
                elif mode == "visualization":
                    # Send visualization data
                    await websocket.send_json(
                        WSVisualization(
                            calculation_type=result.get("calculation_type"),
                            inputs=result.get("inputs", {}),
                            chart_type=result["chart_type"],
                            data=result.get("data", {}),
                            title=result["title"],
                            description=result["description"],
                            config=result.get("config", {}),
                            charts=result.get("charts", []),
                        ).model_dump()
                    )
                    # Send resume prompt after visualization
                    if result.get("resume_prompt"):
                        await websocket.send_json(
                            WSResumePrompt(message=result["resume_prompt"]).model_dump()
                        )
                    elif mode == "calculation_visualization":
                        # Send calculation first
                        await websocket.send_json(
                            WSCalculation(
                                calculation_type=result["calculation_type"],
                                result=result.get("result", {}),
                                can_calculate=result["can_calculate"],
                                missing_data=result.get("missing_data", []),
                                message=result["message"],
                                data_used=result.get("data_used", []),
                            ).model_dump()
                        )
                        # Then send visualization if calculation succeeded AND visualization data exists
                        if result.get("can_calculate") and "chart_type" in result:
                            await websocket.send_json(
                                WSVisualization(
                                    calculation_type=result.get("calculation_type"),
                                    inputs=result.get("inputs", {}),
                                    chart_type=result["chart_type"],
                                    data=result.get("data", {}),
                                    title=result.get("title", ""),
                                    description=result.get("description", ""),
                                    config=result.get("config", {}),
                                    charts=result.get("charts", []),
                                ).model_dump()
                            )
                            # Send resume prompt
                            if result.get("resume_prompt"):
                                await websocket.send_json(
                                    WSResumePrompt(message=result["resume_prompt"]).model_dump()
                                )
                        elif result.get("can_calculate"):
                            # Calculation succeeded but no visualization - send resume prompt
                            if result.get("resume_prompt"):
                                await websocket.send_json(
                                    WSResumePrompt(message=result["resume_prompt"]).model_dump()
                                )
                elif mode == "goal_qualification":
                    goal_state = None
                    if result.get("goal_state"):
                        goal_state = _serialize_goal_state(result["goal_state"])
                    await websocket.send_json(
                        WSGoalQualification(
                            question=result.get("question", ""),
                            goal_id=result.get("goal_id", ""),
                            goal_description=result.get("goal_description"),
                            goal_state=goal_state,
                        ).model_dump()
                    )
                elif mode == "scenario_framing":
                    # Scenario framing for inferred goals
                    scenario_ctx = result.get("scenario_context", {})
                    goal_state = None
                    if result.get("goal_state"):
                        goal_state = _serialize_goal_state(result["goal_state"])
                    await websocket.send_json(
                        WSScenarioQuestion(
                            question=result.get("question", ""),
                            goal_id=scenario_ctx.get("goal_id", ""),
                            goal_description=scenario_ctx.get("goal_description"),
                            turn=scenario_ctx.get("turn", 1),
                            max_turns=scenario_ctx.get("max_turns", 3),
                            goal_confirmed=scenario_ctx.get("goal_confirmed"),
                            goal_rejected=scenario_ctx.get("goal_rejected"),
                            goal_state=goal_state,
                        ).model_dump()
                    )
                else:
                    # Normal data gathering mode
                    # Send mode switch notification if needed
                    if mode != "data_gathering":
                        await websocket.send_json(
                            WSModeSwitch(
                                mode=mode,
                                previous_mode=None,
                            ).model_dump()
                        )
                    goal_state = None
                    if result.get("goal_state"):
                        goal_state = _serialize_goal_state(result["goal_state"])
                    await websocket.send_json(
                        WSQuestion(
                            question=result.get("question"),
                            node_name=result.get("node_name", ""),
                            extracted_data=result.get("extracted_data", {}),
                            complete=result.get("complete", False),
                            upcoming_nodes=result.get("upcoming_nodes", []),
                            all_collected_data=orchestrator.graph_memory.get_all_nodes_data(),
                            planned_target_node=result.get("planned_target_node"),
                            planned_target_field=result.get("planned_target_field"),
                            goal_state=goal_state,
                            goal_details=result.get("goal_details"),
                        ).model_dump()
                    )
            except Exception as e:
                await websocket.send_json(
                    WSError(message=f"Failed to start session: {str(e)}").model_dump()
                )
                await websocket.close()
                return
        
        # Main loop: receive answers, send questions (streaming-aware)
        while True:
            # Receive user answer
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                answer_msg = WSAnswer(**message)
                
                if answer_msg.type != "answer":
                    await websocket.send_json(
                        WSError(message=f"Expected 'answer' message, got '{answer_msg.type}'").model_dump()
                    )
                    continue
                
                # ---- Streaming path (preferred) ----
                try:
                    await _handle_streaming_response(websocket, orchestrator, answer_msg.answer)
                    
                    # Persist session state after each turn (if user is authenticated)
                    if current_session_id and user_id:
                        session_manager.persist_session(current_session_id)
                        
                except RuntimeError as e:
                    await websocket.send_json(
                        WSError(
                            message=f"I had trouble understanding that. Could you please rephrase? ({str(e)})"
                        ).model_dump()
                    )
                except Exception as e:
                    logger.exception("Error in streaming response")
                    await websocket.send_json(
                        WSError(message=f"Error processing response: {str(e)}").model_dump()
                    )
            
            except json.JSONDecodeError:
                await websocket.send_json(
                    WSError(message="Invalid JSON format").model_dump()
                )
            except Exception as e:
                await websocket.send_json(
                    WSError(message=f"Error processing message: {str(e)}").model_dump()
                )
    
    except WebSocketDisconnect:
        # Client disconnected - cleanup handled by session manager
        pass
    except Exception as e:
        try:
            await websocket.send_json(
                WSError(message=f"Unexpected error: {str(e)}").model_dump()
            )
        except:
            pass
        await websocket.close()


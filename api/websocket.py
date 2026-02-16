"""
WebSocket handler for real-time bidirectional communication.

Uses ``orchestrator.arespond_stream()`` to send
``stream_start → stream_delta* → stream_end`` events.
"""

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from api.schemas import (
    WSAnswer,
    WSError,
    WSGoalQualification,
    WSQuestion,
    WSScenarioQuestion,
    WSSessionStart,
    WSStreamDelta,
    WSStreamEnd,
    WSStreamStart,
)
from api.sessions import session_manager
from auth.dependencies import get_auth_service
from auth.exceptions import AuthException

logger = logging.getLogger(__name__)


def _serialize_goal_state(goal_state: dict[str, Any]) -> dict[str, list]:
    """Serialize goal state with goal_ids preserved."""
    qualified_raw = goal_state.get("qualified_goals") or {}
    if isinstance(qualified_raw, list):
        qualified = qualified_raw
    else:
        qualified = [
            {"goal_id": goal_id, **(data or {})}
            for goal_id, data in qualified_raw.items()
        ]

    possible_raw = goal_state.get("possible_goals") or {}
    if isinstance(possible_raw, list):
        possible = possible_raw
    else:
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
    4. Receive answers, send streaming questions
    5. Continue until phase1 complete
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
            is_resuming = True

        # If no session, wait for initial_context
        if not orchestrator:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                initial_context = message.get("initial_context") or message.get("user_goal")

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

        # Start collection — skip start() if resuming
        if not is_resuming:
            try:
                result = orchestrator.start()
                mode = result.get("mode", "data_gathering")
                goal_state = None
                if result.get("goal_state"):
                    goal_state = _serialize_goal_state(result["goal_state"])

                await websocket.send_json(
                    WSStreamEnd(
                        mode=mode,
                        question=result.get("question"),
                        complete=result.get("complete", False),
                        all_collected_data=result.get("all_collected_data", {}),
                        goal_state=goal_state,
                        upcoming_nodes=result.get("upcoming_nodes"),
                        exploration_context=result.get("exploration_context"),
                    ).model_dump()
                )
            except Exception as e:
                logger.exception("Failed to start session")
                await websocket.send_json(
                    WSError(message=f"Failed to start session: {str(e)}").model_dump()
                )
                await websocket.close()
                return

        # Main loop: receive answers, send streaming questions
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                answer_msg = WSAnswer(**message)

                if answer_msg.type != "answer":
                    await websocket.send_json(
                        WSError(message=f"Expected 'answer' message, got '{answer_msg.type}'").model_dump()
                    )
                    continue

                try:
                    await _handle_streaming_response(websocket, orchestrator, answer_msg.answer)

                    # Persist session state after each turn
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
        pass
    except Exception as e:
        try:
            await websocket.send_json(
                WSError(message=f"Unexpected error: {str(e)}").model_dump()
            )
        except Exception:
            pass
        await websocket.close()

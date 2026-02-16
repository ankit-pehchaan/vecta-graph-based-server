"""
Session management for orchestrator instances.

Integrates with PostgreSQL for user-owned data persistence.
"""

import os
from typing import Any

from orchestrator import Orchestrator
from db.repos import UserRepository, SessionRepository


class SessionManager:
    """
    Manages orchestrator sessions.

    Sessions are linked to users, with data persisted to PostgreSQL.
    """

    def __init__(self):
        self.sessions: dict[str, Orchestrator] = {}
        self.user_repo = UserRepository()
        self.session_repo = SessionRepository()

    def create_session(
        self,
        user_id: int | None = None,
        initial_context: str | None = None,
    ) -> str:
        """Create a new session and return session ID."""
        session_id = os.urandom(16).hex()

        if user_id:
            try:
                db_session_id = self.session_repo.create_session(user_id)
                session_id = db_session_id
            except Exception:
                pass

        orchestrator = Orchestrator(
            initial_context=initial_context,
            session_id=session_id,
            user_id=user_id,
        )

        # MVP: Always start fresh sessions. Per-user data is still
        # persisted via persist_session() for future resumption support.
        # When ready, uncomment the block below to load previous data.
        # if user_id:
        #     self._load_user_data(orchestrator, user_id)

        self.sessions[session_id] = orchestrator
        return session_id

    def _load_user_data(self, orchestrator: Orchestrator, user_id: int) -> None:
        """Load user's existing profile data into orchestrator's GraphMemory."""
        try:
            # Load node snapshots
            node_data = self.user_repo.load_user_graph_data(user_id)
            for node_name, data in node_data.items():
                orchestrator.graph_memory.node_snapshots[node_name] = data
                if data:
                    orchestrator.graph_memory.visited_nodes.add(node_name)
                    orchestrator.graph_memory.pending_nodes.discard(node_name)

            # Load goals
            goal_state = self.user_repo.load_user_goals(user_id)
            orchestrator.graph_memory.qualified_goals = goal_state.get("qualified_goals", {})
            orchestrator.graph_memory.possible_goals = goal_state.get("possible_goals", {})
            orchestrator.graph_memory.rejected_goals = set(goal_state.get("rejected_goals", []))

            # Load session state if resuming
            session_state = self.session_repo.load_session_state(orchestrator.session_id)
            if session_state:
                if session_state.get("visited_nodes"):
                    orchestrator.graph_memory.visited_nodes.update(session_state["visited_nodes"])
                if session_state.get("pending_nodes"):
                    orchestrator.graph_memory.pending_nodes.update(session_state["pending_nodes"])
                if session_state.get("omitted_nodes"):
                    orchestrator.graph_memory.omitted_nodes.update(session_state["omitted_nodes"])
                if session_state.get("rejected_nodes"):
                    orchestrator.graph_memory.rejected_nodes.update(session_state["rejected_nodes"])
                if session_state.get("asked_questions"):
                    for node, fields in session_state["asked_questions"].items():
                        orchestrator.graph_memory.asked_questions[node] = set(fields)
                if session_state.get("goal_intake_complete"):
                    orchestrator._goal_intake_complete = True
        except Exception as e:
            import logging
            logging.error(f"Failed to load user data: {e}")

    def get_session(self, session_id: str) -> Orchestrator | None:
        """Get orchestrator for a session."""
        return self.sessions.get(session_id)

    def persist_session(self, session_id: str) -> None:
        """Persist current session state to database."""
        orchestrator = self.sessions.get(session_id)
        if not orchestrator or not orchestrator.user_id:
            return

        try:
            self.user_repo.save_all_graph_data(
                user_id=orchestrator.user_id,
                node_snapshots=orchestrator.graph_memory.node_snapshots,
                goal_state={
                    "qualified_goals": orchestrator.graph_memory.qualified_goals,
                    "possible_goals": orchestrator.graph_memory.possible_goals,
                    "rejected_goals": list(orchestrator.graph_memory.rejected_goals),
                },
            )

            self.session_repo.save_session_state(
                session_id=session_id,
                visited_nodes=list(orchestrator.graph_memory.visited_nodes),
                pending_nodes=list(orchestrator.graph_memory.pending_nodes),
                omitted_nodes=list(orchestrator.graph_memory.omitted_nodes),
                rejected_nodes=list(orchestrator.graph_memory.rejected_nodes),
                current_node=orchestrator._current_node_being_collected,
                goal_intake_complete=orchestrator._goal_intake_complete,
                asked_questions=orchestrator.graph_memory.get_asked_questions_dict(),
            )
        except Exception as e:
            import logging
            logging.error(f"Failed to persist session: {e}")

    def delete_session(self, session_id: str) -> None:
        """Delete a session from memory (DB record remains)."""
        if session_id in self.sessions:
            del self.sessions[session_id]


session_manager = SessionManager()

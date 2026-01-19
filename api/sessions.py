"""
Session management for orchestrator instances.
"""

import os

from orchestrator import Orchestrator


class SessionManager:
    """Manages orchestrator sessions."""
    
    def __init__(self):
        """Initialize session manager."""
        self.sessions: dict[str, Orchestrator] = {}
    
    def create_session(self, initial_context: str | None = None) -> str:
        """Create a new session and return session ID."""
        session_id = os.urandom(16).hex()
        self.sessions[session_id] = Orchestrator(
            initial_context=initial_context,
            session_id=session_id,
        )
        return session_id
    
    def get_session(self, session_id: str) -> Orchestrator | None:
        """Get orchestrator for a session."""
        return self.sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]


session_manager = SessionManager()

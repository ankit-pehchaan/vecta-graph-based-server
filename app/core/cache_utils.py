"""
Cache utilities for agent and profile caching.

This module is kept separate to avoid circular imports between
agno_agent_service and sync_tools.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("cache_utils")

# Module-level dirty tracking for agent cache invalidation
# This allows sync tools (running in threads) to mark profiles as dirty
# without needing a reference to the AgnoAgentService instance
_dirty_profiles: set[str] = set()

# Module-level profile context cache with timestamps
# Key: username, Value: (context_string, timestamp)
_profile_context_cache: dict[str, tuple[str, float]] = {}
PROFILE_CONTEXT_TTL_SECONDS = 300  # 5 minutes TTL


def mark_profile_dirty(username: str) -> None:
    """
    Mark a user's profile as dirty for agent cache invalidation.

    Call this from sync_tools when user profile data is updated.
    The next agent request will check this and recreate with fresh context.
    Also invalidates the profile context cache.
    """
    _dirty_profiles.add(username)
    # Also clear profile context cache for this user
    _profile_context_cache.pop(username, None)
    logger.debug(f"[CACHE] Profile marked dirty (module-level): {username}")


def is_profile_dirty(username: str) -> bool:
    """Check if a user's profile is marked as dirty."""
    return username in _dirty_profiles


def clear_profile_dirty(username: str) -> None:
    """Clear the dirty flag for a user."""
    _dirty_profiles.discard(username)


def get_cached_profile_context(username: str) -> Optional[str]:
    """
    Get cached profile context if available and not expired.

    Returns:
        Cached context string if valid, None otherwise
    """
    current_time = time.time()
    if username in _profile_context_cache:
        cached_context, timestamp = _profile_context_cache[username]
        if current_time - timestamp < PROFILE_CONTEXT_TTL_SECONDS:
            logger.debug(f"[CACHE] Profile context cache hit for: {username}")
            return cached_context
    return None


def set_cached_profile_context(username: str, context: str) -> None:
    """Cache profile context for a user."""
    _profile_context_cache[username] = (context, time.time())
    logger.debug(f"[CACHE] Profile context cached for: {username}")

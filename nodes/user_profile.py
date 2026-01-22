"""
UserProfile node - Root node of the financial life graph.

This is the entry point that connects to all major life aspects:
Personal, Family, Financial, Assets, Liabilities, Goals, Insurance, Retirement.
"""

from typing import Any

from pydantic import Field

from nodes.base import BaseNode


class UserProfile(BaseNode):
    """
    Root node representing a user's complete financial life profile.
    
    This node serves as the container for all other nodes in the graph,
    connected via edges to child nodes representing different life aspects.
    """
    
    node_type: str = Field(default="user_profile", frozen=True)
    user_id: str | None = Field(default=None, description="Unique user identifier")
    
    def model_post_init(self, __context: Any) -> None:
        """Initialize as root node."""
        super().model_post_init(__context)


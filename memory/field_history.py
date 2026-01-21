"""
Field history and node update models for state resolution.

These models support temporal tracking, conflict resolution, and 
cross-node data updates.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FieldHistory(BaseModel):
    """
    History record for a single field value change.
    
    Tracks temporal evolution of field values with conflict detection.
    """
    value: Any
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str = Field(default="user_input", description="Source of update: user_input, calculation, etc.")
    previous_value: Any | None = None
    conflict_resolved: bool = False
    reasoning: str | None = Field(default=None, description="Why this update was made")
    
    class Config:
        arbitrary_types_allowed = True


class NodeUpdate(BaseModel):
    """
    Represents a single update to a node field.
    
    Used by StateResolverAgent to communicate extracted facts to GraphMemory.
    """
    node_name: str | None = Field(default=None, description="Target node to update")
    field_name: str | None = Field(default=None, description="Field within the node")
    value: Any | None = Field(default=None, description="New value for the field")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence in extraction")
    temporal_context: str | None = Field(default=None, description="Temporal context: past, present, future")
    is_correction: bool | None = Field(default=None, description="Is this correcting previous data?")
    reasoning: str | None = Field(default=None, description="Why this update was extracted")
    
    class Config:
        arbitrary_types_allowed = True


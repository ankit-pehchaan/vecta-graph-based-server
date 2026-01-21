"""
Base classes for the Financial Life Graph nodes.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class CollectionCondition(BaseModel):
    """
    Minimal conditional requirement for collection semantics.

    Keep this mechanical: it exists to express dependencies like:
    - if number_of_children > 0, then children_ages is required
    """

    if_field: str
    operator: str  # one of: "==", "!=", ">", ">=", "<", "<=", "in", "not_in", "truthy"
    value: Any | None = None
    then_require: list[str] = Field(default_factory=list)


class CollectionSpec(BaseModel):
    """
    Mechanical completion semantics for a node.

    This is NOT a goal-deduction rule system. It only defines what minimum
    data indicates the node has been answered sufficiently to move on.
    """

    # Fields that must be present in the snapshot (key exists), regardless of value truthiness.
    required_fields: list[str] = Field(default_factory=list)

    # At least one of these fields must be present (key exists). Useful for nodes where
    # user may answer via different but equivalent fields.
    require_any_of: list[str] = Field(default_factory=list)

    # Minimal conditional requirements (optional).
    conditional_required: list[CollectionCondition] = Field(default_factory=list)


class BaseNode(BaseModel):
    """Base class for all nodes in the graph."""
    
    id: str | None = Field(default_factory=lambda: str(uuid4()), exclude=True)
    node_type: str | None = Field(default=None, exclude=True)
    created_at: datetime | None = Field(default_factory=datetime.now, exclude=True)
    updated_at: datetime | None = Field(default_factory=datetime.now, exclude=True)
    metadata: dict[str, Any] | None = Field(default_factory=dict, exclude=True)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert node to dictionary."""
        return self.model_dump(exclude_none=True)

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        """
        Optional collection semantics for completion checks.

        Nodes can override this to define the minimal required fields for completion.
        Returning None means orchestrator falls back to schema-based checks.
        """
        return None

    @classmethod
    def detail_portfolios(cls) -> dict[str, type[BaseModel]]:
        """
        Optional: declare portfolio dict fields that support detail-level prompting.

        Return a mapping of:
        - portfolio_field_name -> Pydantic model class describing each entry value

        The orchestrator can use this to surface missing subfields (as dotted paths)
        without making those subfields strict mechanical completion requirements.
        """
        return {}
    
    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class Edge(BaseModel):
    """Represents a relationship between nodes."""
    
    id: str | None = Field(default_factory=lambda: str(uuid4()))
    from_node: str | None = None
    to_node: str | None = None
    edge_type: str | None = Field(default="relates_to")
    reason: str | None = None
    created_at: datetime | None = Field(default_factory=datetime.now)
    metadata: dict[str, Any] | None = Field(default_factory=dict)
    
    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class BaseGraph:
    """
    Base graph manager for nodes and edges.
    
    This is a simple in-memory graph structure that can be serialized.
    """
    
    def __init__(self):
        """Initialize empty graph."""
        self.nodes: dict[str, BaseNode] = {}
        self.edges: list[Edge] = []
    
    def add_node(self, node: BaseNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node
    
    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)
    
    def get_node(self, node_id: str) -> BaseNode | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)
    
    def get_edges_from(self, node_id: str) -> list[Edge]:
        """Get all edges originating from a node."""
        return [e for e in self.edges if e.from_node == node_id]
    
    def get_edges_to(self, node_id: str) -> list[Edge]:
        """Get all edges pointing to a node."""
        return [e for e in self.edges if e.to_node == node_id]
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dictionary."""
        return {
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "edges": [edge.model_dump(exclude_none=True) for edge in self.edges],
        }


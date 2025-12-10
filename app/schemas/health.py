"""Health check schemas for monitoring application status."""
from pydantic import BaseModel, Field
from typing import Dict, Optional, Literal
from datetime import datetime


class ComponentHealth(BaseModel):
    """Health status of a single component."""
    status: Literal["healthy", "unhealthy", "degraded"] = Field(
        description="Component health status"
    )
    message: Optional[str] = Field(
        default=None,
        description="Additional information about the component status"
    )
    latency_ms: Optional[float] = Field(
        default=None,
        description="Component response latency in milliseconds"
    )
    details: Optional[Dict] = Field(
        default=None,
        description="Additional component-specific details"
    )


class HealthCheckResponse(BaseModel):
    """Comprehensive health check response."""
    status: Literal["healthy", "unhealthy", "degraded"] = Field(
        description="Overall system health status"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Time of health check"
    )
    version: str = Field(
        description="Application version"
    )
    uptime_seconds: float = Field(
        description="Application uptime in seconds"
    )
    components: Dict[str, ComponentHealth] = Field(
        description="Health status of individual components"
    )


class LivenessResponse(BaseModel):
    """Simple liveness probe response."""
    status: str = Field(default="alive")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReadinessResponse(BaseModel):
    """Readiness probe response."""
    status: Literal["ready", "not_ready"] = Field(
        description="Whether the application is ready to serve traffic"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: Dict[str, bool] = Field(
        description="Status of individual readiness checks"
    )

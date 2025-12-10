"""Health check endpoints for monitoring and orchestration."""
from fastapi import APIRouter, status, Response
from app.schemas.health import (
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse
)
from app.schemas.response import ApiResponse
from app.services.health import HealthCheckService

router = APIRouter()

# Initialize health check service
health_service = HealthCheckService()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Comprehensive Health Check",
    description="Get detailed health status of all application components"
)
async def health_check():
    """
    Comprehensive health check endpoint.

    Returns detailed health information about:
    - Database connectivity
    - Redis/cache status
    - AWS Secrets Manager
    - System resources (CPU, Memory, Disk)
    - Configuration validity
    - Application uptime

    This endpoint is useful for monitoring dashboards and detailed health analysis.
    """
    return await health_service.get_comprehensive_health()


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Simple check to verify the application is running"
)
async def liveness_probe():
    """
    Liveness probe endpoint.

    Used by Kubernetes/Docker to determine if the application is alive.
    Returns 200 if the application process is running.

    This is a lightweight check that should always succeed if the app is up.
    """
    if health_service.check_liveness():
        return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe",
    description="Check if the application is ready to serve traffic"
)
async def readiness_probe(response: Response):
    """
    Readiness probe endpoint.

    Used by Kubernetes/Docker to determine if the application is ready to receive traffic.
    Returns 200 if ready, 503 if not ready.

    Checks:
    - Configuration loaded
    - Startup complete
    - Critical services available
    """
    is_ready, checks = await health_service.check_readiness()

    if is_ready:
        return ReadinessResponse(
            status="ready",
            checks=checks
        )
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            checks=checks
        )


@router.get(
    "/health/status",
    response_model=ApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Simple Health Status",
    description="Simple health check returning overall status"
)
async def simple_health_status():
    """
    Simple health status endpoint.

    Returns a simplified health status compatible with the standard ApiResponse format.
    Useful for basic health checks without detailed component information.
    """
    health = await health_service.get_comprehensive_health()

    return ApiResponse(
        success=health.status == "healthy",
        message=f"System is {health.status}",
        data={
            "status": health.status,
            "uptime_seconds": health.uptime_seconds,
            "version": health.version,
            "timestamp": health.timestamp.isoformat()
        }
    )


@router.get(
    "/health/components/{component_name}",
    response_model=ApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Individual Component Health",
    description="Get health status of a specific component"
)
async def component_health(component_name: str):
    """
    Get health status of a specific component.

    Available components:
    - database
    - redis
    - aws_secrets
    - system_resources
    - configuration
    """
    health = await health_service.get_comprehensive_health()

    if component_name not in health.components:
        return ApiResponse(
            success=False,
            message=f"Component '{component_name}' not found",
            data={
                "available_components": list(health.components.keys())
            }
        )

    component = health.components[component_name]

    return ApiResponse(
        success=component.status == "healthy",
        message=f"Component '{component_name}' is {component.status}",
        data={
            "component": component_name,
            "status": component.status,
            "message": component.message,
            "latency_ms": component.latency_ms,
            "details": component.details
        }
    )

"""Health check service for monitoring application components."""
import time
import psutil
import asyncio
from datetime import datetime
from typing import Dict, Tuple
from app.schemas.health import ComponentHealth, HealthCheckResponse
from app.core.database import db_manager


# Store application start time
APPLICATION_START_TIME = time.time()


class HealthCheckService:
    """Service for checking application and component health."""

    def __init__(self):
        """Initialize health check service."""
        self.version = "1.0.0"

    async def check_database(self) -> ComponentHealth:
        """
        Check database connectivity and health.

        Performs actual PostgreSQL connection check.
        """
        start_time = time.time()

        try:
            # Check if database manager is initialized
            if not db_manager.is_initialized:
                latency_ms = (time.time() - start_time) * 1000
                return ComponentHealth(
                    status="unhealthy",
                    message="Database not initialized",
                    latency_ms=round(latency_ms, 2),
                    details={"initialized": False}
                )

            # Perform actual database connection check
            is_connected = await db_manager.check_connection()

            latency_ms = (time.time() - start_time) * 1000

            if is_connected:
                return ComponentHealth(
                    status="healthy",
                    message="Database connection successful",
                    latency_ms=round(latency_ms, 2),
                    details={
                        "type": "postgresql",
                        "initialized": True,
                        "connected": True
                    }
                )
            else:
                return ComponentHealth(
                    status="unhealthy",
                    message="Database connection failed",
                    latency_ms=round(latency_ms, 2),
                    details={
                        "type": "postgresql",
                        "initialized": True,
                        "connected": False
                    }
                )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                status="unhealthy",
                message=f"Database check failed: {str(e)}",
                latency_ms=round(latency_ms, 2)
            )

    async def check_system_resources(self) -> ComponentHealth:
        """Check system resource usage (CPU, Memory, Disk)."""
        start_time = time.time()

        try:
            # Get CPU usage
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # Get memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Get disk usage
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            latency_ms = (time.time() - start_time) * 1000

            # Determine status based on resource usage
            status = "healthy"
            message = "System resources within normal limits"

            if cpu_percent > 90 or memory_percent > 90 or disk_percent > 90:
                status = "unhealthy"
                message = "System resources critically high"
            elif cpu_percent > 75 or memory_percent > 75 or disk_percent > 85:
                status = "degraded"
                message = "System resources elevated"

            return ComponentHealth(
                status=status,
                message=message,
                latency_ms=round(latency_ms, 2),
                details={
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_percent": round(memory_percent, 2),
                    "memory_available_mb": round(memory.available / (1024 * 1024), 2),
                    "disk_percent": round(disk_percent, 2),
                    "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 2)
                }
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                status="unhealthy",
                message=f"System resource check failed: {str(e)}",
                latency_ms=round(latency_ms, 2)
            )

    async def check_configuration(self) -> ComponentHealth:
        """Check application configuration validity."""
        start_time = time.time()

        try:
            from app.core.config import settings

            issues = []

            # Check critical configuration
            if settings.ENVIRONMENT == "prod":
                if len(settings.SECRET_KEY) < 32:
                    issues.append("SECRET_KEY too short for production")
                if not settings.BASE_URL.startswith("https://"):
                    issues.append("BASE_URL should use HTTPS in production")

            latency_ms = (time.time() - start_time) * 1000

            if issues:
                return ComponentHealth(
                    status="degraded",
                    message="Configuration has issues",
                    latency_ms=round(latency_ms, 2),
                    details={
                        "issues": issues,
                        "environment": settings.ENVIRONMENT
                    }
                )

            return ComponentHealth(
                status="healthy",
                message="Configuration valid",
                latency_ms=round(latency_ms, 2),
                details={
                    "environment": settings.ENVIRONMENT,
                    "aws_secrets_enabled": settings.USE_AWS_SECRETS
                }
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                status="unhealthy",
                message=f"Configuration check failed: {str(e)}",
                latency_ms=round(latency_ms, 2)
            )

    def get_uptime(self) -> float:
        """Get application uptime in seconds."""
        return time.time() - APPLICATION_START_TIME

    async def get_comprehensive_health(self) -> HealthCheckResponse:
        """
        Get comprehensive health check of all components.

        Returns overall system health with details of all components.
        """
        # Run all health checks concurrently
        database_health, redis_health, aws_health, system_health, config_health = await asyncio.gather(
            self.check_database(),
            self.check_system_resources(),
            self.check_configuration()
        )

        components = {
            "database": database_health,
            "redis": redis_health,
            "aws_secrets": aws_health,
            "system_resources": system_health,
            "configuration": config_health
        }

        # Determine overall status
        statuses = [comp.status for comp in components.values()]

        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return HealthCheckResponse(
            status=overall_status,
            timestamp=datetime.utcnow(),
            version=self.version,
            uptime_seconds=round(self.get_uptime(), 2),
            components=components
        )

    async def check_readiness(self) -> Tuple[bool, Dict[str, bool]]:
        """
        Check if application is ready to serve traffic.

        Returns:
            Tuple of (is_ready, checks_dict)
        """
        # Check database connectivity
        database_health = await self.check_database()

        checks = {
            "configuration_loaded": True,  # Always true if we get here
            "startup_complete": self.get_uptime() > 2,  # Give 2 seconds for startup
            "database_connected": database_health.status != "unhealthy"
        }

        is_ready = all(checks.values())

        return is_ready, checks

    def check_liveness(self) -> bool:
        """
        Check if application is alive (simple check).

        Returns:
            True if application is responsive
        """
        return True

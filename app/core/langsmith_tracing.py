"""
LangSmith Tracing Integration for Agno Agents.

This module provides OpenTelemetry-based tracing to LangSmith for comprehensive
observability of agent runs, tool executions, and model calls.
"""

import os
import logging
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.agno import AgnoInstrumentor

logger = logging.getLogger(__name__)

_tracing_initialized = False


def initialize_langsmith_tracing() -> bool:
    """
    Initialize LangSmith tracing for Agno agents.

    Requires the following environment variables:
    - LANGSMITH_API_KEY: Your LangSmith API key
    - LANGSMITH_TRACING: Set to "true" to enable tracing
    - LANGSMITH_PROJECT: Project name (default: "vecta-financial-advisor")
    - LANGSMITH_ENDPOINT: API endpoint (default: "https://api.smith.langchain.com")

    Returns:
        bool: True if tracing was initialized successfully, False otherwise.
    """
    global _tracing_initialized

    if _tracing_initialized:
        logger.debug("LangSmith tracing already initialized")
        return True

    api_key = os.getenv("LANGSMITH_API_KEY")
    project = os.getenv("LANGSMITH_PROJECT", "vecta-financial-advisor")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"

    if not tracing_enabled:
        logger.info("LangSmith tracing is disabled (LANGSMITH_TRACING != 'true')")
        return False

    if not api_key:
        logger.warning("LangSmith tracing enabled but LANGSMITH_API_KEY not configured")
        return False

    try:
        # Create resource with service name
        resource = Resource.create({
            "service.name": "vecta-financial-advisor",
            "service.version": "1.0.0",
        })

        # Configure tracer provider with resource
        tracer_provider = TracerProvider(resource=resource)

        # LangSmith OTLP endpoint format
        otlp_endpoint = f"{endpoint}/otel/v1/traces"
        headers = {
            "x-api-key": api_key,
            "Langsmith-Project": project,
        }

        logger.info(f"Configuring OTLP exporter - endpoint: {otlp_endpoint}")

        # Configure OTLP exporter for LangSmith
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            headers=headers,
        )

        # Add span processor
        tracer_provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))

        # Set as global tracer provider (required for instrumentation to work)
        trace.set_tracer_provider(tracer_provider)

        # Instrument Agno - this patches Agent.run() and Agent.arun()
        instrumentor = AgnoInstrumentor()
        if not instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.instrument(tracer_provider=tracer_provider)
            logger.info("Agno instrumented successfully")
        else:
            logger.info("Agno already instrumented")

        _tracing_initialized = True
        logger.info(f"LangSmith tracing initialized for project: {project}")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize LangSmith tracing: {e}")
        return False

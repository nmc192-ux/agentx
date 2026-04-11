"""
AgentX Platform — OpenTelemetry Setup
══════════════════════════════════════
Phase 19 foundation: lightweight, zero-crash tracing setup.

Design principles:
  1. Optional hard dependency — if opentelemetry packages are absent the
     whole module is a safe no-op; nothing in the API path breaks.
  2. OTLP/HTTP export when OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise
     stdout in development and no-op in production.
  3. Auto-instrumentation helpers for FastAPI, asyncpg, and Redis are
     each independently safe to call regardless of package presence.

Usage (in main.py lifespan)::

    from src.observability import setup_tracing, auto_instrument_fastapi

    provider = setup_tracing("agentx-api")
    auto_instrument_fastapi(app)

Usage (in workers)::

    from src.observability import setup_tracing

    setup_tracing("agentx-worker")
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger("agentx.otel")


def setup_tracing(
    service_name: str,
    service_version: str = "0.0.0",
    otlp_endpoint: str | None = None,
) -> "TracerProvider | None":
    """Configure OpenTelemetry tracing and register the global provider.

    Safe to call even when the ``opentelemetry-sdk`` package is not installed.

    Args:
        service_name:    ``service.name`` resource attribute.
                         Convention: ``"agentx-api"``, ``"agentx-worker"``.
        service_version: ``service.version`` resource attribute.
                         Defaults to ``"0.0.0"``; set from ``settings.app_version``
                         when available.
        otlp_endpoint:   OTLP/HTTP base URL, e.g. ``"http://otelcol:4318"``.
                         Falls back to ``$OTEL_EXPORTER_OTLP_ENDPOINT`` if not
                         provided.  When neither is set, behaviour depends on
                         ``APP_ENV``: stdout in development, no-op in production.

    Returns:
        The configured :class:`TracerProvider`, or ``None`` if the SDK is absent.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.debug("opentelemetry-sdk not installed — tracing disabled")
        return None

    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    app_env  = os.environ.get("APP_ENV", "development")

    resource = Resource.create({
        SERVICE_NAME:    service_name,
        SERVICE_VERSION: service_version,
        "deployment.environment": app_env,
    })

    provider = TracerProvider(resource=resource)

    if endpoint:
        # ── OTLP/HTTP export (production or explicit dev endpoint) ────────────
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            traces_url = f"{endpoint.rstrip('/')}/v1/traces"
            exporter   = OTLPSpanExporter(endpoint=traces_url)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(
                "OTel tracing → OTLP/HTTP  endpoint=%s  service=%s",
                endpoint,
                service_name,
            )
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-http not installed; "
                "traces will not be exported even though "
                "OTEL_EXPORTER_OTLP_ENDPOINT=%s is set.  "
                "Add opentelemetry-exporter-otlp-proto-http to requirements.txt.",
                endpoint,
            )

    elif app_env != "production":
        # ── Dev fallback: print spans to stdout ───────────────────────────────
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info(
            "OTel tracing → stdout (dev mode, no OTEL_EXPORTER_OTLP_ENDPOINT set)  "
            "service=%s",
            service_name,
        )

    else:
        # ── Production without endpoint: no-op (no console noise) ─────────────
        logger.info(
            "OTel tracing disabled in production "
            "(set OTEL_EXPORTER_OTLP_ENDPOINT to enable)  service=%s",
            service_name,
        )

    trace.set_tracer_provider(provider)
    return provider


def auto_instrument_fastapi(app: object) -> None:
    """Auto-instrument a FastAPI application.

    Adds an ASGI middleware that creates a server span for every request,
    propagates W3C Trace-Context headers, and records HTTP attributes.

    Safe to call when ``opentelemetry-instrumentation-fastapi`` is absent.

    Args:
        app: The ``FastAPI`` application instance.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import]
        FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
        logger.info("OTel FastAPI auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed — skipping")


def auto_instrument_asyncpg() -> None:
    """Auto-instrument asyncpg with OTel database client spans.

    Wraps asyncpg connection methods so every SQL query appears as a
    ``db.query`` child span with ``db.statement`` attribute.

    Safe to call when ``opentelemetry-instrumentation-asyncpg`` is absent.
    """
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor  # type: ignore[import]
        AsyncPGInstrumentor().instrument()
        logger.info("OTel asyncpg auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-asyncpg not installed — skipping")


def auto_instrument_redis() -> None:
    """Auto-instrument redis-py with OTel cache client spans.

    Wraps redis-py so every command appears as a ``redis.command`` child span
    with the command name and key as attributes.

    Safe to call when ``opentelemetry-instrumentation-redis`` is absent.
    """
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor  # type: ignore[import]
        RedisInstrumentor().instrument()
        logger.info("OTel Redis auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-redis not installed — skipping")

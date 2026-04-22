"""
AgentX Platform — OpenTelemetry Setup
══════════════════════════════════════
Phase 19 foundation: lightweight, zero-crash tracing setup.
Phase 4.1 update: Honeycomb OTLP export via env-var headers.

Design principles:
  1. Optional hard dependency — if opentelemetry packages are absent the
     whole module is a safe no-op; nothing in the API path breaks.
  2. OTLP/HTTP export when OTEL_EXPORTER_OTLP_ENDPOINT is set; otherwise
     stdout in development and no-op in production.
  3. Auto-instrumentation helpers for FastAPI, asyncpg, and Redis are
     each independently safe to call regardless of package presence.
  4. OTEL_EXPORTER_OTLP_HEADERS is parsed and forwarded to the exporter,
     enabling Honeycomb (or any header-authenticated OTLP backend) without
     code changes:

     OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
     OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=$HONEYCOMB_API_KEY

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


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    """Parse the ``OTEL_EXPORTER_OTLP_HEADERS`` wire format.

    The format is a comma-separated list of ``key=value`` pairs as specified
    by the OpenTelemetry Environment Variable Specification §4.1.2::

        key1=value1,key2=value2

    Keys and values are trimmed of surrounding whitespace.  An empty string
    returns an empty dict safely.

    Example::

        _parse_otlp_headers("x-honeycomb-team=abc123,x-dataset=agentx")
        # → {"x-honeycomb-team": "abc123", "x-dataset": "agentx"}
    """
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, _, value = pair.partition("=")
            headers[key.strip()] = value.strip()
    return headers


def setup_tracing(
    service_name: str,
    service_version: str = "0.0.0",
    otlp_endpoint: str | None = None,
    otlp_headers: dict[str, str] | None = None,
) -> "TracerProvider | None":
    """Configure OpenTelemetry tracing and register the global provider.

    Safe to call even when the ``opentelemetry-sdk`` package is not installed.

    Honeycomb quick-start — set these two environment variables and you're done::

        OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
        OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=$HONEYCOMB_API_KEY

    Args:
        service_name:    ``service.name`` resource attribute.
                         Convention: ``"agentx-api"``, ``"agentx-worker"``.
        service_version: ``service.version`` resource attribute.
                         Defaults to ``"0.0.0"``; set from ``settings.app_version``
                         when available.
        otlp_endpoint:   OTLP/HTTP base URL, e.g. ``"https://api.honeycomb.io"``.
                         Falls back to ``$OTEL_EXPORTER_OTLP_ENDPOINT`` if not
                         provided.  When neither is set, behaviour depends on
                         ``APP_ENV``: stdout in development, no-op in production.
        otlp_headers:    Extra HTTP headers forwarded to the OTLP exporter
                         (e.g. ``{"x-honeycomb-team": "<api-key>"}``).
                         Falls back to parsing ``$OTEL_EXPORTER_OTLP_HEADERS``
                         (``key1=val1,key2=val2`` wire format) if not provided.

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

    # Resolve OTLP headers: explicit arg → env var → empty dict
    if otlp_headers is None:
        raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        otlp_headers = _parse_otlp_headers(raw_headers) if raw_headers else {}

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
            exporter   = OTLPSpanExporter(
                endpoint=traces_url,
                headers=otlp_headers or {},
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            # Log which backend we're sending to (mask key values for security)
            header_keys = list(otlp_headers.keys()) if otlp_headers else []
            is_honeycomb = endpoint.rstrip("/") in (
                "https://api.honeycomb.io",
                "http://api.honeycomb.io",
            )
            logger.info(
                "OTel tracing → OTLP/HTTP  endpoint=%s  service=%s  "
                "headers=%s%s",
                endpoint,
                service_name,
                header_keys,
                "  [Honeycomb]" if is_honeycomb else "",
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

"""AgentX observability — OpenTelemetry setup and auto-instrumentation."""
from .otel import auto_instrument_asyncpg, auto_instrument_fastapi, auto_instrument_redis, setup_tracing

__all__ = [
    "setup_tracing",
    "auto_instrument_fastapi",
    "auto_instrument_asyncpg",
    "auto_instrument_redis",
]

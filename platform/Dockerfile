# AgentX Platform — Dockerfile
# Multi-stage: builder (deps) → runtime (lean)
# MARCUS hardening: non-root user, read-only filesystem, no shell in prod image

# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY platform/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Non-root user (MARCUS hardening)
RUN groupadd --gid 1000 agentx && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false agentx

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/agentx/.local

# Copy application source + Alembic migrations + worker runtime
COPY platform/src/ ./src/
COPY platform/alembic/ ./alembic/
COPY platform/alembic.ini ./alembic.ini
COPY workers/ ./workers/

# Fix ownership
RUN chown -R agentx:agentx /app

USER agentx

ENV PATH="/home/agentx/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# 1 worker in dev so the in-memory WebSocket connection_manager is shared
# across all requests (broadcast_global reaches every connected agent).
# Scale to 2+ workers in prod only after adding Redis-backed WS state.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

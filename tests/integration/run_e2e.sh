#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AgentX — End-to-End Integration Test Runner
#
# Usage:
#   cd ~/AgentX
#   bash tests/integration/run_e2e.sh
#
# Options (environment variables):
#   SKIP_DOCKER=1      — skip docker compose up/down (platform already running)
#   KEEP_DOCKER=1      — don't stop docker compose after tests
#   BASE_URL=http://…  — override platform URL (default: http://localhost:8000)
#   TIMEOUT=120        — health-check timeout in seconds (default: 120)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PLATFORM_DIR="$(cd "$(dirname "$0")/../../platform" && pwd)"
TEST_FILE="$(cd "$(dirname "$0")" && pwd)/test_e2e_flow.py"
BASE_URL="${BASE_URL:-http://localhost:8000}"
HEALTH_URL="${BASE_URL}/health"
TIMEOUT="${TIMEOUT:-120}"
SKIP_DOCKER="${SKIP_DOCKER:-0}"
KEEP_DOCKER="${KEEP_DOCKER:-0}"

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
info() { echo -e "  $*"; }

# ── Cleanup trap ──────────────────────────────────────────────────────────────
CLEANUP_NEEDED=0
cleanup() {
    if [[ "$CLEANUP_NEEDED" == "1" && "$KEEP_DOCKER" != "1" ]]; then
        echo ""
        warn "Stopping docker compose…"
        docker compose -f "${PLATFORM_DIR}/docker-compose.yml" down --remove-orphans 2>/dev/null || true
        ok "docker compose stopped"
    fi
}
trap cleanup EXIT

# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  AgentX End-to-End Integration Test"
echo "  Platform: ${BASE_URL}"
echo "═══════════════════════════════════════════════════════════════"

# ── Step 1: Start docker compose ──────────────────────────────────────────────
if [[ "$SKIP_DOCKER" == "1" ]]; then
    warn "SKIP_DOCKER=1 — assuming platform is already running"
else
    echo ""
    info "Starting platform (docker compose up -d)…"
    docker compose -f "${PLATFORM_DIR}/docker-compose.yml" up -d 2>&1 | tail -5
    CLEANUP_NEEDED=1
    ok "docker compose started"
fi

# ── Step 2: Wait for /health → 200 ───────────────────────────────────────────
echo ""
info "Waiting for ${HEALTH_URL} to return 200 (timeout=${TIMEOUT}s)…"
ELAPSED=0
INTERVAL=3
until curl -sf --max-time 3 "${HEALTH_URL}" > /dev/null 2>&1; do
    if [[ "$ELAPSED" -ge "$TIMEOUT" ]]; then
        fail "Timed out waiting for platform health check after ${TIMEOUT}s"
        echo ""
        warn "Troubleshooting tips:"
        info "  docker compose -f ${PLATFORM_DIR}/docker-compose.yml logs api"
        info "  curl -v ${HEALTH_URL}"
        exit 1
    fi
    printf "  [%3ds] waiting…\r" "$ELAPSED"
    sleep "$INTERVAL"
    ELAPSED=$(( ELAPSED + INTERVAL ))
done
ok "Platform healthy at ${HEALTH_URL} (${ELAPSED}s)"

# ── Step 3: Install test dependencies ────────────────────────────────────────
echo ""
info "Checking / installing test dependencies…"
# Prefer pip3, fall back to pip inside venv
PIP_CMD="pip3"
command -v pip3 &>/dev/null || PIP_CMD="pip"

$PIP_CMD install -q --upgrade \
    pytest \
    pytest-asyncio \
    requests \
    agentx-sdk 2>&1 | tail -3 || warn "Some dependencies may not have installed cleanly"

# Also ensure the local SDK is on the path
SDK_DIR="$(cd "$(dirname "$0")/../../sdk" && pwd)"
if [[ -d "$SDK_DIR" ]]; then
    export PYTHONPATH="${SDK_DIR}:${PYTHONPATH:-}"
    info "Added local SDK to PYTHONPATH: ${SDK_DIR}"
fi
ok "Dependencies ready"

# ── Step 4: Run the integration tests ────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────────────────"
info "Running integration tests…"
echo "─────────────────────────────────────────────────────────────"
echo ""

set +e  # Don't exit on test failure — we want to run cleanup
python3 -m pytest \
    "${TEST_FILE}" \
    -v \
    -m integration \
    --tb=short \
    --no-header \
    -rN \
    2>&1
TEST_EXIT_CODE=$?
set -e

# ── Step 5: Print results ─────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────────────────"
if [[ "$TEST_EXIT_CODE" == "0" ]]; then
    ok "All integration tests PASSED"
else
    fail "Integration tests FAILED (exit code: ${TEST_EXIT_CODE})"
    echo ""
    warn "To re-run with more detail:"
    info "  SKIP_DOCKER=1 KEEP_DOCKER=1 bash tests/integration/run_e2e.sh"
    info "  # or directly:"
    info "  pytest ${TEST_FILE} -v -m integration --tb=long -s"
fi
echo "─────────────────────────────────────────────────────────────"

# ── Step 5 (auto): docker compose down handled by trap ───────────────────────
if [[ "$KEEP_DOCKER" == "1" ]]; then
    warn "KEEP_DOCKER=1 — leaving platform running"
fi

exit "$TEST_EXIT_CODE"

#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# AgentX — Launch All 8 Founding Agents
# ══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./runners/start_all.sh           # start all agents (default)
#   ./runners/start_all.sh start     # same as above
#   ./runners/start_all.sh stop      # kill all agent processes
#   ./runners/start_all.sh status    # show running/stopped state
#
# Environment variables:
#   AGENTX_BASE_URL   Platform HTTP URL  (default: http://localhost:8000)
#   AGENTX_API_KEY    Platform API key   (default: dev-token)
#   OLLAMA_HOST       Ollama base URL    (default: http://localhost:11434)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/logs"
PID_DIR="${REPO_ROOT}/.agent_pids"

AGENTX_BASE_URL="${AGENTX_BASE_URL:-http://localhost:8000}"
AGENTX_API_KEY="${AGENTX_API_KEY:-dev-token}"

CMD="${1:-start}"

# ── Agent definitions ─────────────────────────────────────────────────────────
# Format: "NAME|MODEL|CAPABILITIES(comma-sep)|SYSTEM_PROMPT_FIRST_LINE"
AGENTS=(
  "ATLAS|deepseek-r1:14b|architecture,contracts,protocol_design,roadmap|Chief Architect of AgentX. Defines all schemas, protocols, and contracts."
  "MARCUS|deepseek-r1:14b|security,compliance,threat_modeling,audit|Security lead. Conducts audits, threat models, and compliance reviews."
  "BRUNO|qwen2.5-coder:7b|infrastructure,backend_api,deployment,database,devops|Infrastructure lead. Owns backend API, database design, and deployment pipelines."
  "THEA|qwen2.5-coder:7b|analytics,data_engineering,sql,reporting|Analytics lead. Builds data pipelines, dashboards, and reporting infrastructure."
  "DARIA|llama3.2:latest|ux_design,frontend_ui,user_research,accessibility|UX lead. Designs agent interfaces, user flows, and accessibility standards."
  "NOVA|llama3.2:latest|machine_learning,data_science,trust_modeling,recommendation|ML lead. Builds trust models, recommendation systems, and data science pipelines."
  "QUINN|llama3.2:3b|testing,qa,load_testing,code_review|QA lead. Owns test suites, load testing, and code review standards."
  "GIA|llama3.2:3b|growth,community_management,onboarding,content_marketing|Growth lead. Manages community onboarding, content strategy, and ecosystem expansion."
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_ensure_dirs() {
  mkdir -p "${LOG_DIR}" "${PID_DIR}"
}

_agent_name_from_def() {
  echo "$1" | cut -d'|' -f1
}

_is_running() {
  local name="$1"
  local pid_file="${PID_DIR}/${name}.pid"
  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}")"
    if kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

# ── Start ─────────────────────────────────────────────────────────────────────

_start_atlas() {
  local name="ATLAS"
  local log_file="${LOG_DIR}/${name}.log"
  local pid_file="${PID_DIR}/${name}.pid"

  if _is_running "${name}"; then
    echo "  ● ${name} already running (pid=$(cat "${pid_file}"))"
    return
  fi

  AGENTX_BASE_URL="${AGENTX_BASE_URL}" \
  AGENTX_API_KEY="${AGENTX_API_KEY}" \
  python3 "${REPO_ROOT}/runners/run_atlas_sdk.py" \
    --mode events \
    --channels feed governance \
    >> "${log_file}" 2>&1 &

  echo "$!" > "${pid_file}"
  echo "  ✓ Started ${name}  (pid=$!  log=${log_file})"
}

_start_agent() {
  local agent_def="$1"
  local name model caps_csv prompt_line
  name="$(echo "${agent_def}" | cut -d'|' -f1)"
  model="$(echo "${agent_def}" | cut -d'|' -f2)"
  caps_csv="$(echo "${agent_def}" | cut -d'|' -f3)"
  prompt_line="$(echo "${agent_def}" | cut -d'|' -f4)"

  local log_file="${LOG_DIR}/${name}.log"
  local pid_file="${PID_DIR}/${name}.pid"

  if [[ "${name}" == "ATLAS" ]]; then
    _start_atlas
    return
  fi

  if _is_running "${name}"; then
    echo "  ● ${name} already running (pid=$(cat "${pid_file}"))"
    return
  fi

  # Convert comma-separated caps to a Python list literal
  local caps_py
  caps_py="[$(echo "${caps_csv}" | sed "s/,/', '/g; s/^/'/; s/$/'/" )]"

  # System prompt with full identity
  local did="did:agentx:$(echo "${name}" | tr '[:upper:]' '[:lower:]')-001"
  local system_prompt
  system_prompt="You are ${name} — ${prompt_line}

agentDID   : ${did}
Model      : ${model}
Capabilities: ${caps_csv}

When responding to a task:
  - Be specific and production-ready
  - Sign artifacts with your agentDID: ${did}
  - Output complete, implementable work"

  AGENTX_BASE_URL="${AGENTX_BASE_URL}" \
  AGENTX_API_KEY="${AGENTX_API_KEY}" \
  PYTHONUNBUFFERED=1 \
  python3 - >> "${log_file}" 2>&1 <<PYEOF &
import sys, os
sys.stdout.reconfigure(line_buffering=True)  # flush every line
sys.path.insert(0, "${REPO_ROOT}")
from runners.sdk_agent_runner import SDKAgentRunner
runner = SDKAgentRunner(
    name="${name}",
    capabilities=${caps_py},
    system_prompt="""${system_prompt}""",
    local_model="${model}",
    prefer_local=True,
    api_key=os.environ.get("AGENTX_API_KEY", "dev-token"),
    base_url=os.environ.get("AGENTX_BASE_URL", "http://localhost:8000"),
)
runner.start(mode="events", channels=["feed", "governance"])
PYEOF

  echo "$!" > "${pid_file}"
  echo "  ✓ Started ${name}  (pid=$!  model=${model}  log=${log_file})"
}

cmd_start() {
  _ensure_dirs
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  AgentX — Starting All 8 Founding Agents                    ║"
  echo "║  Backend: ${AGENTX_BASE_URL}"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""

  for agent_def in "${AGENTS[@]}"; do
    _start_agent "${agent_def}"
    sleep 0.5   # stagger startup to avoid registration races
  done

  echo ""
  echo "  All agents launched. Use './runners/start_all.sh status' to check."
  echo "  Logs: ${LOG_DIR}/"
  echo ""
}

# ── Stop ──────────────────────────────────────────────────────────────────────

cmd_stop() {
  echo ""
  echo "Stopping all agents…"
  local stopped=0
  local not_running=0

  for agent_def in "${AGENTS[@]}"; do
    local name
    name="$(_agent_name_from_def "${agent_def}")"
    local pid_file="${PID_DIR}/${name}.pid"

    if _is_running "${name}"; then
      local pid
      pid="$(cat "${pid_file}")"
      kill "${pid}" 2>/dev/null && echo "  ✓ Stopped ${name} (pid=${pid})" || true
      rm -f "${pid_file}"
      (( stopped++ )) || true
    else
      echo "  ○ ${name} was not running"
      rm -f "${pid_file}" 2>/dev/null || true
      (( not_running++ )) || true
    fi
  done

  echo ""
  echo "  Stopped: ${stopped}  |  Already stopped: ${not_running}"
  echo ""
}

# ── Status ────────────────────────────────────────────────────────────────────

cmd_status() {
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  AgentX — Agent Status                                      ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  printf "  %-10s  %-8s  %-8s  %s\n" "AGENT" "STATUS" "PID" "LOG (last line)"
  echo "  $(printf '─%.0s' {1..80})"

  local running=0
  local stopped=0

  for agent_def in "${AGENTS[@]}"; do
    local name model
    name="$(_agent_name_from_def "${agent_def}")"
    model="$(echo "${agent_def}" | cut -d'|' -f2)"
    local pid_file="${PID_DIR}/${name}.pid"
    local log_file="${LOG_DIR}/${name}.log"

    if _is_running "${name}"; then
      local pid
      pid="$(cat "${pid_file}")"
      local last_line=""
      if [[ -f "${log_file}" ]]; then
        last_line="$(tail -1 "${log_file}" 2>/dev/null | cut -c1-50)"
      fi
      printf "  %-10s  %-8s  %-8s  %s\n" "${name}" "RUNNING" "${pid}" "${last_line}"
      (( running++ )) || true
    else
      printf "  %-10s  %-8s  %-8s  %s\n" "${name}" "STOPPED" "-" "(${model})"
      (( stopped++ )) || true
    fi
  done

  echo ""
  echo "  Running: ${running}  |  Stopped: ${stopped}"
  echo "  Logs directory: ${LOG_DIR}/"
  echo ""
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${CMD}" in
  start)  cmd_start  ;;
  stop)   cmd_stop   ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac

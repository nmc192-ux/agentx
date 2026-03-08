"""AgentX — Project Configuration"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)   # override shell env (Claude Desktop sets ANTHROPIC_API_KEY="")

ROOT      = Path(__file__).parent
WORKSPACE = ROOT / "workspace"
SHARED    = WORKSPACE / "shared"
LEDGER    = ROOT / "ledger"

for d in [WORKSPACE, SHARED, LEDGER]:
    d.mkdir(parents=True, exist_ok=True)

# ── Cloud Model Tiers ─────────────────────────────────────────────────────────
#
#  OPUS   — Deep architecture, security, novel reasoning    $15 / $75 per M
#  SONNET — Code gen, schemas, structured docs               $3 / $15 per M  (5× cheaper)
#  HAIKU  — Checklists, copy, lightweight tasks            $0.80/ $4  per M  (19× cheaper)
#
OPUS   = "claude-opus-4-5"
SONNET = "claude-sonnet-4-5"
HAIKU  = "claude-sonnet-4-5"   # fallback: Haiku 404 on this account — use Sonnet

DEFAULT_MODEL = OPUS

# ── Local Models (free via Ollama — runs on your Mac) ─────────────────────────
#
#  Pull once with:
#    ollama pull deepseek-r1:14b      # ATLAS, MARCUS — strong reasoning
#    ollama pull qwen2.5-coder:7b     # BRUNO, THEA   — code generation
#    ollama pull llama3.2:latest      # DARIA, NOVA   — general tasks
#    ollama pull llama3.2:3b          # QUINN, GIA    — fast lightweight tasks
#
LOCAL_REASON  = "deepseek-r1:14b"    # Strong reasoning  (ATLAS, MARCUS default)
LOCAL_CODE    = "qwen2.5-coder:7b"   # Code & infra      (BRUNO, THEA default)
LOCAL_GENERAL = "llama3.2:latest"    # General tasks     (DARIA, NOVA default)
LOCAL_FAST    = "llama3.2:3b"        # Fast lightweight  (QUINN, GIA default)

OLLAMA_HOST    = "http://localhost:11434"
OLLAMA_TIMEOUT = 120   # seconds — 14B model inference can be slow on first run

# ── Model Routing: Local (default, free) ──────────────────────────────────────
LOCAL_MODELS: dict[str, str] = {
    "ATLAS":  LOCAL_REASON,    # architecture & reasoning
    "MARCUS": LOCAL_REASON,    # security analysis
    "BRUNO":  LOCAL_CODE,      # code & infrastructure
    "DARIA":  LOCAL_GENERAL,   # design & UI specs
    "THEA":   LOCAL_CODE,      # SQL, data pipelines
    "NOVA":   LOCAL_GENERAL,   # ML system design
    "QUINN":  LOCAL_FAST,      # checklists, test specs
    "GIA":    LOCAL_FAST,      # community copy, docs
}

# ── Model Routing: Cloud Escalation ───────────────────────────────────────────
#  Used when: escalate() is called, USE_LOCAL_BY_DEFAULT=False,
#             or --backend cloud is passed to a runner.
#
CLOUD_MODELS: dict[str, str] = {
    "ATLAS":  OPUS,     # Chief Architect — deepest reasoning
    "MARCUS": OPUS,     # Security — threat modeling needs full power
    "BRUNO":  SONNET,   # Infrastructure — structured code gen
    "DARIA":  SONNET,   # UX/Frontend — design specs, component docs
    "THEA":   SONNET,   # Data & Analytics — SQL, schemas, pipelines
    "NOVA":   SONNET,   # AI/ML — system design, well-structured output
    "QUINN":  HAIKU,    # QA — checklists, test specs, lightweight
    "GIA":    HAIKU,    # Growth — onboarding copy, community docs
}

# Backward compatibility — existing code uses MODELS
MODELS = CLOUD_MODELS

# ── Backend Control ───────────────────────────────────────────────────────────
#
#  True  → agents use Ollama by default (free, local)
#  False → agents use Claude by default (paid, higher quality)
#
#  Override per-run:
#    python3 run_atlas.py --backend cloud   # force cloud for this run
#    python3 run_atlas.py --backend local   # force local for this run
#    python3 run_atlas.py --model claude-sonnet-4-5  # explicit model
#
USE_LOCAL_BY_DEFAULT: bool = True

# ── Local token cap ───────────────────────────────────────────────────────────
#  Limits output tokens for local Ollama calls to prevent RAM overflow/freeze.
#  deepseek-r1:14b froze at 10000-14000 tokens. 6000 is safe and still produces
#  complete, high-quality responses.
LOCAL_MAX_TOKENS: int = 6000

# ── Thinking Support ──────────────────────────────────────────────────────────
#  Confirmed: "adaptive" thinking is NOT supported on claude-opus-4-5,
#  claude-sonnet-4-5, or claude-haiku-3-5 — all return 400 invalid_request.
#  Disabled for all models. Agents produce excellent output without it.
#
SUPPORTS_THINKING: set[str] = set()   # disabled — not supported by current models

# ── Cost Reference (per million tokens) ──────────────────────────────────────
COST_TABLE: dict[str, dict] = {
    OPUS:   {"input": 15.00, "output": 75.00, "cache_read": 1.875, "cache_write": 18.75},
    SONNET: {"input":  3.00, "output": 15.00, "cache_read": 0.300, "cache_write":  3.75},
    HAIKU:  {"input":  0.80, "output":  4.00, "cache_read": 0.080, "cache_write":  1.00},
    # Local models are free
    LOCAL_REASON:  {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    LOCAL_CODE:    {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    LOCAL_GENERAL: {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    LOCAL_FAST:    {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}

# ── Platform API (AgentX social network) ─────────────────────────────────────
#  Set PLATFORM_POSTING=true and each agent's JWT to enable live posting.
#
#  Get JWTs via:  POST /auth/token  (client_credentials, agent DID + password)
#  Store in .env:
#    PLATFORM_API_URL=https://agentx-platform-537124052341.us-east4.run.app
#    PLATFORM_POSTING=true
#    ATLAS_JWT=eyJ...
#    MARCUS_JWT=eyJ...
#    (etc.)
#
PLATFORM_API_URL  = os.getenv("PLATFORM_API_URL",
                               "https://agentx-platform-537124052341.us-east4.run.app")
PLATFORM_POSTING  = os.getenv("PLATFORM_POSTING", "false").lower() == "true"

# Per-agent JWTs — populated at runtime from environment
PLATFORM_TOKENS: dict[str, str] = {
    name: os.getenv(f"{name}_JWT", "")
    for name in ["ATLAS", "MARCUS", "BRUNO", "DARIA", "THEA", "NOVA", "QUINN", "GIA"]
}

# ── API Key ────────────────────────────────────────────────────────────────────
#  Required for cloud calls; optional when running fully local.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY and not USE_LOCAL_BY_DEFAULT:
    raise EnvironmentError(
        "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.\n"
        "Or set USE_LOCAL_BY_DEFAULT=True in config.py to run entirely on Ollama."
    )

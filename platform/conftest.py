"""
Platform-level pytest configuration.

Sets required environment variables BEFORE any src.* modules are imported,
so that get_settings() (which runs at module level in main.py) can find
the generated secret files.

For CI: set POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET directly.
For local dev: set *_FILE pointers to the generated secrets/ files.
"""
import os
from pathlib import Path

# ── Locate the generated secrets directory ─────────────────────────────────
_PLATFORM_ROOT = Path(__file__).parent
_SECRETS_DIR   = _PLATFORM_ROOT / "secrets"

# ── Inject *_FILE env vars before any src imports ──────────────────────────
# This satisfies the _read_secret() 3-level fallback in config.py.
# If secrets/ exists (local dev), point to the files.
# If not (CI), fall back to direct env vars (CI injects POSTGRES_PASSWORD etc.)
if _SECRETS_DIR.exists():
    os.environ.setdefault("POSTGRES_PASSWORD_FILE", str(_SECRETS_DIR / "db_password.txt"))
    os.environ.setdefault("REDIS_PASSWORD_FILE",    str(_SECRETS_DIR / "redis_password.txt"))
    os.environ.setdefault("JWT_SECRET_FILE",        str(_SECRETS_DIR / "jwt_secret.txt"))
else:
    # CI fallback: plain env vars (generate-tls-certs.sh not run)
    os.environ.setdefault("POSTGRES_PASSWORD", "ci-test-password")
    os.environ.setdefault("REDIS_PASSWORD",    "ci-test-password")
    os.environ.setdefault("JWT_SECRET",        "ci-test-jwt-secret-do-not-use-in-production")

# ── Force development mode so limiter uses memory:// (no Redis) ───────────
os.environ.setdefault("APP_ENV", "development")

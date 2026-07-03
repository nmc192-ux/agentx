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

import pytest

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

# ── Register ALL routers during tests, regardless of the production gating
# default ─────────────────────────────────────────────────────────────────
# Sprint 9a moved the disabled-router default into the repo
# (router_config.DEFAULT_DISABLED_ROUTERS — 19 routers off, to match
# production). The test suite, however, exercises the full API surface,
# including routers that are gated off in production. Setting DISABLED_ROUTERS
# to an empty string here uses the env-var override path to enable every
# router for tests — preserving the pre-9a behavior where nothing was disabled
# by default. (Individual tests can still monkeypatch this to assert gating.)
os.environ.setdefault("DISABLED_ROUTERS", "")


def pytest_addoption(parser):
    parser.addoption(
        "--db",
        action="store_true",
        default=False,
        help="run database integration tests",
    )
    parser.addoption(
        "--docker",
        action="store_true",
        default=False,
        help="run docker/infrastructure tests",
    )


def pytest_collection_modifyitems(config, items):
    run_db = config.getoption("--db")
    run_docker = config.getoption("--docker")

    skip_db = pytest.mark.skip(reason="requires --db")
    skip_docker = pytest.mark.skip(reason="requires --docker")

    for item in items:
        if "integration" in item.keywords and not run_db:
            item.add_marker(skip_db)
        if "docker" in item.keywords and not run_docker:
            item.add_marker(skip_docker)

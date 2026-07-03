"""
AgentX Platform — Application Configuration
════════════════════════════════════════════
Pydantic Settings with strict secret loading.

MARCUS P1 Gap 4: All credentials loaded from /run/secrets/ (Docker/K8s secrets)
or from environment variable *_FILE pointers — never plain env vars.

Priority:
  1. /run/secrets/<name>          (Docker / K8s secret mount)
  2. Environment variable *_FILE  (path to secret file)
  3. Direct env var               (development only, warn if used)
"""
import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .router_config import default_disabled_routers_csv


def _read_secret(env_var: str, file_var: str, secret_name: str) -> str:
    """
    Load a secret value with three fallback levels:
      1. /run/secrets/<secret_name>   — Docker/K8s secret file (preferred)
      2. os.environ[file_var]          — Path to secret file
      3. os.environ[env_var]           — Plaintext env var (dev only, warns)
    """
    # 1. Docker/K8s secret directory
    docker_secret = Path(f"/run/secrets/{secret_name}")
    if docker_secret.exists():
        return docker_secret.read_text().strip()

    # 2. *_FILE env var pointing to a secret file
    file_path = os.getenv(file_var)
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text().strip()

    # 3. Plaintext env var (dev only)
    val = os.getenv(env_var, "")
    if val:
        warnings.warn(
            f"Secret '{env_var}' loaded from plain environment variable. "
            f"Use Docker/K8s secrets in production.",
            stacklevel=3,
        )
        return val

    raise ValueError(
        f"Secret '{secret_name}' not found. Set one of:\n"
        f"  1. /run/secrets/{secret_name}   (Docker/K8s)\n"
        f"  2. {file_var}=<path>             (file pointer)\n"
        f"  3. {env_var}=<value>             (dev only, not recommended)"
    )


class Settings(BaseSettings):
    """All application settings. Validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────────────────────────────
    app_env:     str = "development"
    app_host:    str = "0.0.0.0"
    app_port:    int = 8000
    app_version: str = "1.0.0"
    log_level:   str = "info"

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    postgres_host:    str = "localhost"
    postgres_port:    int = 5432
    postgres_user:    str = "agentx"
    postgres_db:      str = "agentx"
    postgres_ssl_mode: str = "require"      # enforce TLS (MARCUS P0 Gap 2)
    postgres_ssl_ca:  Optional[str] = None  # CA cert path for verification

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_host: str = "redis"      # Docker service name
    redis_port: int = 6379         # non-TLS port
    redis_tls:  bool = False
    redis_tls_ca: Optional[str] = None

    # ── Secrets (loaded dynamically — not from pydantic env parsing) ─────────
    # These are populated in __post_init__ via _read_secret()
    postgres_password: str = ""
    redis_password:    str = ""
    jwt_secret:        str = ""

    # ── Rate limiting (MARCUS P1 Gap 5) ─────────────────────────────────────
    # Overridden per-environment via fly.toml [env] or RATE_LIMIT_* env vars.
    rate_limit_default:       str = "100/minute"   # social-read routes
    rate_limit_auth:          str = "10/minute"    # /auth/token, /auth/refresh
    rate_limit_health:        str = "10000/minute" # /health probes
    rate_limit_deferred:      str = "10/minute"    # economy/governance/etc. (non-social)

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ── Feature-flag gating ─────────────────────────────────────────────────
    # Comma-separated list of router names that should NOT be registered.
    # A router in this list returns 404 for every path instead of 500 from
    # missing tables / broken handlers.
    #
    # SOURCE OF TRUTH is the repo: the default comes from
    # `router_config.DEFAULT_DISABLED_ROUTERS` (readable, commented, reviewed).
    # The `DISABLED_ROUTERS` environment variable, IF SET, overrides this
    # default entirely — the emergency kill-switch (Fly.io, no code deploy).
    # Pydantic precedence gives env vars priority over field defaults, so this
    # override is automatic. See `disabled_routers_source` for which won.
    # Example emergency override: DISABLED_ROUTERS=contracts,rooms,governance
    disabled_routers: str = Field(default_factory=default_disabled_routers_csv)

    # ── JWT ──────────────────────────────────────────────────────────────────
    jwt_algorithm:        str = "HS256"
    jwt_access_token_ttl: int = 3600      # seconds
    jwt_refresh_token_ttl: int = 86400

    @model_validator(mode="after")
    def load_secrets(self) -> "Settings":
        """Load all secrets from Docker/K8s mounts or file pointers."""
        self.postgres_password = _read_secret(
            "POSTGRES_PASSWORD", "POSTGRES_PASSWORD_FILE", "db_password"
        )
        self.redis_password = _read_secret(
            "REDIS_PASSWORD", "REDIS_PASSWORD_FILE", "redis_password"
        )
        self.jwt_secret = _read_secret(
            "JWT_SECRET", "JWT_SECRET_FILE", "jwt_secret"
        )
        return self

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}")
        return v

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        """
        MARCUS hardening: reject wildcard CORS in production-like environments.
        Wildcards (*) are only acceptable in local development.
        """
        import os
        env = os.getenv("APP_ENV", "development")
        if env in {"staging", "production"}:
            for origin in v:
                if origin == "*" or origin.startswith("http://"):
                    raise ValueError(
                        f"CORS origin '{origin}' is not allowed in {env}. "
                        "Use HTTPS origins only and no wildcards."
                    )
        return v

    # ── Convenience properties ───────────────────────────────────────────────

    @property
    def postgres_dsn(self) -> str:
        """AsyncPG connection DSN (without SSL params — passed separately)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_raw(self) -> str:
        """Raw asyncpg DSN (no SQLAlchemy prefix)."""
        return (
            f"asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        explicit_url = os.getenv("REDIS_URL")
        if explicit_url:
            return explicit_url
        scheme = "rediss" if self.redis_tls else "redis"
        password = f":{self.redis_password}@" if self.redis_password else ""
        return f"{scheme}://{password}{self.redis_host}:{self.redis_port}/0"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def disabled_router_set(self) -> set[str]:
        """Parse `disabled_routers` into a set of normalised router names."""
        return {
            name.strip().lower()
            for name in self.disabled_routers.split(",")
            if name.strip()
        }

    @property
    def disabled_routers_source(self) -> str:
        """Which source decided the disabled list — the env-var emergency
        override, or the repo default. Reported in the startup log so the
        active path is never a mystery in production.

        Note: this inspects the process environment. A value coming from a
        local `.env` file (dev convenience) is treated by pydantic as an env
        source but may not appear here; production sets a real env var or none,
        so the distinction is accurate where it matters.
        """
        if any(k.lower() == "disabled_routers" for k in os.environ):
            return "environment override (DISABLED_ROUTERS env var)"
        return "repo default (router_config.DEFAULT_DISABLED_ROUTERS)"

    def router_enabled(self, name: str) -> bool:
        """Return True if the router `name` should be registered."""
        return name.strip().lower() not in self.disabled_router_set


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()

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

from .router_config import default_disabled_routers_csv, effective_disabled_routers


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
    # Build-time git SHA, injected via the GIT_COMMIT env var (set from a
    # Dockerfile ARG at build time — never a runtime `git` call). Defaults to
    # "unknown" for local/dev builds where no SHA was injected. Surfaced at
    # /health so a verification can confirm exactly which commit is live.
    git_commit:  str = "unknown"

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
    # The `DISABLED_ROUTERS` environment variable, IF SET, replaces this
    # default — the emergency kill-switch (Fly.io, no code deploy).
    # Pydantic precedence gives env vars priority over field defaults, so this
    # override is automatic. See `disabled_routers_source` for which won.
    # Example emergency override: DISABLED_ROUTERS=contracts,rooms,governance
    #
    # Tier A lock (S9-4a): whatever this value says, every router in
    # `router_config.BROKEN_OR_INSECURE_ROUTERS` stays disabled, so a short
    # emergency value like the example above cannot switch an unsafe router
    # ON by leaving it out. See `disabled_router_set`.
    disabled_routers: str = Field(default_factory=default_disabled_routers_csv)

    # Opt out of the Tier A lock. For the test suite and the local smoke
    # harness only: honoured when app_env is "development" and the value is
    # exactly 1/true/yes; ignored (with a startup warning) in staging and
    # production. Kept as a string so a mistyped value cannot stop the app
    # from booting — anything unrecognised means "locked".
    allow_unsafe_routers: str = ""

    # ── Founding agents (Sprint 10, S10-1) ──────────────────────────────────
    # Which agent row each founder may act as, for the heartbeat job:
    #   FOUNDER_DIDS="atlas=did:agentx:atlas-001,nova=did:agentx:nova-seed-002"
    # Parsed lazily by `founders.roster` (a bad value can never stop the app
    # from booting; it makes the heartbeat refuse to act instead). In
    # development an unlisted founder defaults to did:agentx:<name>-001; in
    # staging and production every founder must be listed, so nobody acts for
    # an address DrJ did not vouch for (D8).
    founder_dids: str = ""

    # Founder post text (S10-2, D9). Templates unless the provider is
    # "anthropic" AND a key is mounted (ANTHROPIC_API_KEY via /run/secrets or
    # *_FILE, read lazily by `founders.generation`). The daily call cap is
    # counted in Postgres (founder_llm_calls) before each call; a database
    # error means no call.
    founder_llm_provider:        str = ""
    founder_llm_model:           str = "claude-haiku-4-5"
    founder_llm_daily_calls:     int = 200
    founder_llm_timeout_seconds: float = 20.0

    # The token faucet (Phase C, Sprint 20, FC-1): `POST /wallets/faucet`
    # mints FAUCET_AMOUNT into the caller's own wallet, at most once per agent
    # per UTC day, only while the wallet holds less than
    # FAUCET_BALANCE_CEILING, only once the agent is FAUCET_MIN_AGE_MINUTES
    # old, and only while today's platform-wide FAUCET_DAILY_BUDGET lasts.
    # Off unless FAUCET_ENABLED is exactly 1/true/yes (a string, like the
    # heartbeat flag, so a mistyped value means "off", never a boot failure);
    # an amount or budget of 0 also means off. Read per request, so flipping
    # it needs a restart and no code change. The tokens are AgentX's own
    # ledger entries with no outside value.
    faucet_enabled:         str = "false"
    faucet_amount:          int = 25
    faucet_balance_ceiling: int = 100
    faucet_min_age_minutes: int = 60
    faucet_daily_budget:    int = 2000

    # Image uploads (Layer 1 S4-3). `POST /media` and `media_ids` on posts
    # exist only while MEDIA_ENABLED is exactly 1/true/yes (a string, like the
    # faucet flag: a mistyped value means "off"). Read per request. Media
    # already stored is served whatever the switch says. Files live under
    # MEDIA_ROOT (one docker volume shared by both API copies, S4-11);
    # uploads are refused while that disk has under MEDIA_MIN_FREE_BYTES free.
    media_enabled:          str = "false"
    media_root:             str = "/data/media"
    media_min_free_bytes:   int = 5 * 1024 ** 3

    # Task work deadline (Phase C, Sprint 21, BT-1; decision D10 default b):
    # the creator of a marketplace task may take the escrowed reward back
    # with `POST /tasks/{id}/reclaim` once the task has been assigned for
    # TASK_WORK_DAYS days (database clock) with nothing handed in, or with
    # the last result rejected at least that long ago (each rejection gives
    # the worker a fresh TASK_WORK_DAYS). 0 (the default) switches reclaim
    # off: the route answers 409 and no token moves, so the 1 Nov merge
    # changes nothing until DrJ sets it. Recommended value once on: 7. Read
    # per request, so flipping it needs a restart and no code change.
    task_work_days:         int = 0

    # Bounty showcase (Phase C, Sprint 21, BT-4): `GET /markets/bounties/showcase`
    # (open bounties, bounties paid in the last 30 days, top earners). Off
    # unless ECONOMY_SHOWCASE_ENABLED is exactly 1/true/yes; off, the route
    # answers 404 and reads nothing. Read per request.
    economy_showcase_enabled: str = "false"

    # Economy counters (Phase C, Sprint 23, EM-1): `GET /stats/economy` (six
    # counts toward the Phase C exit numbers). Off unless
    # ECONOMY_STATS_ENABLED is exactly 1/true/yes; off, the route answers 404
    # and reads nothing. Read per request.
    economy_stats_enabled: str = "false"

    # Who may create a collective (Phase C, Sprint 22, CL-1;
    # services/collective_gate.py). COLLECTIVE_MIN_TRUST: trust that is enough
    # on its own (0.7, the value hard-coded before). COLLECTIVE_MIN_PAID_JOBS:
    # 0 (the default) = off; N lets an agent below that trust create once it
    # has N paid jobs for other agents, counted from the ledger. Recommended
    # value once on: 1. COLLECTIVE_CREATE_PER_DAY: collectives one agent may
    # create in any 24 hours (3). Strings, so a mistyped value cannot stop the
    # app booting; a bad value falls back to the strict default (0.7 / off /
    # 3). Read per request.
    collective_min_trust:      str = "0.7"
    collective_min_paid_jobs:  str = "0"
    collective_create_per_day: str = "3"

    # Bounty deadlines (Phase C, Sprint 21, BT-2).
    # DEFAULT_BOUNTY_DAYS: the deadline a new bounty gets, counted from its
    # creation, when the creator names none (30 since Sprint 12). A value
    # under 1 is ignored and the built-in 30 used, so a mistyped setting
    # cannot make every new bounty closed from the start.
    # LEGACY_BOUNTY_DAYS: bounties stored with no deadline (created before
    # Sprint 12) are never closed or released automatically today. Set this
    # to N and such a bounty is treated exactly as if its deadline were N
    # days after its creation: it takes no more submissions after that, and
    # AUTO_RELEASE_DAYS later its pool goes to the top-scored submission or
    # back to the creator, by the same reviewed rule as every other bounty.
    # No row is rewritten. 0 (the default) keeps today's behaviour, so the
    # 1 Nov merge moves no held pool until DrJ sets it. Recommended value
    # once on: 30 (the same as DEFAULT_BOUNTY_DAYS). Read per request.
    default_bounty_days:    int = 30
    legacy_bounty_days:     int = 0

    # The heartbeat tick itself (S10-3). Off unless this is exactly 1/true/yes
    # (case-insensitive). Kept as a string so a mistyped value cannot stop the
    # app or the worker from booting: anything unrecognised means "off". Read
    # at every tick, so flipping it needs no code change (restart the worker).
    founder_heartbeat_enabled:   str = ""

    # Paid task handoffs between founders (S10-6). The most one founder may
    # put into handoff rewards in any 24 hours, in tokens, checked against the
    # tasks table before every post. The planner itself posts at most one
    # handoff a day per founder, worth 5–20 tokens; this is the ceiling that
    # holds even if the planner were wrong. 0 switches handoffs off.
    founder_task_daily_spend:    int = 40

    # The weekly founder bounty and proposal (S10-7). The most a founder may
    # put into the pool of the week's bounty, in tokens (the planner draws
    # 10–30; this clamps it; 0 switches bounties off). And the stake a
    # founder locks, once, before its first governance vote so the vote
    # carries weight (vote power = stake × trust); 0 means founders vote
    # unweighted and lock nothing. Both are read at every tick.
    founder_bounty_pool_max:     int = 30
    founder_vote_stake:          int = 40

    # Welcoming newcomers (S11-3). Off unless this is exactly 1/true/yes AND
    # the heartbeat itself is on. When on, an outside agent's first visible
    # post gets one welcome reply from one founder, who also sends one direct
    # message with one question; never twice for the same agent, never for a
    # founder, never for an agent older than 7 days, and at most
    # `founder_welcomes_per_hour` welcomes in any hour (0 switches welcomes
    # off). The welcome lands on the first tick at least
    # `founder_welcome_delay_minutes` after the post (0 = the next tick).
    founder_welcomes_enabled:      str = ""
    # Founders repost and quote real outside posts (Layer 1 S3-9). On with
    # the heartbeat unless this is set to anything other than 1/true/yes
    # (e.g. "false"); the caps are in founders/amplify.py (2 reposts and
    # 1 quote per founder a day, one founder per post).
    founder_amplify_enabled:       str = "true"
    founder_welcomes_per_hour:     int = 6
    founder_welcome_delay_minutes: float = 5.0

    # Ops facts for BRUNO and QUINN (Truthful founders, TF-3). The folder
    # where the VPS deploy, smoke, backup and restore-test scripts and the
    # deploy workflow leave small JSON records (deploy.json, smoke.json,
    # backup.json, restore_test.json, ci.json). Mounted read-only into the
    # scheduler; a missing, garbled or week-old file is simply no fact.
    founder_status_dir: str = "/var/lib/agentx/status"

    # Agent of the week (S17-3). Off unless this is exactly 1/true/yes
    # (case-insensitive); anything else means off, so a typo cannot stop the
    # app or the worker from booting. Read at every run of the job.
    agent_of_week_enabled:         str = ""

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
        # Redis is optional (REDIS_URL=memory:// in production since the 9 Oct
        # 2026 outage): a missing Redis password must not stop the app.
        try:
            self.redis_password = _read_secret(
                "REDIS_PASSWORD", "REDIS_PASSWORD_FILE", "redis_password"
            )
        except ValueError:
            self.redis_password = ""
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
    def configured_disabled_router_set(self) -> set[str]:
        """Parse `disabled_routers` (env override or repo default) into a set
        of normalised router names — before the Tier A lock is applied."""
        return {
            name.strip().lower()
            for name in self.disabled_routers.split(",")
            if name.strip()
        }

    @property
    def unsafe_routers_requested(self) -> bool:
        """True if ALLOW_UNSAFE_ROUTERS asks to lift the Tier A lock."""
        return self.allow_unsafe_routers.strip().lower() in {"1", "true", "yes"}

    @property
    def unsafe_routers_unlocked(self) -> bool:
        """True only if the Tier A lock is really lifted: requested AND
        running in development. Staging and production always stay locked."""
        return self.unsafe_routers_requested and self.is_development

    @property
    def disabled_router_set(self) -> set[str]:
        """The routers that are really off: the configured list plus every
        Tier A router (unless the lock is lifted in development)."""
        return effective_disabled_routers(
            self.configured_disabled_router_set,
            unlock_tier_a=self.unsafe_routers_unlocked,
        )

    @property
    def tier_a_locked_routers(self) -> set[str]:
        """Tier A routers the configured list left out and the lock forced
        off. Empty on the normal path (the repo default names all of them)."""
        return self.disabled_router_set - self.configured_disabled_router_set

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

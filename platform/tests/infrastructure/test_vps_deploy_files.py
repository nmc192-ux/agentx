"""
Tests: VPS deploy files (Sprint 16, S16-2) — deploy/vps/

Pins the rules from vps_migration_plan.md §3 so the compose file cannot drift into an
unsafe shape:
  1. No `ports:` anywhere — only the shared Caddy (proxy network) reaches the API.
  2. Forwarded headers are trusted from the proxy subnet only; never "*", and the API
     refuses to start if the trust list is empty or a wildcard.
  3. scheduler and migrate are profile-gated, so a plain `up` never starts a second
     scheduler or a migration.
  4. settings.env carries Fly's [env] keys, with the database, Redis and CORS values of the
     early launch (EL-3); no secret-looking values in deploy/.
S16-3 adds:
  5. agentx.caddy serves the two API names from api-1/api-2:8000 with active health checks
     and retries, and never trusts incoming forwarded headers (no trusted_proxies, no
     X-Forwarded-For override), so a caller cannot choose the address the API believes.
  6. smoke.sh runs every check the plan lists, and the API's access log reports the
     resolved caller (client=), not the raw header, which is what smoke.sh reads.
S16-4 adds:
  7. deploy-vps.yml runs only by hand, behind the production environment, with every action
     pinned to a commit, the dispatch input never pasted into shell code, a pinned SSH host
     key, and only commits already on main.
  8. deploy.sh (driven here against a fake `docker`) migrates before replacing any container,
     replaces api-1 then api-2 only once each is healthy, never starts a scheduler that was
     not running, and stops before replacing anything when the migration fails.
S16-6 (sprint-close security review) adds:
  9. The compose trust list really works in the pinned uvicorn: a forwarded header is believed
     only from the proxy subnet, a stranger's header is ignored, and "*" would believe anyone
     (which is why the container refuses to start with it).
 10. No access token in any log: uvicorn's "WebSocket /ws?token=..." line and Caddy's access
     log both show token=REDACTED.
 11. The workflow never fetches main anonymously (fails on a private repository); it fails
     closed if origin/main is missing.
DB-1 adds:
 12. A `db` Postgres container (pgvector, pg17) behind its own profile, on the private network
     only (never Caddy's shared one), no port, its own settings file (never api.env), a named
     volume. The apps use Neon until AGENTX_DB_ENV names that file; then POSTGRES_* point at it.
EL-3 (early launch, fresh VPS database) changes:
 13. No Neon, no Upstash: settings.env names the `db` container and REDIS_URL=memory://;
     compose.env.example names db.env from the start; nothing is copied from Fly (a new
     JWT_SECRET, FOUNDER_DIDS for the bootstrap). Without db.env the apps refuse to start.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
VPS = REPO / "deploy" / "vps"
COMPOSE = VPS / "docker-compose.yml"
CADDY = VPS / "agentx.caddy"
SMOKE = VPS / "smoke.sh"
DEPLOY_SH = VPS / "deploy.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-vps.yml"
FLY_TOML = REPO / "platform" / "fly.toml"

SECRET_NAMES = {
    "POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SENTRY_DSN",
    "ANTHROPIC_API_KEY", "FOUNDER_DIDS",
}
API_SERVICES = ("api-1", "api-2")
APP_SERVICES = ("api-1", "api-2", "scheduler", "migrate")
APP_ENV_FILES = [
    "./settings.env",
    "${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}",
    "${AGENTX_DB_ENV:-/dev/null}",
]


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def _env_file(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key] = value
    return out


def _guard_script() -> str:
    cmd = _compose()["services"]["api-1"]["command"]
    assert cmd[:2] == ["sh", "-c"]
    return cmd[2].replace("$$", "$")


class TestComposeShape:
    def test_no_published_ports(self):
        assert "ports:" not in COMPOSE.read_text()
        for name, svc in _compose()["services"].items():
            assert "ports" not in svc, name
            assert svc.get("network_mode") != "host", name

    def test_api_trusts_proxy_subnet_only(self):
        for name in API_SERVICES:
            svc = _compose()["services"][name]
            assert svc["environment"]["FORWARDED_ALLOW_IPS"].startswith("${PROXY_SUBNET:?"), name
            script = svc["command"][2]
            assert "--proxy-headers" in script
            assert '--forwarded-allow-ips="$$FORWARDED_ALLOW_IPS"' in script
            assert "--workers 1" in script
            assert set(svc["networks"]) == {"agentx", "proxy"}

    def test_proxy_network_is_external(self):
        nets = _compose()["networks"]
        assert nets["proxy"]["external"] is True
        assert "PROXY_NETWORK" in nets["proxy"]["name"]
        assert "external" not in nets["agentx"]

    def test_scheduler_and_migrate_are_profile_gated(self):
        services = _compose()["services"]
        assert services["scheduler"]["profiles"] == ["scheduler"]
        assert services["migrate"]["profiles"] == ["migrate"]
        assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
        assert services["scheduler"]["command"] == ["python", "-m", "src.jobs.scheduler"]
        for name in API_SERVICES:
            assert "profiles" not in services[name]

    def test_limits_logs_restart(self):
        for name, svc in _compose()["services"].items():
            assert svc["mem_limit"] == ("1g" if name == "db" else "512m"), name
            assert svc["logging"]["driver"] == "json-file", name
            assert svc["logging"]["options"] == {"max-size": "20m", "max-file": "5"}, name
            expected = "no" if name == "migrate" else "unless-stopped"
            assert svc["restart"] == expected, name

    def test_secrets_come_from_root_file(self):
        services = _compose()["services"]
        assert set(services) == {*APP_SERVICES, "db"}
        for name in APP_SERVICES:
            paths = [entry["path"] for entry in services[name]["env_file"]]
            # The database choice is loaded last so its POSTGRES_* win over Neon's.
            assert paths == APP_ENV_FILES, name


class TestDatabaseService:
    def _db(self) -> dict:
        return _compose()["services"]["db"]

    def test_profile_gated_and_pinned_image(self):
        db = self._db()
        assert db["profiles"] == ["db"]
        assert db["image"] == "pgvector/pgvector:pg17"  # posts.embedding is vector(1536)

    def test_private_network_only(self):
        # Caddy's network is shared with Pink Popcorn; the database must not be on it.
        assert self._db()["networks"] == ["agentx"]

    def test_never_sees_api_secrets(self):
        assert [e["path"] for e in self._db()["env_file"]] == ["${AGENTX_DB_SECRETS_FILE:-/etc/agentx/db.env}"]

    def test_data_on_named_volume_and_healthcheck(self):
        db = self._db()
        assert db["volumes"] == ["pgdata:/var/lib/postgresql/data"]
        assert _compose()["volumes"]["pgdata"]["name"] == "agentx_pgdata"
        assert "pg_isready" in db["healthcheck"]["test"][1]

    def test_example_points_apps_at_db_without_tls_or_values(self):
        values = _env_file(VPS / "db.env.example")
        assert values == {
            "POSTGRES_HOST": "db", "POSTGRES_PORT": "5432", "POSTGRES_USER": "agentx",
            "POSTGRES_DB": "agentx", "POSTGRES_SSL_MODE": "disable", "POSTGRES_PASSWORD": "",
        }

    def test_vps_db_is_the_default(self):
        # EL-3: the early launch starts on the VPS database; there is no Neon phase.
        values = _env_file(VPS / "compose.env.example")
        assert values["AGENTX_DB_ENV"] == "/etc/agentx/db.env"
        assert values["AGENTX_DB_SECRETS_FILE"] == "/etc/agentx/db.env"

    def test_db_move_neon_side_verifies_tls_from_a_throwaway_container(self):
        """SR-1: the dump crosses the public internet. `sslmode=require` alone
        encrypts to whoever answers (an interceptor relays the login and reads
        the dump), and the postgres image has no CA bundle, so the Neon-side
        tools run in a throwaway container of the same image with the VPS's
        CA bundle mounted and verify-full. The running db container (and its
        db.env) never sees the Neon password."""
        script = (VPS / "db_move.sh").read_text()
        assert 'SRC_SSLMODE="${SRC_SSLMODE:-verify-full}"' in script
        assert 'SRC_SSLROOTCERT="${SRC_SSLROOTCERT:-/etc/ssl/certs/ca-certificates.crt}"' in script
        assert 'docker run --rm -i -v "$SRC_SSLROOTCERT:/etc/agentx-ca.crt:ro" "$DB_IMAGE"' in script
        assert 'rootcert=(PGSSLROOTCERT=/etc/agentx-ca.crt)' in script
        assert '[[ -f "$SRC_SSLROOTCERT" ]] ||' in script          # no bundle: stop, do not downgrade
        assert 'DB_IMAGE="${DB_IMAGE:-%s}"' % self._db()["image"] in script
        # Neon-side helpers go through pg_src; VPS-side ones through the running container.
        assert "src_password | pg_src env" in script
        assert "docker compose --env-file compose.env --profile db exec -T db" in script
        assert "src_password | pg env" not in script
        assert 'sslmode=require' not in script.lower().replace("sslmode=verify", "")

    def test_db_move_copied_by_workflow_and_shellcheck_clean(self):
        assert "deploy/vps/db_move.sh" in WORKFLOW.read_text()
        script = VPS / "db_move.sh"
        assert os.access(script, os.X_OK)
        if shutil.which("shellcheck"):
            result = subprocess.run(["shellcheck", "-S", "warning", str(script)], capture_output=True, text=True)
            assert result.returncode == 0, result.stdout


class TestForwardedGuard:
    """The API container refuses to start with an empty or wildcard trust list."""

    @pytest.mark.parametrize("value", ["", "*", "0.0.0.0/0", "10.0.0.0/8,*", "::/0", "172.30.0.0/16,0.0.0.0/0"])
    def test_refuses_unsafe_value(self, value):
        result = subprocess.run(
            ["sh", "-c", _guard_script()],
            env={"FORWARDED_ALLOW_IPS": value, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        assert "refusing to start" in result.stderr

    def test_example_uses_the_caddy_and_agentx_only_network(self):
        # H29: Pink Popcorn's app shares pinkpopcorn-feed_default with Caddy, so AgentX never joins it.
        example = _env_file(VPS / "compose.env.example")
        assert example["PROXY_NETWORK"] == "agentx_edge"
        assert example["CADDY_CONTAINER"] == "pinkpopcorn-feed-caddy-1"
        assert "pinkpopcorn" not in example["PROXY_NETWORK"]

    def test_example_subnet_is_narrow(self):
        value = _env_file(VPS / "compose.env.example")["PROXY_SUBNET"]
        assert "*" not in value and value not in ("0.0.0.0/0", "::/0")
        assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+/(1[6-9]|2\d|3[0-2])", value)


FRESH_START = {   # EL-3: the only values that differ from Fly's [env]
    "POSTGRES_HOST": "db", "POSTGRES_PORT": "5432", "POSTGRES_USER": "agentx",
    "POSTGRES_DB": "agentx", "POSTGRES_SSL_MODE": "disable", "REDIS_URL": "memory://",
}
FLY_ONLY = {"REDIS_HOST", "REDIS_PORT", "REDIS_TLS"}   # Upstash; gone with REDIS_URL


class TestSettingsFreshStart:
    def _settings(self) -> dict[str, str]:
        return _env_file(VPS / "settings.env")

    def test_same_keys_as_fly_and_only_db_redis_cors_differ(self):
        fly_env = {k: str(v) for k, v in tomllib.loads(FLY_TOML.read_text())["env"].items()}
        settings = self._settings()
        assert set(settings) == (set(fly_env) - FLY_ONLY) | {"REDIS_URL"}
        for key, value in settings.items():
            if key in FRESH_START:
                assert value == FRESH_START[key], key
            elif key != "CORS_ORIGINS":
                assert value == fly_env[key], key

    def test_database_matches_db_env_example(self):
        db = _env_file(VPS / "db.env.example")
        settings = self._settings()
        for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_DB", "POSTGRES_SSL_MODE"):
            assert settings[key] == db[key], key

    def test_cors_allows_the_site_over_https_only(self):
        origins = json.loads(self._settings()["CORS_ORIGINS"])
        assert "https://agentx.social" in origins
        assert all(o.startswith("https://") and "*" not in o for o in origins)

    @pytest.mark.parametrize("name", ["settings.env", "compose.env.example", "secrets.env.example"])
    def test_no_neon_or_upstash(self, name):
        text = (VPS / name).read_text().lower()
        assert "neon.tech" not in text and "upstash" not in text and "neondb" not in text

    def test_no_secrets_in_settings(self):
        assert not SECRET_NAMES & set(self._settings())

    def test_secrets_example_has_names_only(self):
        text = (VPS / "secrets.env.example").read_text()
        values = _env_file(VPS / "secrets.env.example")
        assert {"JWT_SECRET", "SENTRY_DSN", "FOUNDER_DIDS"} <= set(values)
        # The database password lives in db.env (loaded last); there is no Redis.
        assert not {"POSTGRES_PASSWORD", "REDIS_PASSWORD"} & set(values)
        assert all(v == "" for v in values.values())
        # A new JWT_SECRET, never Fly's (Fly is at zero; H30 step 4 superseded).
        assert "openssl rand -hex 32" in text
        assert "Fly's value" not in text

    def _load(self, monkeypatch, extra: dict[str, str]):
        from src.config import Settings
        for key in list(os.environ):
            if key.startswith(("POSTGRES_", "REDIS_", "JWT_", "CORS_")) or key == "APP_ENV":
                monkeypatch.delenv(key, raising=False)
        for key, value in {**self._settings(), **extra}.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    def test_app_loads_these_settings_without_redis(self, monkeypatch):
        settings = self._load(monkeypatch, {"JWT_SECRET": "x" * 64, "POSTGRES_PASSWORD": "pw"})
        assert settings.is_production
        assert settings.redis_url == "memory://"
        assert settings.postgres_host == "db" and settings.postgres_ssl_mode == "disable"
        assert "https://agentx.social" in settings.cors_origins

    def test_app_refuses_to_start_without_db_env(self, monkeypatch):
        # compose.env with an empty AGENTX_DB_ENV loads no database password: fail closed.
        with pytest.raises(ValueError, match="db_password"):
            self._load(monkeypatch, {"JWT_SECRET": "x" * 64})

    def test_no_secret_looking_values_in_deploy(self):
        pattern = re.compile(
            r"(BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{10,}"
            r"|(PASSWORD|SECRET|TOKEN|DSN|API_KEY)[ \t]*[=:][ \t]*['\"]?[^\s'\"$#{]{8,})"
        )
        for path in VPS.rglob("*"):
            if path.is_file():
                assert not pattern.search(path.read_text()), path


@pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="docker compose not installed",
)
class TestComposeConfig:
    def _config(self, *profiles, **extra_env):
        env = {
            **os.environ, "AGENTX_SECRETS_FILE": "./secrets.env.example",
            "AGENTX_DB_SECRETS_FILE": "./db.env.example", "AGENTX_DB_ENV": "./db.env.example",
            **extra_env,
        }
        flags = [arg for p in profiles for arg in ("--profile", p)]
        return subprocess.run(
            ["docker", "compose", "--env-file", "compose.env.example", *flags, "config", "--format", "json"],
            cwd=VPS, env=env, capture_output=True, text=True, timeout=60,
        )

    def _postgres_hosts(self, result) -> dict[str, str]:
        assert result.returncode == 0, result.stderr
        services = json.loads(result.stdout)["services"]
        return {name: svc["environment"]["POSTGRES_HOST"] for name, svc in services.items()}

    def test_every_app_uses_the_vps_db(self):
        hosts = self._postgres_hosts(self._config("scheduler", "migrate", "db"))
        assert hosts == {name: "db" for name in (*APP_SERVICES, "db")}

    def test_settings_alone_point_at_db_but_carry_no_password(self):
        # Even with an empty AGENTX_DB_ENV nothing points at Neon; the app then has no
        # database password and refuses to start (TestSettingsFreshStart).
        result = self._config("scheduler", "migrate", AGENTX_DB_ENV="")
        hosts = self._postgres_hosts(result)
        assert set(hosts.values()) == {"db"}
        services = json.loads(result.stdout)["services"]
        assert all("POSTGRES_PASSWORD" not in svc["environment"] for svc in services.values())

    def test_deploy_refuses_without_db_env(self):
        # EL-3: compose.env names db.env from the start, so a missing file stops compose.
        assert self._config(AGENTX_DB_ENV="./missing.env").returncode != 0
        assert self._config("db", AGENTX_DB_SECRETS_FILE="./missing.env").returncode != 0

    def test_config_succeeds_with_example_env(self):
        result = self._config()
        assert result.returncode == 0, result.stderr
        assert set(json.loads(result.stdout)["services"]) == set(API_SERVICES)

    def test_config_fails_without_proxy_subnet(self):
        assert self._config(PROXY_SUBNET="").returncode != 0


def _caddy_text() -> str:
    """Site block without comments."""
    return "\n".join(line.split("#", 1)[0] for line in CADDY.read_text().splitlines())


class TestCaddySiteBlock:
    def test_serves_both_names_by_default(self):
        assert "{$AGENTX_SITE:api.agentx.social, api-vps.agentx.social} {" in _caddy_text()

    def test_upstreams_are_the_compose_api_services(self):
        match = re.search(r"reverse_proxy \{\$AGENTX_UPSTREAMS:([^}]*)\}", _caddy_text())
        assert match, "reverse_proxy must use the overridable upstream list"
        assert match.group(1).split() == [f"{name}:8000" for name in API_SERVICES]
        assert set(API_SERVICES) <= set(_compose()["services"])

    def test_health_checks_and_retries(self):
        text = _caddy_text()
        for directive in ("health_uri /health", "lb_try_duration", "flush_interval -1"):
            assert directive in text, directive

    def test_never_trusts_incoming_forwarded_headers(self):
        text = _caddy_text()
        assert "trusted_proxies" not in text
        assert not re.search(r"header_up\s+[+-]?X-Forwarded", text, re.I)
        assert "client_ip_headers" not in text

    def test_publishes_nothing_itself(self):
        # Pink Popcorn's Caddy owns the global options and 80/443; this file is a site block only.
        assert not re.match(r"\s*\{\s*\n", _caddy_text().lstrip("\n"))

    def test_access_log_redacts_the_websocket_token(self):
        text = _caddy_text()
        log_block = re.search(r"\n\tlog \{(.*?)\n\t\}", text, re.S)
        assert log_block, "site block must configure its own access log"
        assert re.search(r"request>uri query \{\s*replace token REDACTED\s*\}", log_block.group(1))


@pytest.mark.skipif(shutil.which("caddy") is None, reason="caddy not installed")
class TestCaddyAdapts:
    def _adapt(self, **extra_env) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTX_")}
        result = subprocess.run(
            ["caddy", "adapt", "--config", str(CADDY), "--adapter", "caddyfile"],
            env={**env, **extra_env}, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    @staticmethod
    def _routes(config: dict) -> list[tuple[list[str], list[str]]]:
        out = []
        for server in config["apps"]["http"]["servers"].values():
            for route in server["routes"]:
                hosts = [h for m in route.get("match", []) for h in m.get("host", [])]
                dials = re.findall(r'"dial": "([^"]+)"', json.dumps(route))
                out.append((hosts, dials))
        return out

    def test_production_defaults(self):
        assert self._routes(self._adapt()) == [
            (["api.agentx.social", "api-vps.agentx.social"], ["api-1:8000", "api-2:8000"]),
        ]

    def test_adapted_log_encoder_redacts_token(self):
        logs = self._adapt()["logging"]["logs"]
        encoders = [log["encoder"] for name, log in logs.items() if name != "default"]
        assert encoders, "site log missing"
        for enc in encoders:
            assert enc["format"] == "filter"
            uri = enc["fields"]["request>uri"]
            assert uri["filter"] == "query"
            assert {"parameter": "token", "type": "replace", "value": "REDACTED"} in uri["actions"]

    def test_rehearsal_overrides(self):
        config = self._adapt(
            AGENTX_SITE="http://127.0.0.1:18080", AGENTX_UPSTREAMS="127.0.0.1:18001 127.0.0.1:18002",
        )
        assert self._routes(config) == [(["127.0.0.1"], ["127.0.0.1:18001", "127.0.0.1:18002"])]


class TestSmokeScript:
    def test_executable_and_parses(self):
        assert os.access(SMOKE, os.X_OK)
        assert subprocess.run(["bash", "-n", str(SMOKE)]).returncode == 0

    def test_usage_without_base_url(self):
        result = subprocess.run([str(SMOKE)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 2
        assert "usage" in result.stderr

    def test_runs_every_planned_check(self):
        text = SMOKE.read_text()
        for name in ("health", "ready", "signup", "login", "feed", "websocket", "real-ip"):
            assert re.search(rf"(pass|fail|skip) {re.escape(name)} ", text), name
        for path in ("/health", "/health/ready", "/onboard", "/auth/token", "/feed", "/ws?token="):
            assert path in text, path

    def test_spoofed_address_is_reserved_test_net(self):
        assert 'SPOOFED_IP="203.0.113.77"' in SMOKE.read_text()


class TestAccessLogReportsResolvedCaller:
    """smoke.sh reads client= from the access log; it must be the address uvicorn resolved."""

    @pytest.mark.asyncio
    async def test_spoofed_header_is_not_client(self, caplog):
        import logging

        from httpx import ASGITransport, AsyncClient

        from src.main import app

        caplog.set_level(logging.INFO, logger="agentx.api")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            await c.get("/smoke-realip-test", headers={"X-Forwarded-For": "203.0.113.77"})
        lines = [r.getMessage() for r in caplog.records if "/smoke-realip-test" in r.getMessage()]
        assert lines and "client=127.0.0.1 " in lines[0], lines
        assert "client=203.0.113.77" not in lines[0]
        assert "fwd=203.0.113.77" in lines[0]


class TestForwardedTrust:
    """Drive uvicorn's ProxyHeadersMiddleware (what --proxy-headers/--forwarded-allow-ips
    install) with the compose example's PROXY_SUBNET. The pinned uvicorn must understand the
    CIDR; a stranger's X-Forwarded-For must never become the client."""

    SPOOF = "203.0.113.77"

    @staticmethod
    async def _client_seen_by_app(trusted: str, peer: str, xff: str | None) -> str:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        seen: list[str] = []

        async def app(scope, receive, send):
            seen.append(scope["client"][0])

        headers = [(b"host", b"api.agentx.social")]
        if xff is not None:
            headers.append((b"x-forwarded-for", xff.encode()))
        scope = {"type": "http", "client": (peer, 40000), "headers": headers, "scheme": "http"}
        await ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None)
        return seen[0]

    @pytest.fixture
    def subnet(self) -> str:
        return _env_file(VPS / "compose.env.example")["PROXY_SUBNET"]

    @staticmethod
    def _inside(subnet: str) -> str:
        import ipaddress

        return str(list(ipaddress.ip_network(subnet).hosts())[7])

    @staticmethod
    def _outside(subnet: str) -> str:
        import ipaddress

        for candidate in ("198.51.100.9", "10.200.1.1", "192.168.77.3"):
            if ipaddress.ip_address(candidate) not in ipaddress.ip_network(subnet):
                return candidate
        raise AssertionError("no address outside the subnet")

    async def test_proxy_in_subnet_is_believed(self, subnet):
        assert await self._client_seen_by_app(subnet, self._inside(subnet), self.SPOOF) == self.SPOOF

    async def test_rightmost_untrusted_hop_wins(self, subnet):
        chain = f"{self.SPOOF}, {self._inside(subnet)}"
        assert await self._client_seen_by_app(subnet, self._inside(subnet), chain) == self.SPOOF

    async def test_stranger_header_is_ignored(self, subnet):
        peer = self._outside(subnet)
        assert await self._client_seen_by_app(subnet, peer, self.SPOOF) == peer

    async def test_no_header_keeps_peer(self, subnet):
        peer = self._inside(subnet)
        assert await self._client_seen_by_app(subnet, peer, None) == peer

    async def test_wildcard_would_believe_anyone(self, subnet):
        """This is the hole the compose guard closes: with "*" the stranger picks their address."""
        assert await self._client_seen_by_app("*", self._outside(subnet), self.SPOOF) == self.SPOOF

    def test_compose_subnet_matches_caddy_default_subnet_shape(self, subnet):
        import ipaddress

        net = ipaddress.ip_network(subnet)
        assert net.is_private and net.prefixlen >= 16


class TestNoTokenInLogs:
    """uvicorn logs the request line with its query string; /ws takes ?token=<jwt>. The
    redaction filter installed by src.main must scrub it on both uvicorn loggers."""

    JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkaWQ6YWdlbnR4OmFiYyJ9.c2lnbmF0dXJl"

    @pytest.fixture(autouse=True)
    def _app(self):
        import src.main  # noqa: F401 — installs the filter

    def test_installed_once_on_both_uvicorn_loggers(self):
        import logging

        from src.log_redaction import UVICORN_LOGGERS, RedactQueryTokenFilter, install

        install()
        install()
        for name in UVICORN_LOGGERS:
            filters = [f for f in logging.getLogger(name).filters if isinstance(f, RedactQueryTokenFilter)]
            assert len(filters) == 1, name

    def test_websocket_accept_line_is_redacted(self, caplog):
        import logging

        caplog.set_level(logging.INFO, logger="uvicorn.error")
        logging.getLogger("uvicorn.error").info(
            '%s - "WebSocket %s" [accepted]', ("203.0.113.5", 0), f"/ws?token={self.JWT}",
        )
        assert "token=REDACTED" in caplog.text
        assert self.JWT not in caplog.text and "eyJ" not in caplog.text

    def test_http_access_line_is_redacted(self, caplog):
        import logging

        caplog.set_level(logging.INFO, logger="uvicorn.access")
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "203.0.113.5:1234", "GET", f"/ws?a=1&token={self.JWT}&b=2", "1.1", 403,
        )
        assert "/ws?a=1&token=REDACTED&b=2" in caplog.text
        assert self.JWT not in caplog.text

    @pytest.mark.parametrize("raw,expected", [
        ("/ws?token=abc.def", "/ws?token=REDACTED"),
        ("/ws?TOKEN=abc", "/ws?TOKEN=REDACTED"),
        ("/ws?token=abc&x=1", "/ws?token=REDACTED&x=1"),
        ("/ws?x=1&token=abc", "/ws?x=1&token=REDACTED"),
        ("/feed?refresh_token=abc", "/feed?refresh_token=REDACTED"),
        ("GET /ws?token=abc HTTP/1.1", "GET /ws?token=REDACTED HTTP/1.1"),
        ("/ws?tokens=abc", "/ws?tokens=abc"),
        ("/ws", "/ws"),
        (42, 42),
        (None, None),
    ])
    def test_redact_values(self, raw, expected):
        from src.log_redaction import redact

        assert redact(raw) == expected

    def test_preformatted_message_and_dict_args(self, caplog):
        import logging

        caplog.set_level(logging.INFO, logger="uvicorn.error")
        log = logging.getLogger("uvicorn.error")
        log.info(f"client opened /ws?token={self.JWT}")
        log.info("path=%(path)s", {"path": f"/ws?token={self.JWT}"})
        assert caplog.text.count("token=REDACTED") == 2
        assert self.JWT not in caplog.text

    async def test_app_access_log_prints_path_without_query(self, caplog):
        import logging

        from httpx import ASGITransport, AsyncClient

        from src.main import app

        caplog.set_level(logging.INFO, logger="agentx.api")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            await c.get(f"/ws?token={self.JWT}")
        lines = [r.getMessage() for r in caplog.records if r.name == "agentx.api" and "/ws" in r.getMessage()]
        assert lines, caplog.text
        assert all("token=" not in line and self.JWT not in line for line in lines), lines


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict]:
    return _workflow()["jobs"]["deploy"]["steps"]


class TestDeployWorkflow:
    def test_manual_trigger_only(self):
        triggers = _workflow()[True]  # PyYAML reads the key `on` as True
        assert set(triggers) == {"workflow_dispatch"}
        assert set(triggers["workflow_dispatch"]["inputs"]) == {"commit"}

    def test_production_environment_and_least_privilege(self):
        wf = _workflow()
        assert wf["permissions"] == {}
        assert set(wf["jobs"]) == {"deploy"}
        job = wf["jobs"]["deploy"]
        assert job["environment"]["name"] == "production"
        assert job["permissions"] == {"contents": "read", "packages": "write", "actions": "read"}
        assert wf["concurrency"]["cancel-in-progress"] is False

    def test_actions_pinned_to_commits(self):
        uses = [step["uses"] for step in _steps() if "uses" in step]
        assert uses, "expected at least actions/checkout"
        for ref in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref

    def test_checkout_does_not_keep_token(self):
        checkout = next(s for s in _steps() if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["persist-credentials"] is False

    def test_dispatch_input_never_inline_in_shell(self):
        for step in _steps():
            run = step.get("run", "")
            assert "${{" not in run, step.get("name")
        env = _workflow()["jobs"]["deploy"]["env"]
        assert env["COMMIT_INPUT"] == "${{ inputs.commit }}"
        # COMMIT comes only from the validate step, after the SHA check.
        assert "COMMIT" not in env

    def test_commit_validated_and_on_main(self):
        text = "\n".join(step.get("run", "") for step in _steps())
        assert '"$COMMIT" =~ ^[0-9a-f]{40}$' in text
        assert 'git merge-base --is-ancestor "$COMMIT" origin/main' in text

    def test_commit_input_trimmed_then_validated_then_exported(self):
        validate = next(s for s in _steps() if s.get("name") == "Validate commit input")["run"]
        trim = validate.index('COMMIT="${COMMIT%"')
        check = validate.index('=~ ^[0-9a-f]{40}$')
        export = validate.index('echo "COMMIT=$COMMIT" >> "$GITHUB_ENV"')
        assert trim < check < export
        assert "exit 1" in validate[check:export]
        checkout = next(s for s in _steps() if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ env.COMMIT }}"

    def test_commit_trim_behaviour_in_bash(self):
        """Run the validate step's script in bash: padded SHAs pass trimmed, anything else fails."""
        validate = next(s for s in _steps() if s.get("name") == "Validate commit input")["run"]
        sha = "dbf80fb" + "0" * 33

        def run(value: str) -> tuple[int, str]:
            with tempfile.NamedTemporaryFile("r", suffix=".env") as env_file:
                proc = subprocess.run(
                    ["bash", "-c", validate],
                    env={"COMMIT_INPUT": value, "GITHUB_ENV": env_file.name, "PATH": os.environ["PATH"]},
                    capture_output=True, text=True,
                )
                return proc.returncode, open(env_file.name).read()

        for padded in (sha, "  " + sha, "    " + sha, sha + "\n", "\t " + sha + "  \r\n"):
            assert run(padded) == (0, f"COMMIT={sha}\n"), repr(padded)
        for bad in ("", "   ", sha[:39], sha.upper(), sha[:20] + " " + sha[20:39],
                    sha + "\nEVIL=1", sha + " x", "main"):
            code, exported = run(bad)
            assert code == 1 and exported == "", repr(bad)

    def test_main_comes_from_checkout_not_an_anonymous_fetch(self):
        """fetch-depth 0 fetches every branch with the job token; a bare `git fetch` would fail
        on a private repository and must not be relied on. Missing origin/main fails closed."""
        checkout = next(s for s in _steps() if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["fetch-depth"] == 0
        commands = "\n".join(
            line for step in _steps() for line in step.get("run", "").splitlines()
            if not line.strip().startswith("#")
        )
        assert "git fetch" not in commands
        assert "git rev-parse --verify --quiet origin/main" in commands
        on_main = next(s for s in _steps() if s.get("name") == "Only commits already on main")["run"]
        assert on_main.index("rev-parse --verify") < on_main.index("merge-base --is-ancestor")
        assert "exit 1" in on_main.split("merge-base")[0]

    def test_ssh_host_key_pinned(self):
        text = WORKFLOW.read_text()
        assert "StrictHostKeyChecking yes" in text
        assert "StrictHostKeyChecking no" not in text
        assert "ssh-keyscan" not in text
        assert "secrets.VPS_KNOWN_HOSTS" in text

    def test_step_order_build_migrate_roll_verify(self):
        names = [step.get("name", step.get("uses", "")) for step in _steps()]
        order = [
            "Validate commit input", "Only commits already on main", "Build and push image",
            "Set up SSH (pinned host key)", "Copy compose files to the VPS",
            "Migrate, then roll api-1 and api-2", "Verify the new commit is serving",
        ]
        assert [n for n in names if n in order] == order
        assert names.index(order[0]) < names.index(next(n for n in names if n.startswith("actions/checkout@")))

    def test_builds_fly_dockerfile_with_commit(self):
        build = next(s for s in _steps() if s.get("name") == "Build and push image")["run"]
        assert "--platform linux/amd64" in build
        assert '--build-arg GIT_COMMIT="$COMMIT"' in build
        assert "-f platform/Dockerfile.fly" in build

    def test_secrets_only_via_env_and_key_removed(self):
        for step in _steps():
            assert "secrets." not in step.get("run", ""), step.get("name")
        last = _steps()[-1]
        assert last["if"] == "always()" and 'rm -rf "$RUNNER_TEMP/ssh"' in last["run"]

    def test_rollback_line_skips_migration(self):
        rollback = next(s for s in _steps() if s.get("name") == "Rollback instructions")
        assert rollback["if"] == "failure()"
        assert "SKIP_MIGRATE=1 bash deploy.sh" in rollback["run"]

    @pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint not installed")
    def test_actionlint_clean(self):
        result = subprocess.run(["actionlint", str(WORKFLOW)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr


FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$*" in
  "network inspect -f {{range .IPAM.Config}}"*) echo "${FAKE_NET_SUBNET-10.250.0.0/24} "; exit 0 ;;
  "network inspect -f {{range \$id"*) echo "${FAKE_NET_MEMBERS-caddyid}"; exit 0 ;;
  "network inspect "*) [ "${FAKE_NET_EXISTS:-1}" = 1 ]; exit $? ;;
  "inspect -f {{.Id}} "*) [ "${FAKE_CADDY:-1}" = 1 ] || exit 1; echo caddyid; exit 0 ;;
  "inspect -f {{index .Config.Labels"*) case "${*: -1}" in stranger*) echo pinkpopcorn-feed ;; *) echo agentx ;; esac; exit 0 ;;
  *"com.docker.compose.service=scheduler"*) [ "${FAKE_SCHEDULER:-0}" = 1 ] && echo sched1; exit 0 ;;
  *"run --rm migrate python scripts/bootstrap_db.py --check"*) exit "${FAKE_DB_CHECK_RC:-0}" ;;
  *"run --rm migrate"*) exit "${FAKE_MIGRATE_RC:-0}" ;;
  *" ps -q "*) echo "cid-${*: -1}"; exit 0 ;;
  "inspect "*) echo "${FAKE_HEALTH:-healthy}"; exit 0 ;;
esac
exit 0
"""

NEW = "a" * 40
OLD = "b" * 40


class TestDeployScript:
    @pytest.fixture
    def run(self, tmp_path):
        fakebin = tmp_path / "bin"
        fakebin.mkdir()
        docker = fakebin / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        workdir = tmp_path / "opt"
        workdir.mkdir()
        (workdir / "compose.env").write_text(
            f"AGENTX_IMAGE=ghcr.io/x/agentx-platform\nIMAGE_TAG={OLD}\nPROXY_NETWORK=agentx_edge\n"
            "PROXY_SUBNET=10.250.0.0/24\nCADDY_CONTAINER=pinkpopcorn-feed-caddy-1\n")
        log = tmp_path / "docker.log"

        def _run(tag=NEW, **env):
            log.write_text("")
            result = subprocess.run(
                ["bash", str(DEPLOY_SH), tag],
                env={"PATH": f"{fakebin}:/usr/bin:/bin", "AGENTX_DIR": str(workdir),
                     "FAKE_LOG": str(log), "HEALTH_TIMEOUT": "6", **env},
                capture_output=True, text=True, timeout=60,
            )
            calls = [line for line in log.read_text().splitlines() if line]
            return result, calls, (workdir / "compose.env").read_text()
        return _run

    @staticmethod
    def _index(calls, needle):
        return next(i for i, c in enumerate(calls) if needle in c)

    def test_executable_and_shellcheck(self):
        assert os.access(DEPLOY_SH, os.X_OK)
        if shutil.which("shellcheck"):
            assert subprocess.run(["shellcheck", str(DEPLOY_SH)]).returncode == 0

    @pytest.mark.parametrize("tag", ["", "abc", NEW.upper(), NEW + "; rm -rf /", "main", f"{NEW[:39]}"])
    def test_rejects_anything_but_a_full_sha(self, run, tag):
        result, calls, env = run(tag)
        assert result.returncode == 2 and "usage" in result.stderr
        assert calls == [] and f"IMAGE_TAG={OLD}" in env

    def test_migrates_before_rolling_api_1_then_api_2(self, run):
        result, calls, env = run()
        assert result.returncode == 0, result.stderr
        migrate = self._index(calls, "run --rm migrate")
        up1 = self._index(calls, "up -d --no-deps api-1")
        up2 = self._index(calls, "up -d --no-deps api-2")
        inspect1 = self._index(calls, "inspect -f {{.State.Health.Status}} cid-api-1")
        assert self._index(calls, "pull api-1") < migrate < up1 < inspect1 < up2
        assert not any("scheduler up" in c for c in calls)
        assert f"IMAGE_TAG={NEW}" in env
        assert f"previous={OLD}" in result.stdout

    def test_failed_migration_replaces_nothing(self, run):
        result, calls, env = run(FAKE_MIGRATE_RC="1")
        assert result.returncode != 0
        assert not any(" up " in f" {c} " for c in calls)
        assert f"IMAGE_TAG={OLD}" in env

    def test_checks_for_a_bootstrapped_database_before_migrating(self, run):
        result, calls, _ = run()
        assert result.returncode == 0, result.stderr
        check = self._index(calls, "run --rm migrate python scripts/bootstrap_db.py --check")
        migrate = next(i for i, c in enumerate(calls) if c.endswith("run --rm migrate"))
        assert self._index(calls, "pull api-1") < check < migrate

    @pytest.mark.parametrize("rc", ["3", "1"])
    def test_empty_or_foreign_database_is_never_migrated(self, run, rc):
        """EL-1: alembic on an empty database half-builds it; deploy refuses and names the bootstrap."""
        result, calls, env = run(FAKE_DB_CHECK_RC=rc)
        assert result.returncode != 0
        assert "refusing to migrate" in result.stderr and "scripts/bootstrap_db.py" in result.stderr
        assert not any(c.endswith("run --rm migrate") for c in calls)
        assert not any(" up " in f" {c} " for c in calls)
        assert f"IMAGE_TAG={OLD}" in env

    def test_bootstrap_is_never_run_by_deploy(self):
        """Seeding founders is a deliberate one-time step, never part of a deploy."""
        code = [line for line in DEPLOY_SH.read_text().splitlines()
                if not line.strip().startswith(("#", "echo"))]
        assert all("bootstrap_db.py" not in line or "--check" in line for line in code)

    def test_unhealthy_api_1_stops_before_api_2(self, run):
        result, calls, env = run(FAKE_HEALTH="unhealthy")
        assert result.returncode != 0
        assert any("up -d --no-deps api-1" in c for c in calls)
        assert not any("api-2" in c and " up " in f" {c} " for c in calls)
        assert f"IMAGE_TAG={OLD}" in env

    def test_restarts_scheduler_only_if_it_was_running(self, run):
        result, calls, _ = run(FAKE_SCHEDULER="1")
        assert result.returncode == 0, result.stderr
        assert self._index(calls, "up -d --no-deps api-2") < self._index(
            calls, "--profile scheduler up -d --no-deps scheduler")

    # Proxy network (H29 answer, cycle 227): agentx_edge is shared by Caddy and AgentX only.
    def test_creates_network_and_connects_caddy_before_anything_else(self, run):
        result, calls, _ = run(FAKE_NET_EXISTS="0", FAKE_NET_MEMBERS="")
        assert result.returncode == 0, result.stderr
        create = self._index(calls, "network create --driver bridge --subnet 10.250.0.0/24 agentx_edge")
        connect = self._index(calls, "network connect agentx_edge pinkpopcorn-feed-caddy-1")
        assert create < connect < self._index(calls, "pull api-1")

    def test_existing_network_with_caddy_is_left_alone(self, run):
        result, calls, _ = run(FAKE_NET_MEMBERS="caddyid agentx-api-1 agentx-api-2")
        assert result.returncode == 0, result.stderr
        assert not any("network create" in c or "network connect" in c for c in calls)

    def _refused(self, result, calls, env, words):
        assert result.returncode != 0
        assert "refusing to deploy" in result.stderr or "must set" in result.stderr
        assert words in result.stderr
        assert not any(" pull " in f" {c} " or " up " in f" {c} " or "migrate" in c for c in calls)
        assert f"IMAGE_TAG={OLD}" in env

    def test_refuses_when_another_container_is_on_the_network(self, run):
        result, calls, env = run(FAKE_NET_MEMBERS="caddyid agentx-api-1 stranger-app")
        self._refused(result, calls, env, "neither Caddy nor AgentX")

    def test_refuses_when_network_range_differs_from_trusted_subnet(self, run):
        result, calls, env = run(FAKE_NET_SUBNET="172.18.0.0/16")
        self._refused(result, calls, env, "is not exactly 10.250.0.0/24")

    def test_refuses_when_caddy_container_is_missing(self, run):
        result, calls, env = run(FAKE_CADDY="0")
        self._refused(result, calls, env, "Caddy container pinkpopcorn-feed-caddy-1 not found")

    @pytest.mark.parametrize("name", ["PROXY_NETWORK", "PROXY_SUBNET", "CADDY_CONTAINER"])
    def test_refuses_without_proxy_settings(self, run, tmp_path, name):
        env_path = tmp_path / "opt" / "compose.env"
        env_path.write_text("\n".join(
            line for line in env_path.read_text().splitlines() if not line.startswith(f"{name}=")) + "\n")
        result, calls, env = run()
        self._refused(result, calls, env, "must set PROXY_NETWORK, PROXY_SUBNET and CADDY_CONTAINER")
        assert calls == []

    def test_rollback_skips_migration(self, run):
        result, calls, env = run(OLD, SKIP_MIGRATE="1")
        assert result.returncode == 0, result.stderr
        assert not any("migrate" in c for c in calls)
        assert f"IMAGE_TAG={OLD}" in env


# ── TF-3: status records for the founders BRUNO and QUINN ────────────────────

DB_MOVE = VPS / "db_move.sh"
STATUS_MOUNT = "${AGENTX_STATUS_DIR:-/opt/agentx/status}:/var/lib/agentx/status:ro"


def _status_record_fn(script: Path) -> str:
    text = script.read_text()
    start = text.index("status_record() {")
    return text[start:text.index("\n}\n", start) + 3]


class TestStatusRecords:
    def test_only_the_scheduler_mounts_the_folder_read_only(self):
        services = _compose()["services"]
        assert services["scheduler"]["volumes"] == [STATUS_MOUNT]
        for name in ("api-1", "api-2", "migrate", "db"):
            assert "volumes" not in services[name] or STATUS_MOUNT not in services[name]["volumes"]

    def test_app_reads_the_mounted_path(self):
        from src.config import Settings
        assert Settings.model_fields["founder_status_dir"].default == "/var/lib/agentx/status"

    def test_every_writer_writes_its_record(self):
        deploy, db_move, smoke = DEPLOY_SH.read_text(), DB_MOVE.read_text(), SMOKE.read_text()
        assert "status_record deploy " in deploy
        assert "status_record backup " in db_move and "status_record restore_test " in db_move
        assert "status_record smoke " in smoke and 'STATUS_DIR="$SMOKE_STATUS_DIR"' in smoke
        # deploy.json only after both APIs are healthy and compose.env records the tag.
        assert deploy.index("status_record deploy ") > deploy.index('wait_healthy "$svc"')
        assert deploy.index("status_record deploy ") > deploy.index("sed -i.bak")

    def test_workflow_writes_ci_record_best_effort_and_last(self):
        steps = _steps()
        names = [s.get("name") for s in steps]
        i = names.index("Record CI of the live commit for the founders")
        assert i > names.index("Verify the new commit is serving")
        step = steps[i]
        assert step["continue-on-error"] is True
        assert "/opt/agentx/status/ci.json" in step["run"] and "chmod 644" in step["run"]
        assert '"name")=="CI"' in step["run"]   # the CI workflow only, not this deploy's own job

    def test_deploy_makes_the_folder_before_containers_mount_it(self):
        deploy = DEPLOY_SH.read_text()
        mkdir = deploy.index('mkdir -p "$STATUS_DIR") || echo')
        assert mkdir < deploy.index("dc up -d --no-deps")

    @pytest.mark.parametrize("script", [DEPLOY_SH, DB_MOVE, SMOKE])
    def test_status_record_writes_a_readable_file(self, script, tmp_path):
        fn = _status_record_fn(script)
        out = tmp_path / "status"
        r = subprocess.run(["bash", "-c", f'set -euo pipefail; umask 077; {fn}\nSTATUS_DIR="$1"; '
                            'status_record deploy \'{"a": 1}\'', "x", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        f = out / "deploy.json"
        assert json.loads(f.read_text()) == {"a": 1}
        assert oct(f.stat().st_mode & 0o777) == "0o644" and oct(out.stat().st_mode & 0o777) == "0o755"
        assert not list(out.glob(".*.tmp"))

    @pytest.mark.parametrize("script", [DEPLOY_SH, DB_MOVE, SMOKE])
    def test_status_record_never_fails_the_run(self, script, tmp_path):
        fn = _status_record_fn(script)
        blocker = tmp_path / "file"
        blocker.write_text("not a folder")
        r = subprocess.run(["bash", "-c", f'set -euo pipefail; {fn}\nSTATUS_DIR="$1"; '
                            'status_record deploy "{}"; echo after', "x", str(blocker / "status")],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip() == "after", r.stderr
        assert "warning: could not write" in r.stderr

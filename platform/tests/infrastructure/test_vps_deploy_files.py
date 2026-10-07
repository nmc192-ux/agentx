"""
Tests: VPS deploy files (Sprint 16, S16-2) — deploy/vps/

Pins the rules from vps_migration_plan.md §3 so the compose file cannot drift into an
unsafe shape:
  1. No `ports:` anywhere — only the shared Caddy (proxy network) reaches the API.
  2. Forwarded headers are trusted from the proxy subnet only; never "*", and the API
     refuses to start if the trust list is empty or a wildcard.
  3. scheduler and migrate are profile-gated, so a plain `up` never starts a second
     scheduler or a migration.
  4. settings.env carries exactly Fly's [env] values; no secret-looking values in deploy/.
S16-3 adds:
  5. agentx.caddy serves the two API names from api-1/api-2:8000 with active health checks
     and retries, and never trusts incoming forwarded headers (no trusted_proxies, no
     X-Forwarded-For override), so a caller cannot choose the address the API believes.
  6. smoke.sh runs every check the plan lists, and the API's access log reports the
     resolved caller (client=), not the raw header, which is what smoke.sh reads.
"""
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
VPS = REPO / "deploy" / "vps"
COMPOSE = VPS / "docker-compose.yml"
CADDY = VPS / "agentx.caddy"
SMOKE = VPS / "smoke.sh"
FLY_TOML = REPO / "platform" / "fly.toml"

SECRET_NAMES = {
    "POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SENTRY_DSN",
    "ANTHROPIC_API_KEY", "FOUNDER_DIDS",
}
API_SERVICES = ("api-1", "api-2")


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
        assert services["scheduler"]["command"] == (
            "celery -A src.jobs.celery_app worker --beat --concurrency 1 --loglevel info".split()
        )
        for name in API_SERVICES:
            assert "profiles" not in services[name]

    def test_limits_logs_restart(self):
        for name, svc in _compose()["services"].items():
            assert svc["mem_limit"] == "512m", name
            assert svc["logging"]["driver"] == "json-file", name
            assert svc["logging"]["options"] == {"max-size": "20m", "max-file": "5"}, name
            expected = "no" if name == "migrate" else "unless-stopped"
            assert svc["restart"] == expected, name

    def test_secrets_come_from_root_file(self):
        for name, svc in _compose()["services"].items():
            paths = [entry["path"] for entry in svc["env_file"]]
            assert paths == ["./settings.env", "${AGENTX_SECRETS_FILE:-/etc/agentx/api.env}"], name


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

    def test_example_subnet_is_narrow(self):
        value = _env_file(VPS / "compose.env.example")["PROXY_SUBNET"]
        assert "*" not in value and value not in ("0.0.0.0/0", "::/0")
        assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+/(1[6-9]|2\d|3[0-2])", value)


class TestSettingsMatchFly:
    def test_settings_equal_fly_env(self):
        fly_env = tomllib.loads(FLY_TOML.read_text())["env"]
        settings = _env_file(VPS / "settings.env")
        assert settings == {k: str(v) for k, v in fly_env.items()}

    def test_no_secrets_in_settings(self):
        assert not SECRET_NAMES & set(_env_file(VPS / "settings.env"))

    def test_secrets_example_has_names_only(self):
        values = _env_file(VPS / "secrets.env.example")
        assert {"POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SENTRY_DSN"} <= set(values)
        assert all(v == "" for v in values.values())

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
    def _config(self, **extra_env):
        env = {**os.environ, "AGENTX_SECRETS_FILE": "./secrets.env.example", **extra_env}
        return subprocess.run(
            ["docker", "compose", "--env-file", "compose.env.example", "config", "--format", "json"],
            cwd=VPS, env=env, capture_output=True, text=True, timeout=60,
        )

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

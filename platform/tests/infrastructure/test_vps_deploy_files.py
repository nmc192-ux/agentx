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
DEPLOY_SH = VPS / "deploy.sh"
WORKFLOW = REPO / ".github" / "workflows" / "deploy-vps.yml"
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
        assert job["permissions"] == {"contents": "read", "packages": "write"}
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
        assert _workflow()["jobs"]["deploy"]["env"]["COMMIT"] == "${{ inputs.commit }}"

    def test_commit_validated_and_on_main(self):
        text = "\n".join(step.get("run", "") for step in _steps())
        assert '"$COMMIT" =~ ^[0-9a-f]{40}$' in text
        assert 'git merge-base --is-ancestor "$COMMIT" origin/main' in text

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
  *"com.docker.compose.service=scheduler"*) [ "${FAKE_SCHEDULER:-0}" = 1 ] && echo sched1; exit 0 ;;
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
        (workdir / "compose.env").write_text(f"AGENTX_IMAGE=ghcr.io/x/agentx-platform\nIMAGE_TAG={OLD}\n")
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

    def test_rollback_skips_migration(self, run):
        result, calls, env = run(OLD, SKIP_MIGRATE="1")
        assert result.returncode == 0, result.stderr
        assert not any("migrate" in c for c in calls)
        assert f"IMAGE_TAG={OLD}" in env

"""
Tests: GET /.well-known/skill.md and GET /.well-known/agent.json — what they
tell an outside agent.

Sprint 9 (S9-7c): the document promised "a funded wallet (100 AXP)" and sent
agents to a wallet route that did not exist. External agents act on this
text, so the claims are pinned here.

Sprint 9 (S9-13a, the truth audit): every path either document names must be
a route the app really mounts — on the repo default router list, with every
gated router off (production today) and with everything on — and a section
about a gated router is only printed when that router is on.
"""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.a2a.agent_card import generate_platform_card
from src.a2a.skill import _human_duration, render_skill_md
from src.config import get_settings
from src.main import app
from src.router_config import DEFAULT_DISABLED_ROUTERS
from src.services import reputation

PLATFORM_DIR = Path(__file__).resolve().parents[2]
BASE = "http://testserver"

# Every router name main.py puts behind the gate.
GATED_ROUTERS = sorted(set(re.findall(
    r'_include_if_enabled\(\s*\w+,\s*"(\w+)"', (PLATFORM_DIR / "src" / "main.py").read_text(),
)))

# The three deployments the documents are checked on.
CONFIGS = {
    # No env override: router_config.DEFAULT_DISABLED_ROUTERS decides.
    "repo default": (None, ("DISABLED_ROUTERS", "ALLOW_UNSAFE_ROUTERS")),
    # Production until DrJ removes the Fly override (HUMAN_ACTIONS H3).
    "every gated router off": (",".join(GATED_ROUTERS), ("ALLOW_UNSAFE_ROUTERS",)),
    # What the rest of the suite runs with.
    "every router on": ("", ()),
}


@pytest.fixture
async def skill_md() -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=BASE,
    ) as client:
        resp = await client.get("/.well-known/skill.md")
    assert resp.status_code == 200
    return resp.text


@pytest.mark.asyncio
async def test_does_not_promise_a_funded_wallet(skill_md):
    lowered = skill_md.lower()
    assert "funds your wallet" not in lowered
    assert "funded wallet" not in lowered
    assert "100 axp" not in lowered
    assert '"wallet_balance":  0' in skill_md
    assert "starts at **0 AXP**" in skill_md


@pytest.mark.asyncio
async def test_wallet_commands_name_routes_that_exist(skill_md):
    routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])}
    economy = skill_md.split("## Economy")[1].split("## Governance")[0]
    paths = set(re.findall(r'"http://testserver(/[^"?]*)', economy))
    assert paths == {"/wallets", "/wallets/by-did"}
    assert ("POST", "/wallets") in routes
    assert ("GET", "/wallets/by-did") in routes


@pytest.mark.asyncio
async def test_governance_commands_name_routes_that_exist(skill_md):
    """S9-8: the section used to name a vote route that never existed."""
    routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])}
    governance = skill_md.split("## Governance")[1].split("## Collaboration Rooms")[0]
    paths = set(re.findall(r'"http://testserver(/[^"?]*)', governance))
    assert paths == {
        "/governance/proposals", "/governance/vote",
        "/governance/results", "/governance/parameters",
    }
    assert ("POST", "/governance/vote") in routes
    for path in paths - {"/governance/vote"}:
        assert ("GET", path) in routes
    assert '{"proposal_id": "<proposal-id>", "vote": "yes"}' in governance
    assert "stakes cannot be released" in governance


@pytest.mark.asyncio
async def test_template_renders_without_leftover_placeholders(skill_md):
    assert "{base_url}" not in skill_md
    assert "-d '{}'" in skill_md
    # No str.format placeholder of any name survives ({word} with no quotes).
    assert not re.findall(r"(?<!\{)\{[a-z_]+\}(?!\})", skill_md)


# ── S9-13a: every path in the documents is a mounted route ───────────────────

@functools.lru_cache(maxsize=None)
def _deployment(config: str) -> dict:
    """Boot the real app in a fresh process with one router configuration and
    return its route table and both discovery documents."""
    disabled, unset = CONFIGS[config]
    env = {k: v for k, v in os.environ.items() if k not in unset}
    if disabled is not None:
        env["DISABLED_ROUTERS"] = disabled
    for name in ("PLATFORM_BASE_URL", "AGENTX_BASE_URL"):
        env.pop(name, None)
    code = (
        "import asyncio, json\n"
        "import src.main as m\n"
        "from httpx import ASGITransport, AsyncClient\n"
        "async def docs():\n"
        f"    async with AsyncClient(transport=ASGITransport(app=m.app), base_url={BASE!r}) as c:\n"
        "        skill = await c.get('/.well-known/skill.md')\n"
        "        card = await c.get('/.well-known/agent.json')\n"
        "    assert skill.status_code == 200 and card.status_code == 200\n"
        "    return skill.text, card.json()\n"
        "skill, card = asyncio.run(docs())\n"
        "routes = [[meth, r.path, r.path_regex.pattern] for r in m.app.routes\n"
        "          for meth in (getattr(r, 'methods', None) or [])]\n"
        "print('RESULT=' + json.dumps({'routes': routes, 'skill': skill, 'card': card}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PLATFORM_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(ln for ln in reversed(result.stdout.splitlines()) if ln.startswith("RESULT="))
    return json.loads(line[len("RESULT="):])


_EXAMPLE_DID = "did:agentx:example-001"
_EXAMPLE_ID = "11111111-1111-1111-1111-111111111111"
_VERBS = "GET|POST|PATCH|PUT|DELETE"


def _concrete(path: str) -> str:
    """Turn a path as the documents write it into one a route can match:
    no query string, no trailing punctuation, placeholders filled in."""
    path = path.split("?")[0].rstrip(".,;:*)")
    return re.sub(
        r"<[^>]*>|\{[^}]*\}",
        lambda m: _EXAMPLE_DID if "did" in m.group(0).lower() else _EXAMPLE_ID,
        path,
    )


def _paths_in(text: str) -> set[tuple[str | None, str]]:
    """Every (method, path) a document names. Method None = not stated."""
    found: set[tuple[str | None, str]] = set()
    for line in text.splitlines():
        # "POST http://testserver/onboard" reads like "POST /onboard".
        line = re.sub(rf"\b({_VERBS})\s+{re.escape(BASE)}/", r"\1 /", line)
        # curl lines: the method is on the line that carries the URL.
        for path in re.findall(re.escape(BASE) + r"(/[^\s\"'\\`]*)", line):
            found.add(("POST" if "-X POST" in line else "GET", _concrete(path)))
        # "POST /posts/<post_id>/flag", "1. GET  /feed/global?limit=20"
        for verb, path in re.findall(rf"\b({_VERBS})\s+(/[^\s`\"'),]*)", line):
            found.add((verb, _concrete(path)))
        # `/notifications`, "/heartbeat" — a path on its own, method not stated
        for path in re.findall(r"[`\"](/[^`\"\s]*)[`\"]", line):
            found.add((None, _concrete(path)))
    return found


def _unmounted(named: set[tuple[str | None, str]], routes: list[list[str]]) -> list:
    compiled = [(meth, re.compile(pattern)) for meth, _path, pattern in routes]
    return sorted(
        (verb or "ANY", path) for verb, path in named
        if not any(
            (verb is None or verb == meth) and regex.match(path)
            for meth, regex in compiled
        )
    )


def _card_text(card: dict) -> str:
    """The parts of an Agent Card that name URLs or routes."""
    lines = [card["url"], card["documentationUrl"], card["description"],
             card["authentication"]["credentials"]]
    lines += [skill["description"] for skill in card["skills"]]
    return "\n".join(lines)


@pytest.mark.parametrize("config", list(CONFIGS))
def test_every_path_in_skill_md_is_a_mounted_route(config):
    deployment = _deployment(config)
    named = _paths_in(deployment["skill"])
    assert len(named) >= 15, named
    assert ("POST", "/onboard") in named and ("POST", "/heartbeat") in named
    assert not _unmounted(named, deployment["routes"])


@pytest.mark.parametrize("config", list(CONFIGS))
def test_every_path_in_the_agent_card_is_a_mounted_route(config):
    deployment = _deployment(config)
    named = _paths_in(_card_text(deployment["card"]))
    assert ("GET", "/a2a") in named  # card.url, read as a plain URL
    named.discard(("GET", "/a2a"))
    named.add(("POST", "/a2a"))
    assert ("GET", "/agents/discover") in named
    assert not _unmounted(named, deployment["routes"])


def test_the_path_check_catches_a_route_that_is_not_there():
    """The checker itself: a made-up path and a wrong method are reported."""
    routes = _deployment("repo default")["routes"]
    named = _paths_in(
        f'curl -s "{BASE}/agents/discover?q=x"\n'
        f"curl -s -X POST {BASE}/governance/proposals/<proposal-id>/vote \\\n"
        "then `GET /posts/<post_id>/flag` and `/no-such-thing`"
    )
    assert _unmounted(named, routes) == [
        ("ANY", "/no-such-thing"),
        ("GET", f"/posts/{_EXAMPLE_ID}/flag"),
        ("POST", f"/governance/proposals/{_EXAMPLE_ID}/vote"),
    ]


def test_repo_default_document_has_every_enabled_section():
    # tasks: held off by decision D2b until creator approval ships (E0 → E1).
    assert set(DEFAULT_DISABLED_ROUTERS) == {"nodes", "consensus", "tasks"}
    skill = _deployment("repo default")["skill"]
    for heading in ("## Economy", "## Governance", "## Collaboration Rooms"):
        assert heading in skill
    assert "## Paid tasks" not in skill
    assert "/tasks" not in skill
    card_skills = {s["id"] for s in _deployment("repo default")["card"]["skills"]}
    assert card_skills == {
        "agent_discovery", "trust_scoring",
        "contract_marketplace", "governance", "token_economy",
    }


def test_gated_features_are_left_out_when_their_routers_are_off():
    """Production today: nothing may point an agent at a route that is off."""
    deployment = _deployment("every gated router off")
    skill = deployment["skill"]
    for heading in ("## Paid tasks", "## Economy", "## Governance", "## Collaboration Rooms"):
        assert heading not in skill
    for fragment in ("/wallets", "/governance", "/rooms", "/tasks", "/contracts",
                     "earn tokens", "vote on governance", "vote weight"):
        assert fragment not in skill, fragment
    assert "## Trust score" in skill and "## Heartbeat" in skill
    card = deployment["card"]
    assert {s["id"] for s in card["skills"]} == {"agent_discovery", "trust_scoring"}
    # message/send would publish a task no route can list: not offered.
    assert "message/send" not in card["description"]
    assert card["description"].endswith("this A2A endpoint accepts tasks/get.")


# ── S9-13a: the claims themselves ────────────────────────────────────────────

def _render(*enabled: str, access: int = 900, refresh: int = 604_800,
            welcomes: bool = False) -> str:
    return render_skill_md(
        BASE, lambda name: name in enabled,
        access_token_ttl=access, refresh_token_ttl=refresh, welcomes=welcomes,
    )


@pytest.mark.asyncio
async def test_no_tiers_or_trust_rewards_that_do_not_exist(skill_md):
    for untrue in ("STANDARD", "PRO tier", "ENTERPRISE", "unlocks higher tiers",
                   "maintain trust score", "raises your trust score",
                   "always up to date", "always reflects the current API",
                   "engagement scores", "10k agents", "daria-004", "?q="):
        assert untrue not in skill_md, untrue
    assert "do\n**not** change it" in skill_md           # posting earns no trust
    assert "Tiers do not unlock anything today" in skill_md
    assert "/agents/discover?capability=research" in skill_md
    assert "did:agentx:daria-001" in skill_md             # the founders are <name>-001


@pytest.mark.asyncio
async def test_token_lifetimes_come_from_the_settings(skill_md):
    settings = get_settings()
    refresh = skill_md.split("### Refresh your token")[1].split("### Read the global feed")[0]
    assert f"expires after {_human_duration(settings.jwt_access_token_ttl)}." in refresh
    assert f"expires after\n{_human_duration(settings.jwt_refresh_token_ttl)}." in refresh
    assert "a new `refresh_token`" in refresh
    # Production values (fly.toml): 15 minutes and 7 days, not "1 hour".
    production = _render()
    assert "expires after 15 minutes." in production
    assert "Refresh at least once every 7 days" in production
    assert "1 hour" not in production


def test_human_duration():
    assert _human_duration(900) == "15 minutes"
    assert _human_duration(3600) == "1 hour"
    assert _human_duration(14_400) == "4 hours"
    assert _human_duration(86_400) == "1 day"
    assert _human_duration(604_800) == "7 days"
    assert _human_duration(90) == "90 seconds"


def test_refresh_before_heartbeat_only_when_the_token_is_shorter_lived():
    assert "refresh it first" in _render(access=900)
    assert "refresh it first" not in _render(access=86_400)


def test_trust_amounts_come_from_the_reputation_rules():
    """The numbers are the ones services/reputation.py enforces."""
    weights = reputation.EVENT_WEIGHTS
    everything = _render("tasks", "verifications", "governance")
    assert f"**+{weights['task_completed']:.2f}**" in everything
    assert f"**+{weights['message_replied']:.2f}**" in everything
    assert f"**+{weights['peer_validation']:.2f}**" in everything
    assert f"**−{abs(weights['task_failed']):.2f}**" in everything
    assert f"at most {reputation.MAX_DAILY_GAIN:.2f} in 24" in everything
    assert "at least\n1 day old" in everything
    assert reputation.MIN_COUNTERPARTY_AGE.total_seconds() == 86_400
    assert "stake × your trust score" in everything

    # Only what this deployment can really give is listed.
    social_only = _render()
    trust = social_only.split("## Trust score")[1].split("## Machine-readable")[0]
    assert f"**+{weights['message_replied']:.2f}**" in trust
    assert "marketplace" not in trust and "verification" not in trust
    assert "vote" not in trust


def test_sections_follow_their_routers_one_by_one():
    assert "## Paid tasks" in _render("tasks")
    assert "## Economy" not in _render("tasks")
    assert "earn tokens" not in _render("tasks")          # needs wallets too
    assert "earn tokens for paid tasks" in _render("tasks", "wallets")

    wallets_only = _render("wallets")
    assert "## Economy" in wallets_only
    assert "Tokens are earned" not in wallets_only         # nothing here pays
    economy = _render("wallets", "markets").split("## Economy")[1]
    assert "capability bounty" in economy
    assert "Completing a contract" not in economy and "carries a reward" not in economy

    assert "## Governance" in _render("governance")
    assert "## Collaboration Rooms" in _render("rooms")
    assert "## Collaboration Rooms" not in _render("governance")


# ── S9-13a: the Agent Card ───────────────────────────────────────────────────

@pytest.fixture
async def agent_card() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    assert resp.headers["vary"] == "Host"
    return resp.json()


@pytest.mark.asyncio
async def test_card_offers_only_what_the_a2a_endpoint_implements(agent_card):
    """POST /a2a has message/send and tasks/get: no streaming, no push
    notifications, no stored history."""
    assert agent_card["capabilities"] == {
        "streaming": False, "pushNotifications": False, "stateTransitionHistory": False,
    }
    from src.a2a.router import _METHODS
    assert set(_METHODS) == {"message/send", "tasks/get"}


@pytest.mark.asyncio
async def test_card_points_at_the_host_it_was_asked_on(agent_card):
    """It used to print http://localhost:8000 unless PLATFORM_BASE_URL was set
    (it is not, in production)."""
    assert agent_card["url"] == f"{BASE}/a2a"
    assert agent_card["provider"]["url"] == BASE
    # /docs is switched off in production; skill.md is served everywhere.
    assert agent_card["documentationUrl"] == f"{BASE}/.well-known/skill.md"
    assert "localhost" not in json.dumps(agent_card)


@pytest.mark.asyncio
async def test_card_says_how_a_token_is_really_obtained(agent_card):
    credentials = agent_card["authentication"]["credentials"]
    assert "API key" not in credentials
    assert f"POST {BASE}/onboard" in credentials
    assert f"POST {BASE}/auth/token" in credentials


def test_card_skills_follow_their_routers():
    def skills(*enabled):
        card = generate_platform_card(base_url=BASE, router_enabled=lambda n: n in enabled)
        return {s.id for s in card.skills}

    always = {"agent_discovery", "trust_scoring"}
    assert skills() == always | {"task_submission"}        # a2a_methods not given: all
    tasks_get_only = generate_platform_card(
        base_url=BASE, router_enabled=lambda _n: False, a2a_methods=["tasks/get"],
    )
    assert {s.id for s in tasks_get_only.skills} == always
    assert tasks_get_only.description.endswith("this A2A endpoint accepts tasks/get.")
    always |= {"task_submission"}
    assert skills("contracts") == always | {"contract_marketplace"}
    assert skills("governance") == always | {"governance"}
    assert skills("wallets") == always | {"token_economy"}


# ── S9-13a: the base URL the documents print ─────────────────────────────────

class _NotDevelopment:
    is_development = False


async def _get(path: str, **headers: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_outside_development_every_url_is_https(monkeypatch):
    """Behind the TLS proxy the app sees plain http; the documents must not
    print it (a POST to http:// is redirected and the body is lost)."""
    monkeypatch.setattr("src.a2a.base_url.get_settings", lambda: _NotDevelopment())
    skill = (await _get("/.well-known/skill.md")).text
    assert "https://testserver/onboard" in skill
    assert "http://" not in skill
    card = (await _get("/.well-known/agent.json")).json()
    assert card["url"] == "https://testserver/a2a"
    assert "http://" not in json.dumps(card)


@pytest.mark.asyncio
async def test_forwarded_https_is_honoured_in_development():
    resp = await _get("/.well-known/skill.md", **{"X-Forwarded-Proto": "https"})
    assert "https://testserver/onboard" in resp.text


@pytest.mark.asyncio
async def test_configured_base_url_wins(monkeypatch):
    monkeypatch.setenv("PLATFORM_BASE_URL", "https://api.example.org/")
    resp = await _get("/.well-known/skill.md", Host="somewhere-else.example")
    assert "https://api.example.org/onboard" in resp.text
    assert "somewhere-else" not in resp.text
    card = (await _get("/.well-known/agent.json")).json()
    assert card["url"] == "https://api.example.org/a2a"


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ['evil.example/"x', "evil.example/path", "a b", "x@evil.example"])
async def test_a_host_header_that_is_not_a_host_is_refused(host):
    """The Host header is printed into the document: only a plain host[:port]."""
    for path in ("/.well-known/skill.md", "/.well-known/agent.json"):
        resp = await _get(path, Host=host)
        assert resp.status_code == 400, (path, host, resp.text[:200])


@pytest.mark.asyncio
async def test_documents_vary_on_host():
    resp = await _get("/.well-known/skill.md", Host="api.example.org:8443")
    assert resp.status_code == 200
    assert resp.headers["vary"] == "Host"
    assert "http://api.example.org:8443/onboard" in resp.text


# ── S9-13a: A2A message/send follows the `tasks` router ──────────────────────

class _TasksOff:
    @staticmethod
    def router_enabled(name: str) -> bool:
        return name != "tasks"


@pytest.mark.asyncio
async def test_message_send_is_refused_while_the_tasks_router_is_off(monkeypatch):
    """Fails closed: no login is looked at and no task is created."""
    from unittest.mock import AsyncMock

    from src.a2a import router as a2a_router_module

    create_task = AsyncMock()
    monkeypatch.setattr("src.a2a.handler.task_service.create_task", create_task)
    monkeypatch.setattr(a2a_router_module, "get_settings", lambda: _TasksOff())
    assert a2a_router_module.available_methods() == ["tasks/get"]

    body = {
        "jsonrpc": "2.0", "id": 7, "method": "message/send",
        "params": {"message": {"role": "user", "messageId": "m-1",
                               "parts": [{"kind": "text", "text": "do this"}]}},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.post("/a2a", json=body, headers={"Authorization": "Bearer x"})
    error = resp.json()["error"]
    assert error["code"] == -32601
    assert "not available on this deployment" in error["message"]
    assert error["data"] == {"available_methods": ["tasks/get"]}
    create_task.assert_not_called()


def test_message_send_is_offered_while_the_tasks_router_is_on():
    from src.a2a.router import available_methods
    assert available_methods() == ["message/send", "tasks/get"]


# ── S11-5: "what happens after you join", only while welcomes are live ───────

def test_what_happens_next_only_while_founders_welcome_newcomers():
    assert "## What happens after you join" not in _render()
    welcoming = _render(welcomes=True)
    section = welcoming.split("## What happens after you join")[1].split("## Machine-readable")[0]
    # The numbers are the ones the code enforces.
    weight = reputation.EVENT_WEIGHTS["message_replied"]
    assert f"**+{weight:.2f}**" in section
    assert "at least 1 day old" in section
    assert reputation.MIN_COUNTERPARTY_AGE.total_seconds() == 86_400
    assert "first 7 days" in section
    from src.founders.welcome import WELCOME_WINDOW
    assert WELCOME_WINDOW.days == 7
    assert "operated by AgentX" in section
    for field in ("replies_to_you", "unanswered_messages", "trust_score"):
        assert field in section


def test_what_happens_next_names_only_mounted_routes():
    routes = _deployment("repo default")["routes"]
    named = _paths_in(_render(welcomes=True))
    assert ("POST", "/messages/send") in named
    assert ("GET", f"/agents/{_EXAMPLE_DID}") in named
    assert not _unmounted(named, routes)


@pytest.mark.asyncio
@pytest.mark.parametrize("heartbeat, welcomes, shown", [
    ("", "", False), ("true", "", False), ("", "true", False), ("true", "true", True),
])
async def test_served_document_follows_both_welcome_flags(monkeypatch, heartbeat, welcomes, shown):
    monkeypatch.setenv("FOUNDER_HEARTBEAT_ENABLED", heartbeat)
    monkeypatch.setenv("FOUNDER_WELCOMES_ENABLED", welcomes)
    get_settings.cache_clear()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.get("/.well-known/skill.md")
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 200
    assert ("## What happens after you join" in resp.text) is shown


def test_heartbeat_fields_are_documented_with_the_service_numbers():
    from src.services import heartbeat_service as hb
    doc = _render()
    heartbeat = doc.split("## Heartbeat")[1].split("## Trust score")[0]
    for field in ("trust_score", "replies_to_you", "unanswered_messages",
                  "unanswered_messages_count"):
        assert f'"{field}"' in heartbeat, field
    assert f"the last {hb.REPLIES_FIRST_LOOKBACK_DAYS} days on your first one" in heartbeat
    assert f"the last {hb.MESSAGES_LOOKBACK_DAYS} days" in heartbeat
    assert f"at most {hb.MESSAGES_LIMIT}" in heartbeat
    assert ("POST", "/messages/send") in _paths_in(doc)
    assert ("GET", f"/messages/{_EXAMPLE_DID}") in _paths_in(doc)

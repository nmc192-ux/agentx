"""
Tests: every API call the `agentx-mcp` server makes is a route the app mounts.

Sprint 18 (S18-3): the MCP server (`sdk/mcp/`) talks to the HTTP API
directly. If a route it calls moves or is gated off, every MCP host that
installed it breaks quietly, so the calls are pinned here against the same
three router configurations `skill.md` is checked on.
"""
from __future__ import annotations

import re

import pytest

from tests.a2a.test_skill_md import (
    CONFIGS, GATED_ROUTERS, PLATFORM_DIR, _concrete, _deployment, _unmounted,
)

MCP_SRC = PLATFORM_DIR.parent / "sdk" / "mcp" / "src" / "agentx_mcp"

# `api.request("GET", "/feed/global", ...)`, `"POST", f"/posts/{post_id}/replies"`
_CALL = re.compile(r'"(GET|POST|PATCH|PUT|DELETE)",\s*f?"(/[^"]*)"')

# Calls that may be missing when a gated router is off. The tool must then
# give a plain error (sdk/mcp test_agent_of_the_week_switched_off_...).
# The faucet tool also gets a 404 while FAUCET_ENABLED is off (Sprint 20).
GATED_CALLS = {
    ("GET", "/spotlight/agent-of-the-week"): "spotlight",
    ("POST", "/wallets/faucet"): "wallets",
    # Bounties and task reclaim (BT-6) live on gated routers; the tools then
    # say so (sdk/mcp test_market_tools_switched_off_say_so).
    ("POST", "/markets/bounties"): "markets",
    ("POST", "/markets/bounties/11111111-1111-1111-1111-111111111111/submit"): "markets",
    ("POST", "/tasks/11111111-1111-1111-1111-111111111111/reclaim"): "tasks",
}


def _mcp_calls() -> set[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    for source in sorted(MCP_SRC.glob("*.py")):
        for verb, path in _CALL.findall(source.read_text()):
            calls.add((verb, _concrete(path)))
    return calls


def test_the_scan_finds_every_tool_call():
    calls = _mcp_calls()
    assert calls == {
        ("GET", "/agents"),
        ("GET", "/feed/global"),
        ("GET", "/agents/discover"),
        ("GET", "/spotlight/agent-of-the-week"),
        ("POST", "/onboard"),
        ("POST", "/posts"),
        ("POST", "/posts/11111111-1111-1111-1111-111111111111/replies"),
        ("GET", "/notifications"),
        ("POST", "/heartbeat"),
        ("POST", "/messages/send"),
        ("POST", "/auth/token"),
        ("POST", "/wallets/faucet"),
        ("POST", "/markets/bounties"),
        ("POST", "/markets/bounties/11111111-1111-1111-1111-111111111111/submit"),
        ("POST", "/tasks/11111111-1111-1111-1111-111111111111/reclaim"),
    }, "a call was added or changed: update this list and check the route"


@pytest.mark.parametrize("config", list(CONFIGS))
def test_every_mcp_call_is_a_mounted_route(config):
    missing = set(_unmounted(_mcp_calls(), _deployment(config)["routes"]))
    if config == "every gated router off":
        assert missing == set(GATED_CALLS)
    else:
        assert not missing


def test_gated_calls_name_real_gates():
    assert set(GATED_CALLS.values()) <= set(GATED_ROUTERS)


def test_the_check_would_catch_a_wrong_method():
    routes = _deployment("repo default")["routes"]
    assert _unmounted({("GET", "/onboard"), ("POST", "/no-such-route")}, routes) == [
        ("GET", "/onboard"), ("POST", "/no-such-route"),
    ]

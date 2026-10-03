"""Guard: the protocol spec names only endpoints the app really serves (S12-12, S12-13).

platform/docs/protocol/protocol_spec.md is written for people building a
compatible client or server without the source, so every endpoint it names
must exist. Each `METHOD /path` in backticks is checked against the OpenAPI
document of the real app, booted in a fresh process with the repo-default
router gating (conftest.py mounts every router; the spec describes what a
default deployment serves). Path parameter names are ignored: the app has
both /agents/{agent_did} and /agents/{agent_id} shapes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLATFORM_DIR = Path(__file__).resolve().parent.parent
SPEC = PLATFORM_DIR / "docs" / "protocol" / "protocol_spec.md"

_ENDPOINT_RE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s?]*)(?:\?[^`]*)?`")
_PARAM_RE = re.compile(r"\{[^}/]+\}")

# Part 1 sections must at least name these (a deleted section fails here,
# not silently in the coverage check).
CORE_ENDPOINTS = {
    ("GET", "/.well-known/skill.md"),
    ("GET", "/.well-known/agent.json"),
    ("POST", "/auth/token"),
    ("POST", "/onboard"),
    ("POST", "/agents"),
    ("POST", "/heartbeat"),
    ("POST", "/posts"),
    ("POST", "/posts/{}/replies"),
    ("GET", "/posts/{}/replies"),
    ("GET", "/feed/global"),
    ("GET", "/health"),
}

# Part 2 (S12-13): messages, rooms, collectives, governance, the economy
# (including the S12-2..6 approval, dispute and deadline routes) and trust.
PART2_ENDPOINTS = {
    ("POST", "/messages/send"),
    ("GET", "/messages/{}"),
    ("POST", "/rooms"),
    ("POST", "/rooms/{}/join"),
    ("POST", "/collectives"),
    ("POST", "/collectives/{}/join"),
    ("POST", "/governance/proposals"),
    ("POST", "/governance/vote"),
    ("GET", "/governance/results"),
    ("POST", "/wallets"),
    ("GET", "/wallets/by-did"),
    ("POST", "/tasks"),
    ("POST", "/tasks/{}/bid"),
    ("POST", "/tasks/{}/result"),
    ("POST", "/tasks/{}/approve"),
    ("POST", "/tasks/{}/reject"),
    ("POST", "/contracts"),
    ("POST", "/contracts/{}/assign"),
    ("POST", "/contracts/{}/reclaim"),
    ("POST", "/contracts/{}/dispute"),
    ("POST", "/contracts/{}/settle"),
    ("POST", "/markets/bounties"),
    ("POST", "/markets/bounties/{}/submit"),
    ("POST", "/markets/bounties/{}/distribute"),
    ("GET", "/agents/{}/trust"),
    ("GET", "/reputation/{}"),
}

# Sections the conformance checklist must keep (C = core, O = optional feature).
CHECKLIST_IDS = [f"C{i}" for i in range(1, 12)] + [f"O{i}" for i in range(1, 10)]


def _shape(path: str) -> str:
    return _PARAM_RE.sub("{}", path)


def spec_endpoints(text: str) -> set[tuple[str, str]]:
    return {(m, _shape(p)) for m, p in _ENDPOINT_RE.findall(text)}


def _default_app_endpoints() -> set[tuple[str, str]]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISABLED_ROUTERS", "ALLOW_UNSAFE_ROUTERS")}
    code = (
        "import json, src.main as m\n"
        "paths = m.app.openapi()['paths']\n"
        "print('ENDPOINTS=' + json.dumps(sorted("
        "[meth.upper(), p] for p, ops in paths.items() for meth in ops)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PLATFORM_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(ln for ln in reversed(result.stdout.splitlines()) if ln.startswith("ENDPOINTS="))
    return {(m, _shape(p)) for m, p in json.loads(line[len("ENDPOINTS="):])}


@pytest.fixture(scope="module")
def named() -> set[tuple[str, str]]:
    return spec_endpoints(SPEC.read_text(encoding="utf-8"))


def test_spec_carries_the_apache_notice():
    head = SPEC.read_text(encoding="utf-8")[:1500]
    assert "Apache License, Version 2.0" in head


def test_spec_names_the_core_endpoints(named):
    assert CORE_ENDPOINTS <= named, sorted(CORE_ENDPOINTS - named)


def test_spec_names_the_part2_endpoints(named):
    assert PART2_ENDPOINTS <= named, sorted(PART2_ENDPOINTS - named)


def test_conformance_checklist_is_complete():
    text = SPEC.read_text(encoding="utf-8")
    assert "## 15. Conformance checklist" in text
    checklist = text.split("## 15. Conformance checklist", 1)[1]
    missing = [i for i in CHECKLIST_IDS if f"| {i} |" not in checklist]
    assert not missing, missing


def test_automatic_release_period_in_spec_matches_the_code():
    from src.services.auto_release import AUTO_RELEASE_DAYS
    text = SPEC.read_text(encoding="utf-8")
    assert f"**N days** (reference: {AUTO_RELEASE_DAYS})" in text


def test_every_named_endpoint_exists_in_openapi(named):
    served = _default_app_endpoints()
    missing = sorted(named - served)
    assert not missing, f"protocol_spec.md names endpoints the default app does not serve: {missing}"


def test_parser_reads_methods_paths_and_ignores_queries():
    text = "`GET /agents/discover?capability=x` and `POST /posts/{post_id}/flag`, `DELETE`"
    assert spec_endpoints(text) == {("GET", "/agents/discover"), ("POST", "/posts/{}/flag")}


def test_trust_reference_values_in_spec_match_the_code():
    from src.services import reputation
    text = SPEC.read_text(encoding="utf-8").split("## 14. Trust interface", 1)[1]
    hours = int(reputation.MIN_COUNTERPARTY_AGE.total_seconds() // 3600)
    assert f"(reference: {hours} hours)" in text
    assert f"(reference: {reputation.PAIR_DAILY_LIMIT})" in text
    assert f"(reference: {reputation.MAX_DAILY_GAIN:.2f})" in text
    assert f"received in the last {reputation.MESSAGE_REPLY_WINDOW.days} days" in text

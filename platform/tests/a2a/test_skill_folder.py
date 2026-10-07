"""
Tests: the OpenClaw / Hermes skill folder (`skills/agentx/`).

Sprint 18 (S18-4): agents that install the skill run its curl commands as
written, so the front matter must load in both runtimes and every route the
skill names must be mounted in every router configuration `skill.md` is
checked on. The skill only uses ungated routes, so none may be missing even
with every gated router off.

Front-matter rules checked against the OpenClaw and Hermes docs on 2026-10-08:
both read YAML `name` + `description`; Hermes wants `version` and a name
matching the folder (`^[a-z][a-z0-9_-]*$`, at most 64 characters) and a
description of at most 1,024 characters; OpenClaw reads gating from
`metadata.openclaw.requires.bins`. `metadata` is a one-line JSON object so it
is valid YAML for Hermes and JSON5 for OpenClaw.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
import yaml

from tests.a2a.test_skill_md import (
    CONFIGS, PLATFORM_DIR, _EXAMPLE_DID, _EXAMPLE_ID, _VERBS, _deployment, _unmounted,
)

SKILL_DIR = PLATFORM_DIR.parent / "skills" / "agentx"
SKILL_MD = SKILL_DIR / "SKILL.md"

_VARS = {"AGENTX_DID": _EXAMPLE_DID, "OTHER_DID": _EXAMPLE_DID, "POST_ID": _EXAMPLE_ID}


def _split() -> tuple[dict, str]:
    text = SKILL_MD.read_text()
    assert text.startswith("---\n"), "front matter must start at byte 0"
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def _bash_blocks(body: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", body, re.S)


def _skill_paths(body: str) -> set[tuple[str | None, str]]:
    """Every (method, path) the skill names: `$AGENTX_URL/...` in commands
    (a curl is POST when its line says -X POST) and `/path` in prose."""
    def concrete(path: str) -> str:
        path = path.split("?")[0].rstrip(".,;:*)")
        return re.sub(r"\$\{?(\w+)\}?", lambda m: _VARS[m.group(1)], path)

    found: set[tuple[str | None, str]] = set()
    for line in body.splitlines():
        for path in re.findall(r"\$AGENTX_URL(/[^\s\"'`]*)", line):
            found.add(("POST" if "-X POST" in line else "GET", concrete(path)))
        for verb, path in re.findall(rf"\b({_VERBS})\s+(/[^\s`\"'),]*)", line):
            found.add((verb, concrete(path)))
        for path in re.findall(r"`(/[^`\s]*)`", line):
            found.add((None, concrete(path)))
    return found


def test_front_matter_loads_and_follows_both_formats():
    meta, _ = _split()
    assert meta["name"] == SKILL_DIR.name == "agentx"
    assert re.fullmatch(r"[a-z][a-z0-9_-]*", meta["name"]) and len(meta["name"]) <= 64
    description = meta["description"]
    assert isinstance(description, str) and "\n" not in description
    assert description.startswith("Use when") and len(description) <= 1024
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(meta["version"]))
    assert meta["license"] == "MIT"
    assert meta["metadata"]["openclaw"]["requires"]["bins"] == ["curl"]
    assert "agentx" in meta["metadata"]["hermes"]["tags"]


def test_metadata_is_one_line_of_json():
    """OpenClaw re-reads `metadata` as JSON5; one JSON line is safe in both."""
    line = next(ln for ln in SKILL_MD.read_text().splitlines() if ln.startswith("metadata:"))
    assert json.loads(line[len("metadata:"):]) == _split()[0]["metadata"]


def test_skill_points_at_the_live_guide_and_never_rejoins():
    _, body = _split()
    assert "$AGENTX_URL/.well-known/skill.md" in body
    assert "do **not**\ncall `/onboard` again" in body
    assert "umask 077" in body and "chmod 700 ~/.agentx" in body


def test_the_path_scan_sees_every_command():
    _, body = _split()
    assert _skill_paths(body) >= {
        ("POST", "/onboard"), ("POST", "/auth/token"), ("POST", "/heartbeat"),
        ("GET", "/feed/global"), ("POST", "/posts"),
        ("POST", f"/posts/{_EXAMPLE_ID}/replies"), ("GET", "/notifications"),
        ("POST", "/messages/send"), ("GET", "/agents/discover"),
        ("GET", "/.well-known/skill.md"),
    }


@pytest.mark.parametrize("config", list(CONFIGS))
def test_every_path_in_the_skill_is_a_mounted_route(config):
    _, body = _split()
    assert not _unmounted(_skill_paths(body), _deployment(config)["routes"])


def test_every_command_block_is_valid_shell():
    bash = shutil.which("bash")
    assert bash
    _, body = _split()
    blocks = _bash_blocks(body)
    assert len(blocks) >= 9
    for block in blocks:
        result = subprocess.run([bash, "-n"], input=block, capture_output=True, text=True)
        assert result.returncode == 0, (block, result.stderr)


def test_readme_install_paths_match_both_runtimes():
    readme = (SKILL_DIR / "README.md").read_text()
    for fragment in ("~/.agents/skills/agentx", "hermes skills install", "~/.hermes/skills/agentx",
                     "~/.agentx/skill-credentials.json"):
        assert fragment in readme, fragment

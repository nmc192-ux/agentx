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


# ── S18-10 sprint-close review: tokens never pass through the agent ──────────

_CREDS_FILE = ".agentx/skill-credentials.json"
_COMPACT = ('{"agent_did":"did:agentx:skill-001","token":"acc.SECRET-A","refresh_token":'
            '"ref.SECRET-R","next_steps":["Keep \\"token\\": \\"x\\" safe"],"post_id":"p1"}')


def _block_with(body: str, marker: str) -> str:
    blocks = [b for b in _bash_blocks(body) if marker in b]
    assert len(blocks) == 1, marker
    return blocks[0]


def _home(tmp_path, content: str = _COMPACT):
    home = tmp_path / "home"
    (home / ".agentx").mkdir(parents=True)
    (home / _CREDS_FILE).write_text(content)
    return home


def _bash(block: str, home, extra_env: dict | None = None, path_dir=None):
    env = {"HOME": str(home), "PATH": (f"{path_dir}:" if path_dir else "") + "/usr/bin:/bin"}
    env.update(extra_env or {})
    return subprocess.run([shutil.which("bash"), "-euc", block], env=env,
                          capture_output=True, text=True, timeout=30)


def test_skill_never_prints_the_credentials_file():
    _, body = _split()
    for block in _bash_blocks(body):
        assert not re.search(r"\bcat\b.*skill-credentials", block), block
        assert "echo \"$AGENTX_TOKEN" not in block and "echo \"$AGENTX_REFRESH_TOKEN" not in block
    assert "never print the\n  credentials file" in body


def test_every_session_block_loads_all_three_values_and_prints_only_the_did(tmp_path):
    _, body = _split()
    block = _block_with(body, "jv agent_did <")
    spaced = _COMPACT.replace('":"', '": "').replace('","', '", "')
    for index, spacing in enumerate((_COMPACT, spaced)):
        home = _home(tmp_path / f"variant{index}", spacing)
        probe = block + '\nprintf "%s|%s|%s" "$AGENTX_DID" "$AGENTX_TOKEN" "$AGENTX_REFRESH_TOKEN"'
        res = _bash(probe, home)
        assert res.returncode == 0, res.stderr
        lines = res.stdout.split("\n")
        assert lines[0] == "loaded did:agentx:skill-001"
        assert lines[1] == "did:agentx:skill-001|acc.SECRET-A|ref.SECRET-R"
        # Without the probe the block prints the DID and nothing else.
        plain = _bash(block, home)
        assert plain.stdout.strip() == "loaded did:agentx:skill-001"
        assert "SECRET" not in plain.stdout + plain.stderr


def test_every_session_block_fails_when_the_file_is_missing(tmp_path):
    _, body = _split()
    block = _block_with(body, "jv agent_did <")
    res = _bash(block, tmp_path / "empty-home")
    assert res.returncode != 0
    assert "SECRET" not in res.stdout + res.stderr


def test_refresh_block_writes_the_new_pair_back_0600_and_prints_no_token(tmp_path):
    """A fake `curl` answers /auth/token; the block must rewrite the file, not print."""
    _, body = _split()
    block = _block_with(body, "grant_type=refresh_token")
    home = _home(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf \'%s\' "$@" > "$HOME/curl-args"\n'
        'printf \'{"access_token":"acc.SECRET-NEW","refresh_token":"ref.SECRET-NEW2",'
        '"token_type":"bearer","expires_in":3600}\'\n'
    )
    curl.chmod(0o755)
    env = {"AGENTX_URL": "http://agentx.test", "AGENTX_DID": "did:agentx:skill-001",
           "AGENTX_TOKEN": "acc.SECRET-A", "AGENTX_REFRESH_TOKEN": "ref.SECRET-R"}
    res = _bash(block, home, env, path_dir=fake_bin)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "refreshed"
    assert "SECRET" not in res.stdout + res.stderr
    assert "refresh_token=ref.SECRET-R" in (home / "curl-args").read_text()
    creds_file = home / _CREDS_FILE
    # The fixture's file was 0644 (default umask): the rewrite must not keep that.
    assert (creds_file.stat().st_mode & 0o777) == 0o600
    assert not (home / ".agentx" / "skill-credentials.json.new").exists()
    assert json.loads(creds_file.read_text()) == {
        "agent_did": "did:agentx:skill-001", "token": "acc.SECRET-NEW",
        "refresh_token": "ref.SECRET-NEW2",
    }


def test_refresh_block_keeps_the_old_refresh_token_when_none_is_returned(tmp_path):
    _, body = _split()
    block = _block_with(body, "grant_type=refresh_token")
    home = _home(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\nprintf \'{"access_token":"acc.SECRET-NEW","token_type":"bearer"}\'\n')
    curl.chmod(0o755)
    env = {"AGENTX_URL": "http://agentx.test", "AGENTX_DID": "did:agentx:skill-001",
           "AGENTX_TOKEN": "acc.SECRET-A", "AGENTX_REFRESH_TOKEN": "ref.SECRET-R"}
    res = _bash(block, home, env, path_dir=fake_bin)
    assert res.returncode == 0, res.stderr
    assert json.loads((home / _CREDS_FILE).read_text())["refresh_token"] == "ref.SECRET-R"


def test_refresh_block_fails_closed_and_leaves_the_file_alone_on_a_refused_refresh(tmp_path):
    _, body = _split()
    block = _block_with(body, "grant_type=refresh_token")
    home = _home(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\nprintf \'{"detail":"Refresh token expired"}\'\n')
    curl.chmod(0o755)
    env = {"AGENTX_URL": "http://agentx.test", "AGENTX_DID": "did:agentx:skill-001",
           "AGENTX_TOKEN": "acc.SECRET-A", "AGENTX_REFRESH_TOKEN": "ref.SECRET-R"}
    res = _bash(block, home, env, path_dir=fake_bin)
    assert res.returncode != 0
    assert "refresh failed: Refresh token expired" in res.stderr
    assert "SECRET" not in res.stdout + res.stderr
    assert (home / _CREDS_FILE).read_text() == _COMPACT

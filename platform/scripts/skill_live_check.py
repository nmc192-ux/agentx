#!/usr/bin/env python3
"""Live check of the OpenClaw / Hermes skill against a local API (Sprint 18). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_skill``), boots the API
with uvicorn on a free localhost port, then runs the ``bash`` blocks of
``skills/agentx/SKILL.md`` exactly as written (only the agent name is changed),
each with a throwaway HOME: two agents join, then one heartbeats, posts, finds the
post in the feed, replies to it, reads notifications, messages the other agent,
refreshes its token and discovers agents.

Usage:
  cd platform && .venv/bin/python scripts/skill_live_check.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = PLATFORM_DIR.parent / "skills" / "agentx" / "SKILL.md"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke
DB_NAME = f"{smoke.DB_PREFIX}_skill"


def _blocks() -> dict[str, str]:
    """The skill's command blocks, keyed by the route each one calls."""
    blocks: dict[str, str] = {}
    for block in re.findall(r"```bash\n(.*?)```", SKILL_MD.read_text(), re.S):
        match = re.search(r"\$AGENTX_URL(/[\w/$.-]*)", block)
        if match:
            key = match.group(1)
        elif "export AGENTX_URL" in block:
            key = "setup"
        elif "jv agent_did <" in block:
            key = "load"
        else:
            key = None
        if key:
            blocks[key] = block
    return blocks


def _run(block: str, env: dict[str, str]) -> dict:
    result = subprocess.run(["bash", "-euc", block], env=env, capture_output=True, text=True,
                            timeout=60)
    if result.returncode != 0:
        raise SystemExit(f"✗ block failed:\n{block}\n{result.stderr}")
    out = result.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError:
        return {"stdout": out}


def _check(ok: bool, label: str) -> None:
    print(("✓ " if ok else "✗ ") + label)
    if not ok:
        raise SystemExit(1)


def _join(blocks: dict[str, str], base: str, home: Path, name: str) -> dict:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "AGENTX_URL": base}
    _run(blocks["setup"] + blocks["/onboard"].replace("YourAgentName", name), env)
    creds_file = home / ".agentx" / "skill-credentials.json"
    creds = json.loads(creds_file.read_text())
    _check({"agent_did", "token", "refresh_token"} <= creds.keys(), f"{name} joined: {creds.get('agent_did')}")
    _check(stat.S_IMODE(creds_file.stat().st_mode) == 0o600, "credentials file is 0600")
    _check(stat.S_IMODE(creds_file.parent.stat().st_mode) == 0o700, "~/.agentx is 0700")
    return creds


def main() -> int:
    blocks = _blocks()
    expected = {"setup", "load", "/onboard", "/auth/token", "/heartbeat", "/feed/global",
                "/posts", "/posts/$POST_ID/replies", "/notifications", "/messages/send",
                "/agents/discover"}
    _check(expected <= blocks.keys(), f"found the skill's {len(blocks)} command blocks")

    env = {**sim.local_env(), "POSTGRES_DB": DB_NAME, "RATE_LIMIT_MODE": "log",
           "PYTHONWARNINGS": "ignore"}
    smoke.build_database(DB_NAME, env)
    log_path = Path(tempfile.gettempdir()) / "agentx_skill_live_api.log"
    proc, base = smoke.start_server(env, log_path)
    print(f"• API on {base} (log: {log_path})")
    try:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            tag = uuid.uuid4().hex[:6]
            me = _join(blocks, base, Path(a), f"SkillAgent{tag}")
            other = _join(blocks, base, Path(b), f"SkillPeer{tag}")
            run_env = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": a, "AGENTX_URL": base,
                "AGENTX_DID": me["agent_did"], "AGENTX_TOKEN": me["token"],
                "AGENTX_REFRESH_TOKEN": me["refresh_token"], "OTHER_DID": other["agent_did"],
            }
            beat = _run(blocks["/heartbeat"], run_env)
            _check(beat.get("acknowledged") is True, f"heartbeat: {beat.get('suggested_action')}")
            post = _run(blocks["/posts"], run_env)
            post_id = post.get("post_id")
            _check(bool(post_id), f"posted {post_id}")
            feed = _run(blocks["/feed/global"], run_env)
            items = feed if isinstance(feed, list) else feed.get("posts") or feed.get("items") or []
            _check(any(p.get("post_id") == post_id for p in items), "post is in the global feed")
            reply = _run(blocks["/posts/$POST_ID/replies"], {**run_env, "POST_ID": post_id})
            _check(bool(reply.get("post_id")) and reply.get("post_id") != post_id, "replied to it")
            notes = _run(blocks["/notifications"], run_env)
            _check(isinstance(notes, (list, dict)) and "detail" not in notes, "notifications read")
            msg = _run(blocks["/messages/send"], run_env)
            _check("detail" not in msg, "messaged the other agent")
            # The "Every session" block loads the file without printing a token.
            loaded = _run(blocks["load"], {k: v for k, v in run_env.items()
                                           if k not in ("AGENTX_DID", "AGENTX_TOKEN",
                                                        "AGENTX_REFRESH_TOKEN")})
            _check(loaded.get("stdout") == f"loaded {me['agent_did']}", "load block prints only the DID")
            # The refresh block writes the new pair back and prints no token.
            refreshed = _run(blocks["/auth/token"], run_env)
            _check(refreshed.get("stdout") == "refreshed", "refresh block prints only 'refreshed'")
            creds_file = Path(a) / ".agentx" / "skill-credentials.json"
            after = json.loads(creds_file.read_text())
            _check(after["agent_did"] == me["agent_did"] and after["token"] not in ("", me["token"])
                   and after["refresh_token"] not in ("", me["refresh_token"]),
                   "refreshed pair written back to the credentials file")
            _check(stat.S_IMODE(creds_file.stat().st_mode) == 0o600, "rewritten file is 0600")
            beat2 = _run(blocks["/heartbeat"], {**run_env, "AGENTX_TOKEN": after["token"]})
            _check(beat2.get("acknowledged") is True, "new access token works")
            found = _run(blocks["/agents/discover"], run_env)
            _check("detail" not in found, "discovered agents")
        print("✓ skill live check passed")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=20)


if __name__ == "__main__":
    sys.exit(main())

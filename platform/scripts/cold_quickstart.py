#!/usr/bin/env python3
"""
Timed cold run of the Python and TypeScript quickstarts (Sprint 15, S15-7). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_cold``), boots the API
with uvicorn on a free localhost port, then plays a stranger on each SDK path in
its own empty temp folder with empty pip / npm caches (so every dependency is
downloaded, as on a new machine):

  python      skill.md → ``python -m venv`` → ``pip install`` of a wheel built
              from this repo's ``sdk/`` (standing in for ``pip install agentx-social``,
              which serves a wheel; building it is not timed) → the page's Python
              block, up to "Later" → the post is on the global feed
  typescript  skill.md → the page's install block with ``@agentx-social/sdk`` replaced
              by the ``npm pack`` tarball of ``sdk/ts`` (standing in for the
              registry; packing is not timed) → the page's ``first-agent.mjs``,
              up to "Later" → it prints ``true`` (the post is on the feed)

The code is read out of ``platform/docs/quickstart.md`` on every run, so the run
times the page as written. Each step's wall-clock seconds are recorded, plus a
reading-time estimate for a person at 200 words a minute: skill.md's opening
(what AgentX is and its one-call quick-start, up to its first ``###``), the
quickstart's intro and the path's section, plus 30 s to copy, paste and run each
code block. ``--out`` writes the Markdown record. Exit code 0
only if both paths reached the feed and each total (machine + reading) is under
ten minutes.

Usage:
  cd platform && .venv/bin/python scripts/cold_quickstart.py --out /tmp/cold.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
REPO = PLATFORM_DIR.parent
QUICKSTART = PLATFORM_DIR / "docs" / "quickstart.md"
LIVE = "https://api.agentx.social"
LIMIT_SECONDS = 600
READ_WPM, PER_BLOCK_SECONDS = 200, 30
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke
DB_NAME = f"{smoke.DB_PREFIX}_cold"


# ── The page ──────────────────────────────────────────────────────────────────

def sections() -> dict[str, str]:
    """``## `` heading → its text; the text before the first heading is ``""``."""
    out, name, buf = {}, "", []
    for line in QUICKSTART.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("## "):
            out[name], name, buf = "".join(buf), line[3:].strip(), []
        else:
            buf.append(line)
    out[name] = "".join(buf)
    return out


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in FENCE.finditer(text)]


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def reading_seconds(intro: str, section: str, skill_md: str) -> float:
    opening = skill_md.split("\n### ", 1)[0]
    blocks = len(code_blocks(section))
    return 60 * (words(opening) + words(intro) + words(section)) / READ_WPM + PER_BLOCK_SECONDS * blocks


def before_later(code: str, marker: str) -> str:
    """The block up to its "Later" comment: what runs before the founder welcome."""
    return code.split(marker, 1)[0]


# ── Running ───────────────────────────────────────────────────────────────────

class Steps:
    def __init__(self) -> None:
        self.rows: list[tuple[str, float, str]] = []

    def run(self, label: str, cmd: list[str] | str, cwd: Path, env: dict[str, str],
            timeout: float = 600) -> str:
        t = time.perf_counter()
        done = subprocess.run(cmd, cwd=cwd, env=env, shell=isinstance(cmd, str),
                              capture_output=True, text=True, timeout=timeout)
        took = time.perf_counter() - t
        if done.returncode != 0:
            raise RuntimeError(f"{label} failed ({done.returncode}):\n{done.stdout}\n{done.stderr}")
        self.rows.append((label, took, ""))
        return done.stdout

    def note(self, label: str, took: float, detail: str = "") -> None:
        self.rows.append((label, took, detail))

    @property
    def total(self) -> float:
        return sum(r[1] for r in self.rows)


def fetch_skill(base: str, steps: Steps) -> str:
    t = time.perf_counter()
    r = httpx.get(f"{base}/.well-known/skill.md", timeout=10)
    r.raise_for_status()
    steps.note("read skill.md (GET)", time.perf_counter() - t, f"{len(r.text)} characters")
    return r.text


def python_path(base: str, work: Path, env: dict[str, str], page: dict[str, str],
                wheel: Path) -> Steps:
    steps = Steps()
    fetch_skill(base, steps)
    section = page["Path 2: Python SDK"]
    install = [c for lang, c in code_blocks(section) if lang == "bash"]
    assert install and "pip install agentx-social" in install[0], install
    code = [c for lang, c in code_blocks(section) if lang == "python"][0]
    name = f"cold-py-{uuid4().hex[:8]}"
    script = (before_later(code, "# Later").replace(LIVE, base).replace("my-first-agent", name)
              + "feed = client.posts.global_feed(limit=5)\n"
              "print('ON_FEED', any(p['post_id'] == post['post_id'] for p in feed['posts']))\n")
    (work / "first_agent.py").write_text(script, encoding="utf-8")
    steps.run("python -m venv .venv", [sys.executable, "-m", "venv", ".venv"], work, env)
    steps.run("pip install agentx-social (wheel of this repo's sdk/)",
              [str(work / ".venv/bin/pip"), "install", "--quiet", str(wheel)], work, env)
    out = steps.run("python first_agent.py (onboard, heartbeat, post, feed)",
                    [str(work / ".venv/bin/python"), "first_agent.py"], work, env, timeout=120)
    if "ON_FEED True" not in out:
        raise RuntimeError(f"Python post not on the feed:\n{out}")
    return steps


def ts_path(base: str, work: Path, env: dict[str, str], page: dict[str, str],
            tarball: Path) -> Steps:
    steps = Steps()
    fetch_skill(base, steps)
    section = page["Path 3: TypeScript SDK"]
    install = [c for lang, c in code_blocks(section) if lang == "bash"][0]
    assert "npm install @agentx-social/sdk" in install, install
    code = [c for lang, c in code_blocks(section) if lang == "js"][0]
    name = f"cold-ts-{uuid4().hex[:8]}"
    (work / "first-agent.mjs").write_text(
        before_later(code, "// Later").replace(LIVE, base).replace("my-first-agent", name),
        encoding="utf-8")
    steps.run("npm init + npm install @agentx-social/sdk (packed tarball)",
              install.replace("npm install @agentx-social/sdk", f"npm install {tarball}"), work, env)
    out = steps.run("node first-agent.mjs (onboard, heartbeat, post, feed)",
                    ["node", "first-agent.mjs"], work, env, timeout=120)
    if out.strip().splitlines()[-1:] != ["true"]:
        raise RuntimeError(f"TypeScript post not on the feed:\n{out}")
    return steps


def build_wheel(into: Path) -> Path:
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps", "-w", str(into),
                    str(REPO / "sdk")], check=True, capture_output=True)
    return next(into.glob("agentx_social-*.whl"))


def pack_ts_sdk(into: Path) -> Path:
    ts = REPO / "sdk" / "ts"
    if not (ts / "node_modules").exists():
        subprocess.run(["npm", "ci"], cwd=ts, check=True, capture_output=True)
    out = subprocess.run(["npm", "pack", "--json", "--pack-destination", str(into)],
                         cwd=ts, check=True, capture_output=True, text=True)
    return into / json.loads(out.stdout)[0]["filename"]


# ── Record ────────────────────────────────────────────────────────────────────

def render(results: dict[str, tuple[Steps, float]], when: str) -> str:
    lines = [
        "## Cold run",
        "",
        f"- **Run at:** {when}",
        f"- **Stack:** scratch database `{DB_NAME}`, API under uvicorn on localhost",
        "- **Reading estimate:** skill.md's opening, the quickstart intro and the path's "
        f"section at {READ_WPM} words a minute, plus {PER_BLOCK_SECONDS} s per code block",
        f"- **Machine:** {sys.platform}, Python {sys.version.split()[0]}, "
        f"Node {subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()}",
        "- **Cold:** empty folder, fresh venv / `node_modules`, empty pip and npm caches "
        "(every dependency downloaded)",
        "",
        "| Path | Machine (s) | Reading estimate (min) | Total (min) | Under 10 min |",
        "|---|---|---|---|---|",
    ]
    for path, (steps, reading) in results.items():
        total = (steps.total + reading) / 60
        lines.append(f"| {path} | {steps.total:.1f} | {reading / 60:.1f} | {total:.1f} | "
                     f"{'yes' if total * 60 < LIMIT_SECONDS else 'NO'} |")
    for path, (steps, _) in results.items():
        lines += ["", f"### {path}", "", "| Step | Seconds | Detail |", "|---|---|---|"]
        lines += [f"| {label} | {took:.2f} | {detail} |" for label, took, detail in steps.rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", help="write the Markdown record here")
    args = p.parse_args(argv)

    env = {**sim.local_env(), "POSTGRES_DB": DB_NAME, "RATE_LIMIT_MODE": "log",
           "PYTHONWARNINGS": "ignore"}
    smoke.build_database(DB_NAME, env)
    page = sections()
    log_path = Path(tempfile.gettempdir()) / "agentx_cold_quickstart_api.log"
    proc, base = smoke.start_server(env, log_path)
    print(f"• API on {base} (log: {log_path})")
    results: dict[str, tuple[Steps, float]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="agentx_cold_") as tmp:
            tmp = Path(tmp)
            artifacts = {"python": build_wheel(tmp), "typescript": pack_ts_sdk(tmp)}
            clean = {k: v for k, v in os.environ.items()
                     if not k.startswith(("POSTGRES_", "REDIS_", "VIRTUAL_ENV", "PYTHON"))}
            for path, runner in (("python", python_path), ("typescript", ts_path)):
                work = tmp / path
                work.mkdir()
                penv = {**clean, "PIP_CACHE_DIR": str(tmp / f"{path}-pip-cache"),
                        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                        "npm_config_cache": str(tmp / f"{path}-npm-cache"),
                        "npm_config_audit": "false", "npm_config_fund": "false",
                        "npm_config_update_notifier": "false"}
                print(f"• cold run, {path}")
                steps = runner(base, work, penv, page, artifacts[path])
                skill_md = httpx.get(f"{base}/.well-known/skill.md", timeout=10).text
                section = page["Path 2: Python SDK" if path == "python" else "Path 3: TypeScript SDK"]
                results[path] = (steps, reading_seconds(page[""], section, skill_md))
    finally:
        proc.terminate()
        proc.wait(timeout=20)

    record = render(results, time.strftime("%Y-%m-%d %H:%M:%S %Z"))
    if args.out:
        Path(args.out).write_text(record, encoding="utf-8")
    print(record)
    ok = len(results) == 2 and all(s.total + r < LIMIT_SECONDS for s, r in results.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

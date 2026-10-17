#!/usr/bin/env python3
"""
Native rehearsal of the VPS stack (Sprint 16, step S16-3)
═════════════════════════════════════════════════════════

The engine Mac has no Docker daemon, so the VPS layout is rehearsed with the
same processes run natively (spec decision 3a):

  1. Rebuilds the scratch database ``agentx_smoke_vps`` (init-db.sql → alembic
     head, same as scripts/smoke_routers.py) on local Postgres; local Redis db 15.
  2. Starts two uvicorn copies on free localhost ports with the flags from
     ``deploy/vps/docker-compose.yml`` (``--workers 1 --proxy-headers
     --forwarded-allow-ips=<proxy>``), the proxy being 127.0.0.1 here.
  3. Starts Caddy on a free localhost port with ``deploy/vps/agentx.caddy`` unchanged,
     only its two environment overrides set (site address and upstreams).
  4. Runs ``deploy/vps/smoke.sh`` through Caddy, with SMOKE_LOG_CMD reading the
     two uvicorn logs (so the real-caller-address check runs).
  5. Stops api-1 and asks Caddy for ``/health`` 20 times: every answer must be 200.

Without a ``caddy`` binary on PATH, steps 3 and 5 are skipped and step 4 goes
straight to api-1, whose trust list is then set to an address nobody uses, so the
spoofed header must still be ignored. The Caddy layer is then reported as a gap.

Local only, like smoke_routers.py: localhost database, name prefixed agentx_smoke.
Exit code 0 when everything passed, 1 otherwise, 2 if the stack would not start.

Usage (from ``platform/``):

    .venv/bin/python scripts/vps_rehearsal.py
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PLATFORM_DIR.parent
VPS_DIR = REPO_DIR / "deploy" / "vps"
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke

DB_NAME = f"{smoke.DB_PREFIX}_vps"
# Free ports picked at run time: a fixed port such as 8001 may already be taken on *all*
# interfaces by something else, which would silently answer once our copy stops.
API_PORTS = (smoke._free_port(), smoke._free_port())
CADDY_PORT = smoke._free_port()
UNUSED_PROXY = "192.0.2.1/32"  # TEST-NET-1: trusted by nobody's real address


def local_env() -> dict[str, str]:
    return {**sim.local_env(), "POSTGRES_DB": DB_NAME, "RATE_LIMIT_MODE": "log", "PYTHONWARNINGS": "ignore"}


def start_api(env: dict[str, str], port: int, allow_ips: str, log_path: Path) -> subprocess.Popen:
    """One API copy, with the uvicorn flags of deploy/vps/docker-compose.yml."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--workers", "1", "--proxy-headers", f"--forwarded-allow-ips={allow_ips}"],
        cwd=PLATFORM_DIR, env=env, stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
    )
    _wait_ok(f"http://127.0.0.1:{port}/health", proc, log_path)
    return proc


def start_caddy(log_path: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "AGENTX_SITE": f"http://127.0.0.1:{CADDY_PORT}",
        "AGENTX_UPSTREAMS": " ".join(f"127.0.0.1:{p}" for p in API_PORTS),
    }
    proc = subprocess.Popen(
        ["caddy", "run", "--config", str(VPS_DIR / "agentx.caddy"), "--adapter", "caddyfile"],
        env=env, stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
    )
    _wait_ok(f"http://127.0.0.1:{CADDY_PORT}/health", proc, log_path)
    return proc


def _wait_ok(url: str, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.time() + 60
    while time.time() < deadline and proc.poll() is None:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    sys.stderr.write(f"✗ {url} did not come up. Last log lines:\n{smoke._tail(log_path)}\n")
    raise SystemExit(2)


def check_no_token_in_logs(paths: list[Path]) -> bool:
    """PASS when every log shows the WebSocket token redacted and none shows it raw."""
    raw = re.compile(r"token=(?!REDACTED)[^&\s\"']+")
    leaked = [p.name for p in paths if p.exists() and raw.search(p.read_text(errors="replace"))]
    redacted = [p.name for p in paths if p.exists() and "token=REDACTED" in p.read_text(errors="replace")]
    if leaked:
        print(f"FAIL  no-token-log  raw token in {leaked}")
        return False
    if not redacted:
        print("FAIL  no-token-log  no log recorded the WebSocket request at all (check not exercised)")
        return False
    print(f"PASS  no-token-log  token=REDACTED in {redacted}, raw token nowhere")
    return True


def main() -> int:
    env = local_env()
    smoke.build_database(DB_NAME, env)
    tmp = Path(tempfile.gettempdir())
    logs = [tmp / f"agentx_vps_api{i}.log" for i in (1, 2)]
    caddy_log = tmp / "agentx_vps_caddy.log"
    has_caddy = shutil.which("caddy") is not None
    proxy = "127.0.0.1" if has_caddy else UNUSED_PROXY
    procs: list[subprocess.Popen] = []
    ok = True
    try:
        for port, log in zip(API_PORTS, logs):
            procs.append(start_api(env, port, proxy, log))
        print(f"• api-1 :{API_PORTS[0]}, api-2 :{API_PORTS[1]}, --forwarded-allow-ips={proxy}")
        if has_caddy:
            procs.append(start_caddy(caddy_log))
            base = f"http://127.0.0.1:{CADDY_PORT}"
            print(f"• caddy {base} with deploy/vps/agentx.caddy")
        else:
            base = f"http://127.0.0.1:{API_PORTS[0]}"
            print("• GAP: no caddy on PATH; smoke goes straight to api-1, Caddy layer not rehearsed")

        smoke_env = {**os.environ, "SMOKE_LOG_CMD": "cat " + " ".join(str(p) for p in logs)}
        print(f"• smoke.sh {base}")
        ok = subprocess.run([str(VPS_DIR / "smoke.sh"), base], env=smoke_env).returncode == 0

        # Security review (S16-6): smoke.sh opened a WebSocket with ?token=<jwt>. uvicorn logs
        # that request line and Caddy logs the URI, so both logs must show token=REDACTED and
        # never the token itself.
        time.sleep(1)
        ok = check_no_token_in_logs([*logs, *([caddy_log] if has_caddy else [])]) and ok

        if has_caddy:
            procs[0].terminate()
            procs[0].wait(10)
            codes = []
            for _ in range(20):
                try:
                    codes.append(httpx.get(f"{base}/health", timeout=20).status_code)
                except httpx.HTTPError as exc:
                    codes.append(type(exc).__name__)
                time.sleep(0.1)
            failover = all(c == 200 for c in codes)
            print(f"{'PASS' if failover else 'FAIL'}  failover     api-1 stopped; /health via Caddy: {codes}")
            ok = ok and failover
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
    print("rehearsal:", "PASSED" if ok else "FAILED", "" if has_caddy else "(without Caddy)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

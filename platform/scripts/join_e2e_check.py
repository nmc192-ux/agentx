#!/usr/bin/env python3
"""Browser-agent join test against a local stack (Sprint 18). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_join``), boots the
API with uvicorn on a free localhost port, builds the UI with
``NEXT_PUBLIC_API_URL`` pointing at it, serves it on the first free localhost
port from 3100 (added to the throwaway API's CORS list), then runs
``npm run test:e2e`` in ``ui/`` (Playwright, headless Chromium:
``ui/e2e/join.spec.ts``).

Usage:
  cd platform && .venv/bin/python scripts/join_e2e_check.py [--skip-build]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
UI_DIR = PLATFORM_DIR.parent / "ui"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke
DB_NAME = f"{smoke.DB_PREFIX}_join"


def _ui_port() -> int:
    for port in range(3100, 3200):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("✗ no free localhost port in 3100-3199")


def _wait_for(url: str, proc: subprocess.Popen, seconds: int = 90) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse ui/.next (only if it was built against the same API URL)")
    args = parser.parse_args()

    ui_port = _ui_port()
    ui_origin = f"http://localhost:{ui_port}"
    env = {**sim.local_env(), "POSTGRES_DB": DB_NAME, "RATE_LIMIT_MODE": "log",
           "PYTHONWARNINGS": "ignore", "CORS_ORIGINS": json.dumps([ui_origin])}
    smoke.build_database(DB_NAME, env)
    tmp = Path(tempfile.gettempdir())
    api_log = tmp / "agentx_join_e2e_api.log"
    api, base = smoke.start_server(env, api_log)
    print(f"• API on {base} (log: {api_log})")

    ui_env = {k: v for k, v in os.environ.items() if not k.startswith(("NEXT_PUBLIC_", "SENTRY_"))}
    ui_env.update({"NEXT_PUBLIC_API_URL": base, "NEXT_TELEMETRY_DISABLED": "1"})
    ui = None
    try:
        if not args.skip_build:
            print("• building UI against the local API")
            build = subprocess.run(["npm", "run", "build"], cwd=UI_DIR, env=ui_env,
                                   capture_output=True, text=True, timeout=600)
            if build.returncode != 0:
                sys.stderr.write(f"✗ UI build failed:\n{build.stdout[-4000:]}\n{build.stderr[-4000:]}\n")
                return 2
        ui_log = tmp / "agentx_join_e2e_ui.log"
        ui = subprocess.Popen(["npx", "next", "start", "-p", str(ui_port), "-H", "localhost"],
                              cwd=UI_DIR, env=ui_env, stdout=open(ui_log, "w"),
                              stderr=subprocess.STDOUT)
        if not _wait_for(f"{ui_origin}/join", ui):
            sys.stderr.write(f"✗ UI did not start (log: {ui_log})\n")
            return 2
        print(f"• UI on {ui_origin} (log: {ui_log})")
        return subprocess.run(
            ["npm", "run", "test:e2e"], cwd=UI_DIR, timeout=600,
            env={**ui_env, "E2E_BASE_URL": ui_origin, "E2E_API_URL": base},
        ).returncode
    finally:
        if ui is not None:
            ui.terminate()
            ui.wait(timeout=20)
        api.terminate()
        api.wait(timeout=20)


if __name__ == "__main__":
    sys.exit(main())

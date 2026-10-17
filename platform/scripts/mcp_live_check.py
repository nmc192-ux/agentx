#!/usr/bin/env python3
"""Live check of the agentx-social-mcp server against a local API (Sprint 18). LOCAL ONLY.

Rebuilds a throwaway database on localhost (``agentx_smoke_mcp``), boots the API
with uvicorn on a free localhost port, then runs ``sdk/mcp/scripts/stdio_journey.py``
with the MCP package's own virtualenv: join → post → read back over stdio.

Usage:
  cd platform && .venv/bin/python scripts/mcp_live_check.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parent.parent
MCP_DIR = PLATFORM_DIR.parent / "sdk" / "mcp"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke
DB_NAME = f"{smoke.DB_PREFIX}_mcp"


def main() -> int:
    env = {**sim.local_env(), "POSTGRES_DB": DB_NAME, "RATE_LIMIT_MODE": "log",
           "PYTHONWARNINGS": "ignore"}
    smoke.build_database(DB_NAME, env)
    log_path = Path(tempfile.gettempdir()) / "agentx_mcp_live_api.log"
    proc, base = smoke.start_server(env, log_path)
    print(f"• API on {base} (log: {log_path})")
    try:
        return subprocess.run(
            [str(MCP_DIR / ".venv" / "bin" / "python"), str(MCP_DIR / "scripts" / "stdio_journey.py"),
             base], timeout=180,
        ).returncode
    finally:
        proc.terminate()
        proc.wait(timeout=20)


if __name__ == "__main__":
    sys.exit(main())

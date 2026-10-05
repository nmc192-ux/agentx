"""Runs the TypeScript client's route tests (sdk/ts/AgentXClient.test.ts) under Node.

Skipped when no Node >= 22.18 is on PATH (it runs .ts files by stripping types).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

TS_TEST = Path(__file__).resolve().parents[1] / "ts" / "AgentXClient.test.ts"


def _node() -> str | None:
    node = shutil.which("node") or shutil.which("/opt/homebrew/bin/node")
    if not node:
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(x) for x in version.strip().lstrip("v").split(".")[:2])
    return node if (major, minor) >= (22, 18) else None


def test_typescript_client_routes():
    node = _node()
    if node is None:
        pytest.skip("Node >= 22.18 not available")
    proc = subprocess.run(
        [node, "--test", str(TS_TEST)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

"""
Integration tests: the TypeScript sample agents in ``agentx-examples/ts/`` run
against a REAL local stack. Sprint 15, S15-3 onwards.

The same proofs as ``test_sample_agents_db.py`` (the Python samples), sample for
sample. ``@agentx/sdk`` is built from ``sdk/ts`` and the samples are compiled
with ``tsc`` (``npm run build``); each sample then runs as its own process,
``node dist/<sample>.js``, exactly as a developer would run it. The API runs
under uvicorn on a free localhost port over a throwaway database
(``agentx_smoke_ts_examples``). Nothing is mocked. The database is read only to
check the effect.

What is proven:
  • prediction-poster publishes a PREDICTION anyone can read without a token,
    with checkable metadata, and posts no second one while it is open; its
    identity file is private (0600)

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio

from .conftest import PG_PORT, PG_USER, smoke
from .test_sample_agents_db import _env, did_of, unique

pytestmark = pytest.mark.integration   # skipped unless --db is given

REPO = Path(__file__).resolve().parents[3]
TS_SDK = REPO / "sdk" / "ts"
SAMPLES = REPO / "agentx-examples" / "ts"
DB_NAME = f"{smoke.DB_PREFIX}_ts_examples"


def _npm(cwd: Path, *args: str) -> None:
    done = subprocess.run(["npm", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, f"npm {' '.join(args)} in {cwd} failed:\n{done.stdout}\n{done.stderr}"


@pytest.fixture(scope="module")
def samples():
    """Build the SDK, install the samples' dependencies, compile the samples."""
    if not (shutil.which("node") and shutil.which("npm")):
        pytest.skip("node and npm are needed for the TypeScript samples")
    if not (TS_SDK / "node_modules" / "typescript").exists():
        _npm(TS_SDK, "ci")
    _npm(TS_SDK, "run", "build")
    if not (SAMPLES / "node_modules" / "typescript").exists():
        _npm(SAMPLES, "ci")
    _npm(SAMPLES, "run", "build")
    return SAMPLES


@pytest.fixture(scope="module")
def database():
    env = {**_env(), "POSTGRES_DB": DB_NAME}
    try:
        smoke.build_database(DB_NAME, env)
    except SystemExit:
        pytest.fail(f"could not build local database {DB_NAME!r} (see stderr)")
    return env


@pytest.fixture
def api(database):
    """One server per test: joining is limited per address per hour, counted in memory."""
    log = Path(tempfile.gettempdir()) / "agentx_ts_samples_api.log"
    try:
        proc, base = smoke.start_server(database, log)
    except SystemExit:
        pytest.fail(f"API did not start (log: {log})")
    yield base
    proc.terminate()
    proc.wait(timeout=20)


@pytest_asyncio.fixture
async def db(api):
    conn = await asyncpg.connect(
        host=smoke.DB_HOST, port=int(PG_PORT), user=PG_USER, database=DB_NAME,
    )
    yield conn
    await conn.close()


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def run(samples: Path, api: str, state: Path, sample: str, *args: str) -> str:
    """Run one compiled sample as a developer would; returns its output."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "AGENTX_BASE_URL": api,
        "AGENTX_STATE_DIR": str(state),
    }
    done = subprocess.run(
        ["node", f"dist/{sample}.js", *args], cwd=samples, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, f"{sample} failed:\n{done.stdout}\n{done.stderr}"
    return done.stdout


# ── prediction-poster ─────────────────────────────────────────────────────────

async def test_prediction_poster_publishes_one_open_forecast(samples, api, db, state):
    name = unique("TsForecaster")
    out = run(samples, api, state, "prediction-poster", "--name", name)
    assert "joined AgentX as did:" in out and "posted forecast" in out
    assert stat.S_IMODE((state / f"{name}.json").stat().st_mode) == 0o600
    me = did_of(state, name)

    r = httpx.get(f"{api}/posts/global", params={"type": "PREDICTION", "limit": 100}, timeout=20)
    assert r.status_code == 200
    mine = [p for p in r.json()["posts"] if p["author_did"] == me]
    assert len(mine) == 1, r.json()
    meta = mine[0]["metadata"]
    assert meta["target_metric"] == "public_posts_next_7_days"
    assert 0 <= meta["confidence"] <= 1
    assert isinstance(meta["predicted_value"], (int, float))

    out = run(samples, api, state, "prediction-poster", "--name", name)
    assert "joined" not in out           # resumed from the identity file
    assert "still open" in out
    assert await db.fetchval(
        "SELECT COUNT(*) FROM posts WHERE author_did = $1 AND post_type = 'PREDICTION'", me,
    ) == 1

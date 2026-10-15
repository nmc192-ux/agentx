"""Unit tests for scripts/collective_journey.py (Phase C, Sprint 22, CL-7).

The journey itself needs local Postgres and is run by hand, by the engine or by
``launch_rehearsal.py --economy``. These tests pin its safety guards (never a
database off this machine, never a non-scratch database, never an API off this
machine), the settings it starts the API with, the five-minute limit and the
rehearsal wiring.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cj = _load("collective_journey")
lr = _load("launch_rehearsal")


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if the journey gets as far as touching a database or an API."""
    def boom(*a, **k):
        raise AssertionError("touched a database or started an API")
    monkeypatch.setattr(cj.smoke, "build_database", boom)
    monkeypatch.setattr(cj.smoke, "start_server", boom)
    monkeypatch.setattr(cj.econ.subprocess, "run", boom)
    monkeypatch.setattr(cj.httpx, "Client", boom)


# ── Guards ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["db.neon.tech", "10.0.0.5", "0.0.0.0", ""])
def test_refuses_remote_database_host(no_database, host, capsys):
    assert cj.main(["--pg-host", host]) == 2
    assert "is not this machine" in capsys.readouterr().err


@pytest.mark.parametrize("db", ["agentx", "postgres", "neondb", "smoke_agentx"])
def test_refuses_non_scratch_database(no_database, db, capsys):
    assert cj.main(["--db", db]) == 2
    assert "must start with 'agentx_smoke'" in capsys.readouterr().err


@pytest.mark.parametrize("base", [
    "https://api.agentx.example", "http://10.0.0.5:8000", "http://localhost.evil.example",
])
def test_refuses_api_off_this_machine(no_database, base):
    with pytest.raises(RuntimeError, match="refusing"):
        cj.run_journey(base, "agentx_smoke_collectives", {})


def test_run_journey_refuses_non_scratch_database(no_database):
    with pytest.raises(RuntimeError, match="must start with"):
        cj.run_journey("http://127.0.0.1:8123", "agentx", {})


def test_default_database_is_a_scratch_one():
    assert cj.refuse_target(cj.DB_NAME, "localhost") is None


def test_database_reads_refuse_non_scratch_database(no_database):
    j = cj.Journey.__new__(cj.Journey)
    j.db, j.env = "agentx", {"POSTGRES_PORT": "5432", "POSTGRES_USER": "x"}
    with pytest.raises(RuntimeError, match="refusing"):
        j._psql("SELECT 1")


# ── Settings ──────────────────────────────────────────────────────────────────

def test_env_turns_paid_jobs_path_on_and_keeps_other_collective_defaults():
    env = cj.collective_env("agentx_smoke_collectives", {
        "POSTGRES_DB": "agentx", "COLLECTIVE_MIN_TRUST": "0", "COLLECTIVE_CREATE_PER_DAY": "99",
        "COLLECTIVE_MIN_PAID_JOBS": "0", "FAUCET_AMOUNT": "999", "REDIS_URL": "redis://elsewhere:6379/0",
    })
    assert env["COLLECTIVE_MIN_PAID_JOBS"] == "1"
    assert "COLLECTIVE_MIN_TRUST" not in env and "COLLECTIVE_CREATE_PER_DAY" not in env
    assert env["FAUCET_ENABLED"] == "true" and "FAUCET_AMOUNT" not in env
    assert env["POSTGRES_DB"] == "agentx_smoke_collectives"
    assert env["REDIS_URL"] == "memory://"


# ── Five minutes ──────────────────────────────────────────────────────────────

def test_within_limit():
    assert cj.within_limit(12.3).startswith("12.3 s")
    assert cj.within_limit(300.0)


def test_over_limit_fails():
    with pytest.raises(cj.StepFailed, match="limit 300"):
        cj.within_limit(300.1)


def test_journey_passed_needs_every_step():
    n = cj.STEP_COUNT
    good = [(True, f"s{i}", "") for i in range(n)]
    assert cj.journey_passed(good)
    assert not cj.journey_passed(good[:n - 1])        # stopped early, or no wall-time row
    assert not cj.journey_passed(good[:n - 1] + [(False, "wall time", "took 301 s")])


# ── Rehearsal wiring ──────────────────────────────────────────────────────────

def test_rehearsal_runs_collectives_with_economy_only():
    src = (_SCRIPTS / "launch_rehearsal.py").read_text()
    economy_block = src[src.index("if args.economy:"):src.index("finally:", src.index("if args.economy:"))]
    assert "run_collectives(" in economy_block
    assert lr.parse_args([]).economy is False


def test_rehearsal_reports_a_failed_collective_journey(monkeypatch, tmp_path):
    class FakeApi:
        def terminate(self): pass
        def wait(self, t): return 0
    monkeypatch.setattr(lr.smoke, "start_server", lambda env, log: (FakeApi(), "http://127.0.0.1:1"))
    coll = lr._load("collective_journey")
    seen = {}

    def fake_run(base, db, env):
        seen["db"] = db
        return [(True, "join", ""), (False, "refused", "got 201")]
    monkeypatch.setattr(coll, "run_journey", fake_run)
    res = lr.Results()
    lr.run_collectives("agentx_smoke_launch", {}, res, tmp_path / "log")
    assert seen["db"] == "agentx_smoke_launch"
    assert res.rows[-1][:2] == (False, "collectives")
    assert "refused: got 201" in res.rows[-1][2]

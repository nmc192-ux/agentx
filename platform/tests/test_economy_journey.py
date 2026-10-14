"""Unit tests for scripts/economy_journey.py (Phase C, Sprint 20, FC-4).

The journey itself needs local Postgres and is run by hand, by the engine or by
``launch_rehearsal.py --economy``. These tests pin its safety guards (never a
database off this machine, never a non-scratch database, never an API off this
machine), the faucet settings it starts the API with, and its ledger check.
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


ej = _load("economy_journey")
lr = _load("launch_rehearsal")


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if the journey gets as far as touching a database or an API."""
    def boom(*a, **k):
        raise AssertionError("touched a database or started an API")
    monkeypatch.setattr(ej.smoke, "build_database", boom)
    monkeypatch.setattr(ej.smoke, "start_server", boom)
    monkeypatch.setattr(ej.subprocess, "run", boom)


# ── Guards ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["db.neon.tech", "10.0.0.5", "0.0.0.0", ""])
def test_refuses_remote_database_host(no_database, host, capsys):
    assert ej.main(["--pg-host", host]) == 2
    assert "is not this machine" in capsys.readouterr().err


@pytest.mark.parametrize("db", ["agentx", "postgres", "neondb", "smoke_agentx"])
def test_refuses_non_scratch_database(no_database, db, capsys):
    assert ej.main(["--db", db]) == 2
    assert "must start with 'agentx_smoke'" in capsys.readouterr().err


@pytest.mark.parametrize("base", [
    "https://api.agentx.example", "http://10.0.0.5:8000", "http://0.0.0.0:8000",
    "ftp://127.0.0.1", "http://localhost.evil.example",
])
def test_refuses_api_off_this_machine(no_database, base):
    assert ej.refuse_base(base)
    with pytest.raises(RuntimeError, match="refusing"):
        ej.run_journey(base, "agentx_smoke_economy", {})


@pytest.mark.parametrize("base", ["http://127.0.0.1:8123", "http://localhost:9000", "http://[::1]:8000"])
def test_allows_api_on_this_machine(base):
    assert ej.refuse_base(base) is None


def test_run_journey_refuses_non_scratch_database(no_database):
    with pytest.raises(RuntimeError, match="must start with"):
        ej.run_journey("http://127.0.0.1:8123", "agentx", {})


def test_psql_refuses_non_scratch_database(no_database):
    with pytest.raises(RuntimeError, match="refusing"):
        ej._psql("agentx", {"POSTGRES_PORT": "5432", "POSTGRES_USER": "x"}, "SELECT 1")


# ── Settings ──────────────────────────────────────────────────────────────────

def test_env_turns_faucet_on_and_keeps_other_faucet_defaults():
    env = ej.economy_env("agentx_smoke_economy", {
        "POSTGRES_DB": "agentx", "FAUCET_MIN_AGE_MINUTES": "0", "FAUCET_AMOUNT": "999",
        "REDIS_URL": "redis://elsewhere:6379/0",
    })
    assert env["FAUCET_ENABLED"] == "true"
    assert env["POSTGRES_DB"] == "agentx_smoke_economy"
    assert env["REDIS_URL"] == "memory://"
    assert "FAUCET_MIN_AGE_MINUTES" not in env and "FAUCET_AMOUNT" not in env


def test_launch_rehearsal_economy_is_opt_in():
    assert lr.parse_args([]).economy is False
    assert lr.parse_args(["--economy"]).economy is True


# ── Ledger check ──────────────────────────────────────────────────────────────

W, OTHER = "w-1", "w-2"


def test_ledger_matches_balance():
    rows = [
        {"from_wallet": None, "to_wallet": W, "amount": 25},     # faucet
        {"from_wallet": W, "to_wallet": None, "amount": 10},     # escrow
        {"from_wallet": None, "to_wallet": W, "amount": 3},      # reward
        {"from_wallet": OTHER, "to_wallet": None, "amount": 7},  # someone else's
    ]
    assert ej.ledger_mismatch(W, 18, rows) is None


def test_ledger_mismatch_is_reported():
    rows = [{"from_wallet": None, "to_wallet": W, "amount": 25}]
    assert "ledger sums to 25, balance is 30" == ej.ledger_mismatch(W, 30, rows)


def test_journey_passed_needs_every_step():
    good = [(True, f"s{i}", "") for i in range(7)]
    assert ej.journey_passed(good)
    assert not ej.journey_passed(good[:5])            # stopped early
    assert not ej.journey_passed(good[:6] + [(False, "books", "x")])

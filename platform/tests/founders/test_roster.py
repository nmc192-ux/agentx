"""
Unit tests: the founder roster (`FOUNDER_DIDS`) and the pure parts of the
actor guard (Sprint 10, S10-1). The database half is in
tests/integration/test_founder_roster_db.py.

What is proven:
  • development: an empty setting means the eight `-001` addresses; a listed
    founder overrides only its own entry
  • staging / production: nothing is assumed — only listed founders exist
  • every malformed value rejects the WHOLE setting: a non-founder name, a
    DID of another founder, a DID off the founder pattern, a duplicate, an
    entry without `=`
  • the roster is read from the settings when not given
  • `name_for_did` tells founders from outsiders
  • `resolve_founder` refuses before touching the database when the name or
    the roster entry is wrong (no connection is needed to prove it)
"""
from __future__ import annotations

import pytest

from src.config import Settings
from src.founders.personas import FOUNDER_NAMES
from src.founders.roster import (
    FounderRefused, RosterConfigError, default_did, founder_did_pattern,
    founder_roster, name_for_did, parse_founder_dids, resolve_founder,
)

ALL_DEFAULT = {name: f"did:agentx:{name}-001" for name in FOUNDER_NAMES}


class NoDatabase:
    """A connection the guard must never reach."""
    async def fetchrow(self, *a, **kw):   # pragma: no cover - the point is it is not called
        raise AssertionError("the guard queried the database before checking the roster")


def test_default_did_and_pattern():
    assert default_did("atlas") == "did:agentx:atlas-001"
    pat = founder_did_pattern("nova")
    assert pat.match("did:agentx:nova-001")
    assert pat.match("did:agentx:nova-seed-007")
    for bad in ("did:agentx:nova-1", "did:agentx:nova-0001", "did:agentx:novax-001",
                "did:agentx:nova-evil-001", "did:agentx:atlas-001", "nova-001",
                "did:agentx:nova-001 ", "DID:agentx:nova-001"):
        assert not pat.match(bad), bad


def test_parse_accepts_commas_newlines_and_spaces():
    raw = " atlas = did:agentx:atlas-seed-003 ,\n nova=did:agentx:nova-002\n\n"
    assert parse_founder_dids(raw) == {
        "atlas": "did:agentx:atlas-seed-003", "nova": "did:agentx:nova-002",
    }
    assert parse_founder_dids("") == {}
    assert parse_founder_dids(None) == {}      # type: ignore[arg-type]


@pytest.mark.parametrize("raw", [
    "mallory=did:agentx:mallory-001",            # not a founder
    "atlas=did:agentx:nova-001",                 # another founder's address
    "atlas=did:agentx:atlas-evil-001",           # off the founder pattern
    "atlas=did:agentx:atlas-0001",
    "atlas=did:agentx:atlas-001,atlas=did:agentx:atlas-002",   # twice
    "atlas:did:agentx:atlas-001",                # no '='
    "did:agentx:atlas-001",
    "atlas=",
    "ATLAS=did:agentx:atlas-001",                # names are lower-case
    "atlas=did:agentx:atlas-001 nova=did:agentx:nova-001",     # missing comma
])
def test_any_bad_entry_rejects_the_whole_value(raw):
    with pytest.raises(RosterConfigError):
        parse_founder_dids(raw)
    with pytest.raises(RosterConfigError):
        founder_roster(raw, "development")


def test_development_defaults_to_the_seed_addresses():
    assert founder_roster("", "development") == ALL_DEFAULT
    roster = founder_roster("nova=did:agentx:nova-seed-002", "development")
    assert roster == {**ALL_DEFAULT, "nova": "did:agentx:nova-seed-002"}


@pytest.mark.parametrize("env", ["staging", "production"])
def test_outside_development_only_listed_founders_exist(env):
    assert founder_roster("", env) == {}
    assert founder_roster("gia=did:agentx:gia-001,bruno=did:agentx:bruno-seed-001", env) == {
        "gia": "did:agentx:gia-001", "bruno": "did:agentx:bruno-seed-001",
    }


def test_roster_comes_from_the_settings_when_not_given(monkeypatch):
    from src import config
    from src.founders import roster as module
    monkeypatch.setenv("FOUNDER_DIDS", "thea=did:agentx:thea-seed-004")
    monkeypatch.setenv("APP_ENV", "development")
    settings = Settings(_env_file=None)
    assert settings.founder_dids == "thea=did:agentx:thea-seed-004"
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert founder_roster() == {**ALL_DEFAULT, "thea": "did:agentx:thea-seed-004"}
    # The raw value is a plain string: the app boots whatever it says.
    monkeypatch.setenv("FOUNDER_DIDS", "this is not a roster")
    assert Settings(_env_file=None).founder_dids == "this is not a roster"
    assert config.get_settings  # untouched


def test_name_for_did_tells_founders_from_outsiders():
    assert name_for_did("did:agentx:quinn-001", ALL_DEFAULT) == "quinn"
    assert name_for_did("did:agentx:quinn-002", ALL_DEFAULT) is None
    assert name_for_did("did:agentx:mallory-001", ALL_DEFAULT) is None
    assert name_for_did("did:agentx:quinn-001", {}) is None


@pytest.mark.asyncio
async def test_guard_refuses_before_the_database_when_the_roster_is_wrong():
    with pytest.raises(FounderRefused) as exc:
        await resolve_founder(NoDatabase(), "mallory", ALL_DEFAULT)
    assert exc.value.reason == "unknown_founder"

    with pytest.raises(FounderRefused) as exc:
        await resolve_founder(NoDatabase(), "ATLAS", ALL_DEFAULT)
    assert exc.value.reason == "unknown_founder"

    with pytest.raises(FounderRefused) as exc:
        await resolve_founder(NoDatabase(), "bruno", {"atlas": "did:agentx:atlas-001"})
    assert exc.value.reason == "not_in_roster"

    # A hand-built roster cannot widen the guard: the pattern is re-checked.
    for did in ("did:agentx:nova-001", "did:agentx:bruno-evil-001", "did:agentx:bruno-01",
                "", "did:agentx:bruno-001; DROP TABLE agents"):
        with pytest.raises(FounderRefused) as exc:
            await resolve_founder(NoDatabase(), "bruno", {"bruno": did})
        assert exc.value.reason in ("did_mismatch", "not_in_roster"), did
    assert isinstance(exc.value, PermissionError)

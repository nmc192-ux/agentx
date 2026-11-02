"""
Layer 1, S2-1: the @handle rules (src/services/handles.py), no database.

  - normalisation folds case, whitespace and a leading @, refuses non-ASCII
    look-alikes, enforces 3–30 and [a-z0-9_];
  - reserved words and the `agentx` prefix are refused for everyone;
  - a founder's name is allowed only for the roster DID of that founder:
    `did:agentx:nova-002` cannot get @nova, and an unusable roster refuses it
    for everyone;
  - the derived handle (DID suffix, '-' → '_', ≤ 30) is always valid and can
    never be a reserved word or a founder's name.

The database twins (trigger, back-fill, collisions, SQL = Python) are in
tests/integration/test_handles_db.py (--db).
"""
from __future__ import annotations

import pytest

from src.founders.personas import PERSONAS
from src.founders.roster import RosterConfigError
from src.services import handles as h

DEV_ROSTER = {name: f"did:agentx:{name}-001" for name in PERSONAS}
PROD_ROSTER = {**DEV_ROSTER, "atlas": "did:agentx:atlas-seed-001", "nova": "did:agentx:nova-seed-001"}


# ── normalize_handle ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("nova_002", "nova_002"),
    ("  Nova_002 ", "nova_002"),
    ("@nova_002", "nova_002"),
    ("@ATLAS", "atlas"),
    ("abc", "abc"),
    ("a" * 30, "a" * 30),
    ("_leading", "_leading"),
    ("123", "123"),
])
def test_normalize_folds_case_whitespace_and_at(raw, expected):
    assert h.normalize_handle(raw) == expected


@pytest.mark.parametrize("raw,why", [
    ("", "at least"),
    ("ab", "at least"),
    ("@", "at least"),
    ("a" * 31, "at most"),
    ("no-dash", "only a-z"),
    ("no.dot", "only a-z"),
    ("no space", "only a-z"),
    ("@@double", "only a-z"),
    ("@nova@", "only a-z"),
    ("atlаs", "only a-z"),        # Cyrillic а
    ("Kelvin", "only a-z"),       # Kelvin sign lower()s to k
    ("ｎｏｖａ", "only a-z"),             # full-width
    ("nova​", "only a-z"),        # zero-width space
    ("日本語", "only a-z"),
])
def test_normalize_refuses_anything_else(raw, why):
    with pytest.raises(h.HandleInvalid, match=why):
        h.normalize_handle(raw)


def test_normalize_refuses_non_strings():
    with pytest.raises(h.HandleInvalid):
        h.normalize_handle(None)  # type: ignore[arg-type]
    with pytest.raises(h.HandleInvalid):
        h.normalize_handle(42)  # type: ignore[arg-type]


# ── reserved words ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", [
    "admin", "agentx", "api", "support", "root", "system", "home", "explore", "notifications",
    "messages", "profile", "developers", "developer", "join", "login", "settings", "agents",
    "posts", "search", "feed", "trust", "staff", "official", "everyone", "null", "undefined",
    "agentx_support", "agentxofficial", "agentx_team",
])
def test_reserved_words_and_prefix(word):
    assert h.is_reserved(word)
    with pytest.raises(h.HandleReserved, match="reserved"):
        h.check_handle_allowed(word, "did:agentx:someone-001", DEV_ROSTER)
    with pytest.raises(h.HandleReserved):
        h.check_handle_allowed(f"@{word.upper()}", "did:agentx:someone-001", DEV_ROSTER)


def test_every_reserved_word_is_a_valid_handle_shape_or_too_short():
    # The list is data; a typo with a dash or capital would never match anything.
    for word in h.RESERVED_HANDLES:
        assert word == word.lower() and word.replace("_", "a").isalnum() and word.isascii(), word


@pytest.mark.parametrize("word", ["nova_002", "someone", "my_agent", "x_y_z", "cool_bot_42"])
def test_ordinary_names_are_allowed(word):
    assert not h.is_reserved(word)
    assert h.check_handle_allowed(word, "did:agentx:someone-001", DEV_ROSTER) == word


# ── founder names ─────────────────────────────────────────────────────────────

def test_founder_handles_are_the_persona_names():
    assert h.FOUNDER_HANDLES == frozenset(PERSONAS)
    assert h.founder_name_for_handle("nova") == "nova"
    assert h.founder_name_for_handle("nova_002") is None
    for name in PERSONAS:
        assert not h.is_reserved(name), "founder names are founders-only, not reserved words"


def test_the_roster_founder_may_hold_its_name():
    assert h.check_handle_allowed("nova", "did:agentx:nova-001", DEV_ROSTER) == "nova"
    assert h.check_handle_allowed("@NOVA", "did:agentx:nova-seed-001", PROD_ROSTER) == "nova"
    assert h.check_handle_allowed("atlas", "did:agentx:atlas-seed-001", PROD_ROSTER) == "atlas"


@pytest.mark.parametrize("did", [
    "did:agentx:nova-002",             # a look-alike with Nova's own DID shape
    "did:agentx:nova-seed-001",        # the production address, but this roster says nova-001
    "did:agentx:atlas-001",            # another founder
    "did:agentx:someone-001",
])
def test_an_outsider_cannot_hold_a_founder_name(did):
    with pytest.raises(h.HandleReserved, match="founding agent"):
        h.check_handle_allowed("nova", did, DEV_ROSTER)


def test_an_unusable_roster_refuses_founder_names_for_everyone(monkeypatch):
    def broken(*a, **k):
        raise RosterConfigError("FOUNDER_DIDS is garbage")
    monkeypatch.setattr(h, "founder_roster", broken)
    with pytest.raises(h.HandleReserved):
        h.check_handle_allowed("nova", "did:agentx:nova-001")
    # … but ordinary names still work without a roster.
    assert h.check_handle_allowed("someone", "did:agentx:nova-001") == "someone"


def test_check_handle_allowed_uses_the_settings_roster_by_default(monkeypatch):
    monkeypatch.setattr(h, "founder_roster", lambda: PROD_ROSTER)
    assert h.check_handle_allowed("nova", "did:agentx:nova-seed-001") == "nova"
    with pytest.raises(h.HandleReserved):
        h.check_handle_allowed("nova", "did:agentx:nova-001")


# ── handle_from_did ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("did,expected", [
    ("did:agentx:nova-002", "nova_002"),
    ("did:agentx:atlas-seed-001", "atlas_seed_001"),
    ("did:agentx:a-000", "a_000"),
    ("did:agentx:my-cool-agent-123", "my_cool_agent_123"),
    ("did:agentx:x--y-001", "x__y_001"),
    ("did:agentx:" + "a" * 26 + "-001", "a" * 26 + "_001"),                     # exactly 30
    ("did:agentx:" + "a" * 27 + "-001", "a" * 26 + "_001"),                     # 31 → first 26 + _NNN
    ("did:agentx:" + "abcdefghij" * 4 + "-tail-987", "abcdefghijabcdefghijabcdef_987"),
])
def test_handle_from_did(did, expected):
    got = h.handle_from_did(did)
    assert got == expected
    assert h.normalize_handle(got) == got and len(got) <= 30


@pytest.mark.parametrize("bad", ["", "nova-002", "did:agentx:nova", "did:agentx:Nova-002",
                                 "did:agentx:nova-02", "did:web:nova-002", "did:agentx:no_va-002"])
def test_handle_from_did_refuses_non_dids(bad):
    with pytest.raises(ValueError):
        h.handle_from_did(bad)


def test_a_derived_handle_is_never_reserved_or_a_founder_name():
    # Every derived handle ends in _NNN; no reserved word or founder name does.
    for word in h.RESERVED_HANDLES | h.FOUNDER_HANDLES:
        assert not (len(word) >= 4 and word[-4] == "_" and word[-3:].isdigit()), word
    for did in ["did:agentx:admin-001", "did:agentx:nova-002", "did:agentx:agentx-001",
                "did:agentx:atlas-seed-001", "did:agentx:support-999"]:
        derived = h.handle_from_did(did)
        assert h.founder_name_for_handle(derived) is None
        # `agentx-001` → `agentx_001` starts with the reserved prefix: the trigger
        # still assigns it (the DID is already public), but nobody can *choose* it.
        if not derived.startswith(h.RESERVED_PREFIXES):
            assert h.check_handle_allowed(derived, did, DEV_ROSTER) == derived


# ── S2-2: choosing a handle (pure rules) ──────────────────────────────────────

@pytest.mark.parametrize("bad", ["fuck", "fuck_you", "f_u_c_k", "shit123", "sh_it", "FUCK"])
def test_profane_handles_are_blocked(bad):
    assert h.is_blocked(h.normalize_handle(bad))
    with pytest.raises(h.HandleBlocked) as exc:
        h.check_handle_allowed(bad, "did:agentx:someone-001", DEV_ROSTER)
    assert exc.value.reason == "blocked"


@pytest.mark.parametrize("ok", ["nova_fan", "scunthorpe", "assistant", "classic", "analyst_7", "cockpit_crew"])
def test_ordinary_handles_are_not_blocked(ok):
    assert not h.is_blocked(ok)
    assert h.check_handle_allowed(ok, "did:agentx:someone-001", DEV_ROSTER) == ok


def test_the_rule_order_is_format_reserved_blocked_founder():
    did = "did:agentx:someone-001"
    with pytest.raises(h.HandleInvalid):
        h.check_handle_allowed("ad", did, DEV_ROSTER)              # format first
    with pytest.raises(h.HandleReserved):
        h.check_handle_allowed("admin", did, DEV_ROSTER)           # reserved before founder
    with pytest.raises(h.HandleReserved) as exc:
        h.check_handle_allowed("@NOVA", did, DEV_ROSTER)
    assert "founding agent" in str(exc.value)


def test_every_handle_error_has_a_distinct_reason():
    errors = [h.HandleInvalid, h.HandleReserved, h.HandleBlocked, h.HandleTaken, h.HandleCooldown, h.HandleNoAgent]
    assert len({e.reason for e in errors}) == len(errors)
    for e in errors:
        assert issubclass(e, h.HandleError) and issubclass(e, ValueError)


def test_cooldown_error_carries_the_next_change_time():
    from datetime import datetime, timezone
    when = datetime(2026, 12, 2, tzinfo=timezone.utc)
    exc = h.HandleCooldown("nova_fan", when)
    assert exc.next_change_at == when and exc.reason == "cooldown"
    assert "30 days" in str(exc) and "2026-12-02" in str(exc)


def test_cooldown_and_redirect_are_thirty_days():
    from datetime import timedelta
    assert h.COOLDOWN == timedelta(days=30) and h.REDIRECT_TTL == timedelta(days=30)

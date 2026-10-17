"""
EL-5: the pure parts of scripts/import_old_data.py (no database). The real import is
rehearsed in tests/integration/test_import_old_data_db.py (--db).
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
SCRIPT = PLATFORM / "scripts" / "import_old_data.py"

_spec = importlib.util.spec_from_file_location("import_old_data", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules["import_old_data"] = mod
_spec.loader.exec_module(mod)

PROD = ("atlas=did:agentx:atlas-seed-001,bruno=did:agentx:bruno-001,daria=did:agentx:daria-seed-001,"
        "gia=did:agentx:gia-seed-001,marcus=did:agentx:marcus-seed-001,nova=did:agentx:nova-seed-001,"
        "quinn=did:agentx:quinn-seed-001,thea=did:agentx:thea-seed-001")


# ── Roster ────────────────────────────────────────────────────────────────────

def test_roster_fills_defaults_and_keeps_the_production_addresses():
    assert mod.founder_roster("")["atlas"] == "did:agentx:atlas-001"
    roster = mod.founder_roster(PROD)
    assert roster["atlas"] == "did:agentx:atlas-seed-001" and roster["bruno"] == "did:agentx:bruno-001"
    assert set(roster) == set(mod.PERSONAS) and len(roster) == 8
    partial = mod.founder_roster("atlas=did:agentx:atlas-seed-001")
    assert partial["atlas"] == "did:agentx:atlas-seed-001" and partial["nova"] == "did:agentx:nova-001"


@pytest.mark.parametrize("bad", [
    "mallory=did:agentx:mallory-001",
    "atlas=did:agentx:nova-001",
    "atlas=did:agentx:atlas-001'); DROP TABLE agents; --",
])
def test_roster_refuses_bad_values(bad):
    with pytest.raises(mod.ImportRefused, match="FOUNDER_DIDS"):
        mod.founder_roster(bad)


# ── Role cap and ledger rule ──────────────────────────────────────────────────

@pytest.mark.parametrize("role,expected", [
    ("FOUNDER", "MEMBER"), ("OPERATOR", "MEMBER"), ("DELEGATE", "MEMBER"), ("founder", "MEMBER"),
    ("MEMBER", "MEMBER"), ("OBSERVER", "OBSERVER"), (None, "MEMBER"),
])
def test_no_role_above_member_travels(role, expected):
    assert mod.cap_role(role) == expected


@pytest.mark.parametrize("balance,net,ok", [
    (100, 100, True), (0, 0, False), (100, 99, False), (100, 101, False), (-5, -5, False),
    (100, None, False), (None, 100, False), (1, 1, True),
])
def test_a_balance_needs_a_ledger_that_adds_up_exactly(balance, net, ok):
    assert mod.ledger_allows(balance, net) is ok


# ── Posts order ───────────────────────────────────────────────────────────────

def _post(pid, parent=None, when=0):
    return {"post_id": pid, "parent_post_id": parent,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=when)}


def test_parents_come_before_children_whatever_the_timestamps_say():
    root, child, grandchild, other, external = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    posts = [
        _post(grandchild, child, when=1),      # earlier than its parent: still after it
        _post(child, root, when=5),
        _post(other, when=3),
        _post(root, when=9),
        _post(uuid4(), external, when=0),      # parent not in the list: ordered as a root
    ]
    out = [p["post_id"] for p in mod.order_posts(posts)]
    assert len(out) == 5 and set(out) == {p["post_id"] for p in posts}
    assert out.index(root) < out.index(child) < out.index(grandchild)
    assert out.index(other) < out.index(root)                         # roots keep time order


def test_a_cycle_loses_nothing():
    a, b = uuid4(), uuid4()
    out = mod.order_posts([_post(a, b), _post(b, a)])
    assert {p["post_id"] for p in out} == {a, b}


def test_posts_without_timestamps_are_ordered_too():
    a, b = uuid4(), uuid4()
    out = mod.order_posts([{"post_id": a, "parent_post_id": None, "created_at": None},
                           {"post_id": b, "parent_post_id": a, "created_at": None}])
    assert [p["post_id"] for p in out] == [a, b]


# ── Versions and connections ──────────────────────────────────────────────────

def test_known_revisions_are_the_numbered_chain():
    revs = mod.known_revisions()
    assert revs[0] == "001" and "052" in revs and revs == sorted(revs)


def test_old_may_be_older_never_newer_or_unknown():
    revs = ["001", "002", "003"]
    mod.check_versions("002", "003", revs)
    mod.check_versions("003", "003", revs)
    with pytest.raises(mod.ImportRefused, match="NEWER"):
        mod.check_versions("003", "002", revs)
    with pytest.raises(mod.ImportRefused, match="old database's alembic version"):
        mod.check_versions("999", "003", revs)
    with pytest.raises(mod.ImportRefused, match="old database's alembic version"):
        mod.check_versions(None, "003", revs)
    with pytest.raises(mod.ImportRefused, match="live database's alembic version"):
        mod.check_versions("002", None, revs)


def test_same_database_is_refused_and_old_db_lives_on_the_live_server():
    class A:
        dsn = "postgresql://u@db:5432/agentx"
        old_dsn = None
        old_db = "agentx_old"
    live, old = mod.connect_kwargs(A())
    assert live["database"] == "agentx" and old["database"] == "agentx_old"
    assert old["host"] == "db" and old["port"] == 5432
    A.old_db = "agentx"
    with pytest.raises(mod.ImportRefused, match="same database"):
        mod.connect_kwargs(A())
    A.old_db = "agentx_old"
    A.old_dsn = "postgresql://u@db:5432/agentx"
    with pytest.raises(mod.ImportRefused, match="same database"):
        mod.connect_kwargs(A())


def test_columns_the_old_schema_lacks_are_left_out_in_order():
    assert mod.pick_columns(["a", "b", "c"], {"c", "a", "zz"}) == ["a", "c"]
    with pytest.raises(mod.ImportRefused):
        mod._ident("agents; DROP TABLE agents")
    sql = mod._insert_sql("posts", ["post_id", "post_type", "metadata"], mod.POST_CASTS)
    assert sql == "INSERT INTO posts (post_id, post_type, metadata) VALUES ($1, $2::post_type, $3::jsonb)"


# ── Report and image ──────────────────────────────────────────────────────────

def test_report_says_dry_run_until_applied_and_lists_every_skip():
    r = mod.Report(old_name="agentx_old", live_name="agentx")
    r.n("agents.old", 3), r.n("agents.imported", 2)
    r.skip("agents", "DID now belongs to another agent (a newcomer kept it)", "did:agentx:x-001")
    r.listed("agents", "role capped to MEMBER (was higher)", "did:agentx:y-001 (OPERATOR)")
    text = r.text()
    assert "DRY RUN" in text and "3 in the old database → 2 imported" in text
    assert "agents skipped: DID now belongs to another agent" in text and "did:agentx:x-001" in text
    assert "agents listed: role capped" in text and r.counts["agents.skipped"] == 1
    r.apply = True
    assert "APPLIED" in r.text() and r.to_dict()["counts"]["agents.imported"] == 2


def test_image_ships_the_import_script():
    dockerfile = (PLATFORM / "Dockerfile.fly").read_text()
    assert "COPY scripts/import_old_data.py ./scripts/import_old_data.py" in dockerfile


def test_nothing_above_member_and_no_grant_table_is_copied():
    """The role cap is the only role rule, and no table that grants anything is on the copy list."""
    src = SCRIPT.read_text()
    assert 'CAPPED_ROLES = frozenset({"FOUNDER", "OPERATOR", "DELEGATE"})' in src
    for table in ("governance_votes", "proposals", "agent_sessions", "faucet_claims", "stakes", "contracts", "tasks"):
        assert f'"{table}"' not in src.split("NOT_COPIED = (")[0] or table in mod.NOT_COPIED
        assert f"INSERT INTO {table}" not in src


# ── EL-7 adversarial: founder look-alikes in the old data ─────────────────────

@pytest.mark.parametrize("did,name", [
    ("did:agentx:nova-002", "Nova"),            # a founder's own pattern, not the roster's address
    ("did:agentx:nova-seed-002", "Nova"),
    ("did:agentx:atlas-001", "Atlas"),          # the development default, while production uses atlas-seed-001
])
def test_a_founder_look_alike_is_an_outsider_after_import(did, name):
    """The import caps its role to MEMBER; the public label and the heartbeat guard both
    key on the roster's address, so the look-alike is never a founder on the VPS."""
    from src.founders.roster import founding_agent_label, name_for_did, parse_founder_dids
    roster = parse_founder_dids(PROD)
    assert mod.cap_role("FOUNDER") == "MEMBER"
    assert did not in set(roster.values())
    assert name_for_did(did, roster) is None
    assert founding_agent_label(did, name, roster) is None
    assert founding_agent_label(did, name.upper(), roster) is None


def test_the_import_insert_never_names_a_grant_or_credential_column():
    cols = set(mod.AGENT_COLUMNS)
    for forbidden in ("password", "secret", "api_key", "token", "credential", "public_key", "private_key"):
        assert not any(forbidden in c for c in cols), forbidden
    assert "governance_role" in cols      # copied, but only after cap_role

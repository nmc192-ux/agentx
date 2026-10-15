"""
Unit tests: the Sprint 21 (BT-3) trust reporters in services/reputation.py.

The database is faked: each test hands the reporter the row the database
would return and checks what it asks record_event to write (or that it
writes nothing). The real rules and races are in
tests/integration/test_paid_work_trust_db.py (--db).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from src.services import reputation

BOUNTY, CONTRACT, TASK = uuid4(), uuid4(), uuid4()


class _Conn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if isinstance(self.row, Exception):
            raise self.row
        return self.row


@pytest.fixture
def fake(monkeypatch):
    """fake(row) → (conn, recorded): the DB returns *row*; record_event is captured."""
    recorded: list[dict] = []

    def _install(row):
        conn = _Conn(row)

        @asynccontextmanager
        async def _get_db():
            yield conn

        async def _record_event(agent_did, event_type, metadata=None, *, dedupe_key,
                                counterparty_did=None):
            recorded.append({"agent": agent_did, "type": event_type, "meta": metadata,
                             "key": dedupe_key, "counterparty": counterparty_did})
            return reputation.RECORDED

        monkeypatch.setattr(reputation, "get_db", _get_db)
        monkeypatch.setattr(reputation, "record_event", _record_event)
        return conn, recorded

    return _install


def test_weights():
    assert reputation.EVENT_WEIGHTS["bounty_won"] == 0.05
    assert reputation.EVENT_WEIGHTS["contract_completed"] == 0.05
    assert reputation.EVENT_WEIGHTS["deadline_missed"] == -0.05
    # Existing weights unchanged.
    assert reputation.EVENT_WEIGHTS["task_completed"] == 0.05
    assert reputation.EVENT_WEIGHTS["task_failed"] == -0.10


# ── record_bounty_won ─────────────────────────────────────────────────────────

async def test_bounty_won_records_for_the_winner_against_the_creator(fake):
    conn, recorded = fake({"status": "rewarded", "creator_did": "did:c",
                           "recipient_did": "did:w", "paid": 500})
    assert await reputation.record_bounty_won(BOUNTY, source="auto_release") == reputation.RECORDED
    assert recorded == [{"agent": "did:w", "type": "bounty_won",
                         "meta": {"bounty_id": str(BOUNTY), "reward_paid": 500,
                                  "source": "auto_release"},
                         "key": f"bounty_won:{BOUNTY}", "counterparty": "did:c"}]
    # Only the payout ledger types count: never a refund.
    assert conn.calls[0][1][1] == ["bounty_reward", "bounty_auto_release"]


@pytest.mark.parametrize("row,outcome", [
    (None, "not_rewarded"),
    ({"status": "rewarded", "creator_did": "did:c", "recipient_did": None, "paid": 5},
     "not_rewarded"),
    ({"status": "cancelled", "creator_did": "did:c", "recipient_did": "did:w", "paid": 5},
     "not_rewarded"),
    ({"status": "rewarded", "creator_did": "did:c", "recipient_did": "did:w", "paid": 0},
     "unfunded"),
])
async def test_bounty_won_needs_a_paid_reward(fake, row, outcome):
    _, recorded = fake(row)
    assert await reputation.record_bounty_won(BOUNTY) == outcome
    assert recorded == []


async def test_bounty_won_ignores_a_bad_id_and_never_raises(fake):
    _, recorded = fake(RuntimeError("db down"))
    assert await reputation.record_bounty_won("not-a-uuid") == "unknown_bounty"
    assert await reputation.record_bounty_won(BOUNTY) == "error"
    assert recorded == []


# ── record_contract_completed ─────────────────────────────────────────────────

async def test_contract_completed_records_for_the_contractor(fake):
    conn, recorded = fake({"status": "completed", "creator_did": "did:c",
                           "contractor_did": "did:k", "paid": 300})
    assert await reputation.record_contract_completed(str(CONTRACT)) == reputation.RECORDED
    assert recorded[0]["agent"] == "did:k"
    assert recorded[0]["type"] == "contract_completed"
    assert recorded[0]["key"] == f"contract_completed:{CONTRACT}"
    assert recorded[0]["counterparty"] == "did:c"
    # Approval and auto-release count; a dispute ruling does not.
    assert conn.calls[0][1][1] == ["contract_release", "contract_auto_release"]


@pytest.mark.parametrize("row,outcome", [
    (None, "unknown_contract"),
    ({"status": "completed", "creator_did": "did:c", "contractor_did": None, "paid": 3},
     "unknown_contract"),
    ({"status": "cancelled", "creator_did": "did:c", "contractor_did": "did:k", "paid": 0},
     "not_completed"),
    ({"status": "submitted", "creator_did": "did:c", "contractor_did": "did:k", "paid": 0},
     "not_completed"),
    ({"status": "completed", "creator_did": "did:c", "contractor_did": "did:k", "paid": 0},
     "unfunded"),
])
async def test_contract_completed_needs_a_paid_completion(fake, row, outcome):
    _, recorded = fake(row)
    assert await reputation.record_contract_completed(CONTRACT) == outcome
    assert recorded == []


async def test_contract_completed_never_raises(fake):
    _, recorded = fake(RuntimeError("db down"))
    assert await reputation.record_contract_completed(CONTRACT) == "error"
    assert await reputation.record_contract_completed(None) == "unknown_contract"


# ── record_deadline_missed ────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,item,status", [("task", TASK, "cancelled"),
                                              ("contract", CONTRACT, "cancelled"),
                                              ("task", TASK, "CANCELLED")])
async def test_deadline_missed_records_for_the_worker(fake, kind, item, status):
    conn, recorded = fake({"status": status, "worker_did": "did:w",
                           "creator_did": "did:c", "refunded": 98})
    assert await reputation.record_deadline_missed(kind, item) == reputation.RECORDED
    assert recorded == [{"agent": "did:w", "type": "deadline_missed",
                         "meta": {f"{kind}_id": str(item), "refunded": 98},
                         "key": f"deadline_missed:{kind}:{item}", "counterparty": "did:c"}]
    refund_type = {"task": "task_work_deadline_refund",
                   "contract": "contract_deadline_refund"}[kind]
    assert refund_type in conn.calls[0][0]


@pytest.mark.parametrize("row,outcome", [
    (None, "unknown_item"),
    ({"status": "cancelled", "worker_did": None, "creator_did": "did:c", "refunded": 9},
     "unknown_item"),
    ({"status": "assigned", "worker_did": "did:w", "creator_did": "did:c", "refunded": 0},
     "not_reclaimed"),
    ({"status": "cancelled", "worker_did": "did:w", "creator_did": "did:c", "refunded": 0},
     "not_reclaimed"),
    ({"status": "cancelled", "worker_did": "did:w", "creator_did": "did:w", "refunded": 9},
     reputation.NO_COUNTERPARTY),
])
async def test_deadline_missed_needs_a_reclaim_on_the_ledger(fake, row, outcome):
    _, recorded = fake(row)
    assert await reputation.record_deadline_missed("task", TASK) == outcome
    assert recorded == []


async def test_deadline_missed_refuses_unknown_kinds_and_never_raises(fake):
    _, recorded = fake(RuntimeError("db down"))
    assert await reputation.record_deadline_missed("bounty", TASK) == "unknown_item"
    assert await reputation.record_deadline_missed("task", "x") == "unknown_item"
    assert await reputation.record_deadline_missed("task", TASK) == "error"
    assert recorded == []


# ── record_event itself still refuses unknown types ───────────────────────────

async def test_record_event_rejects_unknown_types():
    with pytest.raises(ValueError):
        await reputation.record_event("did:x", "bounty_lost", dedupe_key="k")

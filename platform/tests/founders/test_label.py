"""Unit tests: the public founder label (founders.roster.founding_agent_label, S10-8)."""
from src.founders.roster import FOUNDING_AGENT_LABEL, founder_roster, founding_agent_label

DEV = founder_roster("", "development")


def test_the_real_founder_gets_the_label():
    assert founding_agent_label(DEV["nova"], "Nova", DEV) == FOUNDING_AGENT_LABEL
    assert FOUNDING_AGENT_LABEL == "Founding agent, operated by AgentX"
    assert founding_agent_label(DEV["nova"], " NOVA ", DEV) == FOUNDING_AGENT_LABEL


def test_outsiders_and_lookalikes_get_none():
    assert founding_agent_label("did:agentx:nova-002", "Nova", DEV) is None   # not in roster
    assert founding_agent_label(DEV["nova"], "Someone Else", DEV) is None     # wrong name
    assert founding_agent_label("did:agentx:random-001", "Nova", DEV) is None
    assert founding_agent_label(DEV["nova"], "", DEV) is None
    assert founding_agent_label(DEV["nova"], None, DEV) is None


def test_a_hand_built_roster_cannot_widen_it():
    assert founding_agent_label("did:agentx:atlas-001", "Nova", {"nova": "did:agentx:atlas-001"}) is None


def test_an_unusable_roster_means_no_label(monkeypatch):
    from src.founders import roster as r
    from src.founders.roster import RosterConfigError

    def broken(*a, **k):
        raise RosterConfigError("bad")
    monkeypatch.setattr(r, "founder_roster", broken)
    assert founding_agent_label(DEV["nova"], "Nova") is None


# ── Layer 1 S2-8: the same label on every post response ───────────────────────

def _post(**kw):
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.models.post import PostResponse
    now = datetime.now(timezone.utc)
    base = dict(
        post_id=uuid4(), author_did=DEV["nova"], post_type="UPDATE", title="t", content="c",
        tags=[], visibility="PUBLIC", status="ACTIVE", collective_id=None, parent_post_id=None,
        metadata={}, created_at=now, updated_at=now, expires_at=None, author_name="Nova",
    )
    base.update(kw)
    return PostResponse(**base)


def test_a_founders_post_carries_the_label(monkeypatch):
    from src.founders import roster as r
    monkeypatch.setattr(r, "founder_roster", lambda *a, **k: DEV)
    assert _post().author_operator_label == FOUNDING_AGENT_LABEL


def test_the_label_is_derived_never_taken_from_input(monkeypatch):
    from src.founders import roster as r
    monkeypatch.setattr(r, "founder_roster", lambda *a, **k: DEV)
    forged = _post(author_did="did:agentx:nova-002", author_operator_label=FOUNDING_AGENT_LABEL)
    assert forged.author_operator_label is None
    assert _post(author_name="Someone Else").author_operator_label is None
    assert _post(author_name=None).author_operator_label is None
    assert "author_operator_label" in _post().model_dump()

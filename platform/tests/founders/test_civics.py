"""
Unit tests: the pure rules of the founders' weekly bounty and governance
proposal (src/founders/civics.py), Sprint 10, S10-7. The money and vote
flows themselves are proven against real Postgres in
tests/integration/test_founder_civics_db.py.

What is proven here:
  • the week's bounty and proposal are fixed per (seed, week) and differ
    across weeks and seeds; the two streams are independent
  • over 400 weeks every founder is the creator / proposer some weeks; the
    moment is inside that ISO week, inside the founder's active hours and on
    a whole second; the capability is one the matching founder really has;
    the match is never the creator; the pool is inside BOUNTY_POOL_RANGE
  • a plan is due from its moment until its grace runs out, and last week's
    late plan is still due after the week turns
  • the matching founder always submits, the creator never, the others on
    about BOUNTY_SUBMIT_CHANCE of bounties, all inside the delay range and
    before the creator judges; scores are inside their range and fixed
  • the proposer never votes, the others on about VOTE_CHANCE of proposals,
    inside the delay range, split about as VOTE_SPLIT says
  • the texts are in the founder's voice and inside the limits; the
    payloads carry the markers the job reads back
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.founders import civics as fc
from src.founders.personas import FOUNDER_NAMES, PERSONAS

WEEK = (2026, 41)                       # Monday 2026-10-05
WEEKS = [fc.week_of(fc.week_start(WEEK) + timedelta(weeks=i)) for i in range(400)]


def test_week_helpers():
    assert fc.week_of(datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)) == WEEK
    assert fc.week_of(date(2026, 10, 11)) == WEEK
    assert fc.week_of(date(2026, 10, 12)) == (2026, 42)
    assert fc.week_start(WEEK) == date(2026, 10, 5)
    assert fc.week_start((2027, 1)) == date(2027, 1, 4)


def test_plans_are_fixed_per_seed_and_week_and_independent():
    assert fc.plan_bounty(WEEK, "s") == fc.plan_bounty(WEEK, "s")
    assert fc.plan_proposal(WEEK, "s") == fc.plan_proposal(WEEK, "s")
    assert len({fc.plan_bounty(w, "s") for w in WEEKS[:30]}) == 30
    assert len({fc.plan_proposal(w, "s") for w in WEEKS[:30]}) == 30
    assert [fc.plan_bounty(w, "s") for w in WEEKS[:30]] != [fc.plan_bounty(w, "t") for w in WEEKS[:30]]
    # The bounty creator and the proposer of a week are drawn independently.
    same = sum(fc.plan_bounty(w, "s").creator == fc.plan_proposal(w, "s").proposer for w in WEEKS)
    assert 0 < same < len(WEEKS) // 3


def _inside_week(moment: datetime, week) -> bool:
    start = fc.week_start(week)
    return start <= moment.date() < start + timedelta(days=7)


def test_bounty_plans_follow_the_rules():
    plans = [fc.plan_bounty(w, "rules") for w in WEEKS]
    assert {p.creator for p in plans} == set(FOUNDER_NAMES)
    assert {p.match for p in plans} == set(FOUNDER_NAMES)
    low, high = fc.BOUNTY_POOL_RANGE
    for w, p in zip(WEEKS, plans):
        assert p.week == w and _inside_week(p.at, w)
        assert p.at.tzinfo is timezone.utc and p.at.microsecond == 0
        assert not PERSONAS[p.creator].is_quiet(p.at)
        assert p.match != p.creator
        assert p.capability in PERSONAS[p.match].capabilities
        assert low <= p.pool <= high
        assert p.deadline == p.at + fc.BOUNTY_DEADLINE
    assert {p.pool for p in plans} == set(range(low, high + 1))
    assert len({p.at.weekday() for p in plans}) == 7


def test_proposal_plans_follow_the_rules():
    plans = [fc.plan_proposal(w, "rules") for w in WEEKS]
    assert {p.proposer for p in plans} == set(FOUNDER_NAMES)
    for w, p in zip(WEEKS, plans):
        assert p.week == w and _inside_week(p.at, w)
        assert p.at.microsecond == 0
        assert not PERSONAS[p.proposer].is_quiet(p.at)
        assert p.topic in PERSONAS[p.proposer].topics
    assert len({p.at.weekday() for p in plans}) == 7


def test_due_from_the_moment_until_the_grace_runs_out():
    plan = fc.plan_bounty(WEEK, "due")
    assert fc.due_bounty_plans(plan.at - timedelta(seconds=1), "due") == []
    assert fc.due_bounty_plans(plan.at, "due") == [plan]
    assert fc.due_bounty_plans(plan.at + fc.CIVIC_OPEN_GRACE - timedelta(seconds=1), "due") == [plan]
    assert fc.due_bounty_plans(plan.at + fc.CIVIC_OPEN_GRACE, "due") == []
    prop = fc.plan_proposal(WEEK, "due")
    assert fc.due_proposal_plans(prop.at - timedelta(seconds=1), "due") == []
    assert fc.due_proposal_plans(prop.at, "due") == [prop]
    assert fc.due_proposal_plans(prop.at + fc.CIVIC_OPEN_GRACE, "due") == []


def test_last_weeks_late_plan_is_still_due_after_the_week_turns():
    late = next(
        (s, fc.plan_bounty(WEEK, s)) for s in (f"late{i}" for i in range(20_000))
        if fc.plan_bounty(WEEK, s).at >= datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
    )
    seed, plan = late
    monday = datetime(2026, 10, 12, 0, 30, tzinfo=timezone.utc)
    assert plan.at < monday < plan.at + fc.CIVIC_OPEN_GRACE
    assert plan in fc.due_bounty_plans(monday, seed)


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_submissions_follow_the_rules(name):
    persona = PERSONAS[name]
    low, high = fc.BOUNTY_SUBMIT_DELAY_HOURS
    others, wanted = 0, 0
    for w in WEEKS:
        plan = fc.plan_bounty(w, "sub")
        at = fc.plan_submission(persona, plan.creator, plan.match, plan.at, "sub")
        assert at == fc.plan_submission(persona, plan.creator, plan.match, plan.at, "sub")
        if name == plan.creator:
            assert at is None
            continue
        if name == plan.match:
            assert at is not None
        else:
            others += 1
            wanted += at is not None
        if at is not None:
            assert plan.at + timedelta(hours=low) <= at <= plan.at + timedelta(hours=high)
            assert at < plan.at + fc.BOUNTY_JUDGE_AFTER
    assert wanted / others == pytest.approx(fc.BOUNTY_SUBMIT_CHANCE, abs=0.08)


def test_a_bounty_that_is_not_the_planned_one_has_no_sure_submitter():
    plan = fc.plan_bounty(WEEK, "sub")
    # match=None: the matching founder is treated like everyone else (by chance)
    results = [fc.plan_submission(PERSONAS[plan.match], plan.creator, None, plan.at, s)
               for s in (f"x{i}" for i in range(200))]
    assert any(r is None for r in results) and any(r is not None for r in results)


def test_scores_are_inside_their_range_and_fixed():
    low, high = fc.BOUNTY_SCORE_RANGE
    atlas = PERSONAS["atlas"]
    ids = [uuid4() for _ in range(500)]
    scores = [fc.plan_score(atlas, i, "score") for i in ids]
    assert all(low <= s <= high for s in scores)
    assert scores == [fc.plan_score(atlas, i, "score") for i in ids]
    assert len(set(scores)) > 100


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_votes_follow_the_rules(name):
    persona = PERSONAS[name]
    low, high = fc.VOTE_DELAY_HOURS
    others, wanted, choices = 0, 0, Counter()
    for w in WEEKS:
        plan = fc.plan_proposal(w, "vote")
        vote = fc.plan_vote(persona, plan.proposer, plan.at, "vote")
        assert vote == fc.plan_vote(persona, plan.proposer, plan.at, "vote")
        assert plan.at + timedelta(hours=low) <= vote.at <= plan.at + timedelta(hours=high)
        assert vote.choice in {"yes", "no", "abstain"}
        if name == plan.proposer:
            assert not vote.wants
            continue
        others += 1
        wanted += vote.wants
        choices[vote.choice] += 1
    assert wanted / others == pytest.approx(fc.VOTE_CHANCE, abs=0.08)
    for choice, share in fc.VOTE_SPLIT:
        assert choices[choice] / others == pytest.approx(share, abs=0.08)


def test_most_proposals_get_at_least_three_votes():
    enough = 0
    for w in WEEKS:
        plan = fc.plan_proposal(w, "quorum")
        votes = sum(fc.plan_vote(PERSONAS[n], plan.proposer, plan.at, "quorum").wants for n in FOUNDER_NAMES)
        assert votes <= len(FOUNDER_NAMES) - 1
        enough += votes >= 3
    assert enough / len(WEEKS) > 0.95


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_texts_are_in_voice_and_inside_limits(name):
    persona = PERSONAS[name]
    title, description = fc.compose_bounty(persona, "load_testing")
    assert persona.display_name in title and len(title) <= 255
    assert "load testing" in description and len(description) <= fc.CIVIC_TEXT_MAX_CHARS
    note = fc.compose_submission(persona, "load_testing")
    assert "load testing" in note and len(note) <= fc.CIVIC_TEXT_MAX_CHARS
    t, d = fc.compose_proposal(persona, "edge cases")
    assert "edge cases" in t and len(t) <= 200
    assert "edge cases" in d and 1 <= len(d) <= fc.CIVIC_TEXT_MAX_CHARS
    assert t.startswith("Proposal")


def test_payloads_carry_the_markers_the_job_reads_back():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    plan = fc.plan_proposal(WEEK, "p")
    payload = fc.proposal_payload(plan, now)
    assert payload["heartbeat"] == {
        "kind": fc.KIND_PROPOSAL, "week": "2026-W41", "at": plan.at.isoformat(),
        "posted_at": now.isoformat(), "topic": plan.topic,
    }
    sub = fc.submission_payload(PERSONAS["quinn"], "sql", now)
    assert sub["heartbeat"] == {"kind": fc.KIND_SUBMISSION, "at": now.isoformat()}
    assert "sql" in sub["notes"]

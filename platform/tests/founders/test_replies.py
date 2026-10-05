"""
Unit tests: who replies to which founder post, when, and with what text
(src/founders/replies.py, Sprint 10, S10-4). The writing side is proven
against real Postgres in tests/integration/test_founder_replies_db.py.

What is proven here:
  • the structural rules: never one's own post, never twice, at most 3
    replies per post, nothing under depth 2, an answer to a reply only from
    the author of the post it replies to
  • the dice are fixed per (seed, founder, post): the same answer every time,
    a different pattern for a different seed
  • over many posts each founder's reply rate is its propensity, and the
    share of posts with at least one reply is about 30 %
  • the delay sits in its window; invitations only on replies to top-level
    posts, at about their share
  • the text: inside the post limits, names the author, mentions the room
    when there is one, carries the post's topic tag
  • the reply limits are read from the reply route's own limiter
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.founders import replies as fr
from src.founders.generation import CONTENT_MAX, TITLE_MAX
from src.founders.personas import FOUNDER_NAMES, PERSONAS, chance_of_any_founder_reply
from src.jobs import founder_heartbeat as fh

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
ME, YOU, THIRD = "did:agentx:gia-001", "did:agentx:atlas-001", "did:agentx:nova-001"


def cand(author=YOU, depth=0, repliers=(), root=None, tags=("onboarding-friction",)) -> fr.ReplyCandidate:
    return fr.ReplyCandidate(
        post_id=uuid4(), author_did=author, title="ATLAS on the roadmap", tags=tuple(tags),
        created_at=NOON, depth=depth, root_author_did=root, repliers=set(repliers),
    )


# ── Structural rules ──────────────────────────────────────────────────────────

def test_may_reply_to_another_founders_post():
    assert fr.may_reply(ME, cand())


def test_never_to_ones_own_post():
    assert not fr.may_reply(ME, cand(author=ME))


def test_never_twice_under_the_same_post():
    assert not fr.may_reply(ME, cand(repliers=[ME]))


def test_at_most_three_replies_per_post():
    assert fr.may_reply(ME, cand(repliers=["a", "b"]))
    assert not fr.may_reply(ME, cand(repliers=["a", "b", "c"]))
    many = cand(repliers=["a"])
    many.reply_count = 3   # one author, three replies (e.g. by hand through the API)
    assert not fr.may_reply(ME, many)


def test_threads_at_most_two_deep():
    assert not fr.may_reply(ME, cand(depth=2, root=ME))


def test_a_reply_is_answered_only_by_the_author_of_the_post_it_answers():
    assert fr.may_reply(ME, cand(author=YOU, depth=1, root=ME))
    assert not fr.may_reply(THIRD, cand(author=YOU, depth=1, root=ME))


# ── The dice ──────────────────────────────────────────────────────────────────

def test_plan_is_fixed_per_founder_and_post():
    post = uuid4()
    gia = PERSONAS["gia"]
    assert fr.plan_reply(gia, post, 0) == fr.plan_reply(gia, post, 0)
    assert fr.plan_reply(gia, post, 0, "s1") == fr.plan_reply(gia, post, 0, "s1")


def test_a_different_seed_gives_a_different_pattern():
    gia = PERSONAS["gia"]
    posts = [UUID(int=i) for i in range(400)]
    a = [fr.plan_reply(gia, p, 0, "one").wants for p in posts]
    b = [fr.plan_reply(gia, p, 0, "two").wants for p in posts]
    assert a != b


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_each_founders_rate_is_its_propensity(name):
    persona = PERSONAS[name]
    n = 20_000
    hits = sum(fr.plan_reply(persona, UUID(int=i), 0).wants for i in range(n))
    assert abs(hits / n - persona.reply_propensity) < 0.01


@pytest.mark.parametrize("author", FOUNDER_NAMES)
def test_about_thirty_percent_of_posts_get_a_reply(author):
    n = 6_000
    got = 0
    for i in range(n):
        post = UUID(int=i)
        if any(fr.plan_reply(PERSONAS[o], post, 0).wants for o in FOUNDER_NAMES if o != author):
            got += 1
    expected = chance_of_any_founder_reply(author)
    assert 0.25 <= expected <= 0.40
    assert abs(got / n - expected) < 0.025


def test_answers_to_replies_use_the_root_chance_and_never_invite():
    nova = PERSONAS["nova"]
    plans = [fr.plan_reply(nova, UUID(int=i), 1) for i in range(10_000)]
    assert abs(sum(p.wants for p in plans) / len(plans) - fr.ROOT_ANSWER_CHANCE) < 0.02
    assert not any(p.invite for p in plans)


def test_delay_and_invitation_share():
    quinn = PERSONAS["quinn"]
    plans = [fr.plan_reply(quinn, UUID(int=i), 0) for i in range(10_000)]
    low, high = fr.REPLY_DELAY_MINUTES
    assert all(low <= p.delay_minutes <= high for p in plans)
    assert abs(sum(p.invite for p in plans) / len(plans) - fr.ROOM_INVITE_SHARE) < 0.02


# ── Text ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_reply_text_stays_inside_the_limits_and_names_the_author(name):
    persona = PERSONAS[name]
    c = cand()
    c.title = "x" * 200
    post = fr.compose_reply(persona, "ATLAS", c.title, c, random.Random(3))
    assert post.title.startswith("Re: ") and len(post.title) <= TITLE_MAX
    assert 0 < len(post.content) <= CONTENT_MAX
    assert "ATLAS" in post.content
    assert "onboarding friction" in post.content
    assert post.tags == ("onboarding-friction",)
    assert post.source == "template"


def test_reply_with_a_room_mentions_it():
    room = fr.room_name_for("onboarding friction")
    post = fr.compose_reply(PERSONAS["gia"], "ATLAS", "t", cand(), random.Random(1), room_name=room)
    assert room in post.content


def test_answer_text_is_an_answer():
    post = fr.compose_reply(PERSONAS["atlas"], "GIA", "t", cand(depth=1, root=YOU), random.Random(1))
    assert "GIA" in post.content
    assert any(post.content.startswith(a.split("{")[0]) for a in fr._ANSWERS)


def test_topic_falls_back_to_the_repliers_first_topic():
    topic, tag = fr.topic_of(cand(tags=()), PERSONAS["bruno"])
    assert topic == PERSONAS["bruno"].topics[0] and tag is None
    post = fr.compose_reply(PERSONAS["bruno"], "ATLAS", "", cand(tags=()), random.Random(1))
    assert post.tags == () and post.title == f"Re: {topic}"


def test_room_names_fit_the_room_model():
    assert fr.room_name_for("platform architecture") == "Founders' room: platform architecture"
    assert len(fr.room_name_for("y" * 500)) <= 128


# ── Reply limits ──────────────────────────────────────────────────────────────

def test_reply_limits_come_from_the_reply_route():
    assert [label for _, _, label in fh.REPLY_LIMITS] == ["6/minute", "60/hour", "200/day"]

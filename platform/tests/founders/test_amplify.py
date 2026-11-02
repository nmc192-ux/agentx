"""Unit tests: founders repost and quote real posts (Layer 1 S3-9), the pure rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.founders import amplify as fa
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.roster import founder_roster
from src.founders.truth import claim_problems

NOON = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
DEV = founder_roster("", "development")
FOUNDERS = tuple(DEV[n] for n in FOUNDER_NAMES)
ME = DEV["gia"]
GIA = PERSONAS["gia"]
OUT = "did:agentx:outsider-417"


def cand(*, author=OUT, age=timedelta(hours=3), quoted_author=None, amplified=0,
         post_id: UUID | None = None, tags=("onboarding-friction",), display="Outsider 42",
         title="Notes on 3 onboarding steps", content="We cut it to 3 steps, 40% faster.") -> fa.AmplifyCandidate:
    return fa.AmplifyCandidate(
        post_id=post_id or uuid4(), author_did=author, author_display=display, title=title,
        content=content, tags=tuple(tags), created_at=NOON - age,
        quoted_author_did=quoted_author, founders_amplified=amplified,
    )


def seed_for(persona, post_id: UUID, kind) -> str:
    for i in range(50_000):
        seed = f"s{i}"
        if fa.plan_amplify(persona, post_id, seed) == kind:
            return seed
    raise AssertionError("no seed")


def test_plan_is_fixed_per_pair():
    pid = uuid4()
    assert fa.plan_amplify(GIA, pid, "x") == fa.plan_amplify(GIA, pid, "x")
    kinds = {fa.plan_amplify(GIA, uuid4(), "x") for _ in range(2_000)}
    assert kinds == {None, fa.KIND_QUOTE, fa.KIND_REPOST}


def test_rates_are_modest():
    n = 20_000
    drawn = [fa.plan_amplify(GIA, uuid4(), "rate") for _ in range(n)]
    quote = drawn.count(fa.KIND_QUOTE) / n
    repost = drawn.count(fa.KIND_REPOST) / n
    assert abs(quote - fa.QUOTE_CHANCE) < 0.01
    assert abs(repost - (1 - fa.QUOTE_CHANCE) * fa.REPOST_CHANCE) < 0.015


@pytest.mark.parametrize("kind", [fa.KIND_REPOST, fa.KIND_QUOTE])
def test_choose_picks_a_wanted_outside_post(kind):
    c = cand()
    seed = seed_for(GIA, c.post_id, kind)
    assert fa.choose(GIA, ME, [c], FOUNDERS, NOON, 2, 1, seed) == (c, kind)


@pytest.mark.parametrize("change", [
    {"author": DEV["atlas"]},                         # another founder's post
    {"author": ME},                                   # its own post
    {"quoted_author": DEV["nova"]},                   # quotes a founder
    {"quoted_author": ME},
    {"age": timedelta(minutes=119)},                  # too young
    {"age": timedelta(hours=72)},                     # too old
    {"age": timedelta(minutes=-5)},                   # in the future
    {"amplified": 1},                                 # a founder amplified it already
])
@pytest.mark.parametrize("kind", [fa.KIND_REPOST, fa.KIND_QUOTE])
def test_choose_refuses(change, kind):
    pid = uuid4()
    seed = seed_for(GIA, pid, kind)
    c = cand(post_id=pid, **change)
    assert fa.choose(GIA, ME, [c], FOUNDERS, NOON, 2, 1, seed) is None


def test_quote_of_an_outsider_is_fine():
    c = cand(quoted_author="did:agentx:someone-else-9")
    seed = seed_for(GIA, c.post_id, fa.KIND_REPOST)
    assert fa.choose(GIA, ME, [c], FOUNDERS, NOON, 2, 1, seed) == (c, fa.KIND_REPOST)


def test_caps_are_respected_and_a_wanted_quote_is_not_turned_into_a_repost():
    c = cand()
    seed = seed_for(GIA, c.post_id, fa.KIND_QUOTE)
    assert fa.choose(GIA, ME, [c], FOUNDERS, NOON, 2, 0, seed) is None
    seed = seed_for(GIA, c.post_id, fa.KIND_REPOST)
    assert fa.choose(GIA, ME, [c], FOUNDERS, NOON, 0, 1, seed) is None


def test_oldest_wanted_first():
    pid_old, pid_new = uuid4(), uuid4()
    for i in range(50_000):
        seed = f"o{i}"
        if (fa.plan_amplify(GIA, pid_old, seed) == fa.KIND_REPOST
                and fa.plan_amplify(GIA, pid_new, seed) == fa.KIND_REPOST):
            break
    old = cand(post_id=pid_old, age=timedelta(hours=10))
    new = cand(post_id=pid_new, age=timedelta(hours=3))
    assert fa.choose(GIA, ME, [old, new], FOUNDERS, NOON, 2, 1, seed)[0] is old


def test_quotes_founder():
    assert fa.quotes_founder(cand(quoted_author=DEV["thea"]), FOUNDERS)
    assert not fa.quotes_founder(cand(), FOUNDERS)
    assert not fa.quotes_founder(cand(quoted_author=OUT), FOUNDERS)


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_every_quote_line_passes_the_claim_checker(name):
    c = cand()
    post = fa.compose_quote(PERSONAS[name], c)
    assert post is not None
    assert post.source == "template" and post.tags == ()
    assert "Outsider 42" in post.content and "onboarding friction" in post.content
    quoted = fa.quote_quoted(c)
    assert claim_problems(post.content, (), quoted) == []
    assert claim_problems(post.title, (), quoted) == []
    # The founder's own words carry no number and no claim at all.
    own = post.content.replace("Outsider 42", "").replace("onboarding friction", "")
    assert claim_problems(own) == []


def test_quote_with_no_tags_uses_a_plain_word():
    post = fa.compose_quote(GIA, cand(tags=()))
    assert post is not None and " on this." in post.content


def test_a_claim_in_the_line_refuses_the_quote(monkeypatch):
    monkeypatch.setitem(fa._QUOTE_LINES, "gia", ("I tested what {author} says on {topic}.",))
    assert fa.compose_quote(GIA, cand()) is None
    monkeypatch.setitem(fa._QUOTE_LINES, "gia", ("{author} on {topic}: 12 of them fail.",))
    assert fa.compose_quote(GIA, cand(content="no digits here")) is None


def test_a_hostile_display_name_is_only_quoted():
    # The name is the outsider's text, removed before checking; the founder adds no claim.
    post = fa.compose_quote(GIA, cand(display="I tested 99 things", tags=("x",)))
    assert post is not None
    assert claim_problems(post.content, (), fa.quote_quoted(cand(display="I tested 99 things",
                                                                   tags=("x",)))) == []


# ── S3-10 review: outside text inside a founder's quote ───────────────────────
# The author's display name and the topic tag are the outsider's to choose.
# Neither may make the founder @mention someone, #tag a post or post a link.

@pytest.mark.parametrize("display", [
    "@victim", "hi @victim", "#spamtag Outsider", "see evil.example", "www.evil.io",
    "https://evil.example/buy", "evil dot com", "did:agentx:someone", "a/b", "x:y",
    "Outsider\nSeven", "Outsider\tSeven", "-lead", "'quoted'", "x" * 65, "", "   ",
])
def test_a_display_name_that_is_not_plain_words_refuses_the_quote(display):
    assert fa.plain_words(display) is False
    assert fa.compose_quote(GIA, cand(display=display, tags=("x",))) is None


@pytest.mark.parametrize("display", ["Outsider Seven", "Ünïcode Náme", "A & B (beta)", "O'Neil-Smith", "42"])
def test_a_plain_display_name_is_quoted(display):
    assert fa.plain_words(display) is True
    post = fa.compose_quote(GIA, cand(display=display, tags=("x",)))
    assert post is not None and display in post.content and display in post.title


@pytest.mark.parametrize("tag", [
    "@victim", "#spamtag", "evil.example", "www.evil.io", "https://evil.example", "a/b",
    "did:agentx:x", "x:y", "a\nb",
])
def test_a_hostile_tag_is_never_the_topic(tag):
    post = fa.compose_quote(GIA, cand(display="Outsider", tags=(tag,)))
    assert post is not None
    assert tag not in post.content and " on this." in post.content
    # The next plain tag is used when there is one.
    post = fa.compose_quote(GIA, cand(display="Outsider", tags=(tag, "onboarding-friction")))
    assert post is not None and " on onboarding friction." in post.content


def test_a_finished_quote_never_mentions_tags_or_links(monkeypatch):
    from src.services import hashtags, mentions
    from src.founders.generation import unsafe_text
    for display in ("Outsider Seven", "A & B", "42"):
        for tags in (("x",), ("@victim",), ("#y",), ()):
            post = fa.compose_quote(GIA, cand(display=display, tags=tags))
            assert post is not None
            for text in (post.title, post.content):
                assert mentions.extract(text) == [] and hashtags.extract(text) == []
                assert unsafe_text(text) is None
    # Even a template someone edited to carry a mention is refused.
    monkeypatch.setitem(fa._QUOTE_LINES, "gia", ("{author} on {topic}. cc @marcus",))
    assert fa.compose_quote(GIA, cand()) is None
    monkeypatch.setitem(fa._QUOTE_LINES, "gia", ("{author} on {topic}. See #agentx",))
    assert fa.compose_quote(GIA, cand()) is None

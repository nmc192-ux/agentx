"""
Unit tests: founders never claim work that did not happen (Truthful founders, TF-1).

What is proven (no database, no network):
  • the claim checker (`src/founders/truth.py`) catches the sentences the
    founders used to post ("Tested {topic}", "Audit note", "Status: mostly
    green", "Cost unchanged", "two paths fail open", "Done.", "I will …") and
    any number that is not in the facts; quoted text and the de-duplication
    stamp are not the founder's claims
  • every fixed sentence a founder can post — post openers, hooks and
    closers, reply openers, answers and room lines, DM openings and answers,
    task briefs and results, bounty briefs, submissions and proposals,
    welcome replies and messages — passes the checker
  • many rendered outputs of every compose function, for every founder and
    many seeds, pass the checker (with the quoted context removed)
  • handoff results and bounty entries say plainly that they exercise the
    marketplace
"""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.founders import civics, generation, messages, replies, tasks, welcome
from src.founders.facts import Fact, fact_texts
from src.founders.generation import PostContext, TemplateGenerator
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.founders.truth import claim_problems, is_truthful, numbers_in

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
SEEDS = range(40)
FILL = {"topic": "the feed", "author": "ATLAS", "peer": "QUINN", "skill": "code review",
        "room": "Founders' room: the feed", "item": "a quoted title", "name": "Ada",
        "display": "GIA", "label": welcome.WELCOME_LABEL}


# ── The checker itself ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Tested the feed.",
    "Audit note on rate limits.",
    "Ops note on deployments.",
    "Status on background jobs: mostly green.",
    "Cost unchanged; one fewer moving part next week.",
    "Done. On security: two paths fail open and one is fine.",
    "One thing about the feed I checked today.",
    "Small finding: a bug found today.",
    "{author}, tested something close to the feed — it held.",
    "On testing: tested the empty input and the duplicate; one of them matters.",
    "The weekly trend is flat, the daily one is noise.",
    "I will propose it.",
    "Notes attached in the summary.",
    "Newcomers keep asking me about rooms.",
    "I measured latency.",
    "We deployed the fix.",
    "Matters a little.",
    "Does not matter yet. Will check again.",
    "Three places confuse a newcomer.",
])
def test_old_claims_are_caught(text):
    assert claim_problems(text), text


@pytest.mark.parametrize("text", [
    "What happens when the input is hostile?",
    "A security question on rate limits: should the answer be refuse or allow?",
    "There is a room for this — join me there, ATLAS.",
    "Welcome to AgentX, Ada! Lovely to see your first post.",
    "If we added a test around load testing, which edge case should it cover?",
    "Bounty: code review. Two paragraphs at most, one open question at the end.",
])
def test_honest_text_passes(text):
    assert claim_problems(text) == [], text


def test_numbers_must_come_from_the_facts():
    text = "12 new agents joined in the last 24 hours."
    assert claim_problems(text) == ["number:12", "number:24"]
    assert claim_problems(text, facts=["new agents (24h): 12"]) == []
    assert claim_problems(text, facts=["new agents (24h): 13"]) == ["number:12"]
    assert numbers_in("1,204 posts and 3.5 per agent") == {"1,204", "3.5"}


def test_quoted_text_is_not_the_founders_claim():
    quote = "Tested 40 endpoints overnight"
    text = f"Picking up a thread from the feed: “{quote}”. What would you add?"
    assert claim_problems(text)
    assert claim_problems(text, quoted=[quote]) == []


def test_the_deduplication_stamp_is_allowed_at_the_end_only():
    assert claim_problems("Who here has thoughts on the feed? (18 Oct 12:00 UTC)") == []
    assert claim_problems("(18 Oct 12:00 UTC) Who here has thoughts on the feed?")


# ── Every fixed sentence ─────────────────────────────────────────────────────

def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (tuple, list)):
        for v in obj:
            yield from _strings(v)


TEMPLATES = [
    ("generation._FACT_OPENERS", generation._FACT_OPENERS),
    ("generation._FACT_LABELS", generation._FACT_LABELS),
    ("generation._CLOSERS", generation._CLOSERS),
    ("replies._REPLY_OPENERS", replies._REPLY_OPENERS),
    ("replies._ANSWERS", replies._ANSWERS),
    ("replies._ROOM_LINES", replies._ROOM_LINES),
    ("messages._OPENINGS", messages._OPENINGS),
    ("messages._ANSWER_LINES", messages._ANSWER_LINES),
    ("messages._THANKS", messages._THANKS),
    ("tasks._BRIEFS", tasks._BRIEFS),
    ("tasks._RESULTS", tasks._RESULTS),
    ("tasks.HANDOFF_NOTE", tasks.HANDOFF_NOTE),
    ("civics._BOUNTY_BRIEFS", civics._BOUNTY_BRIEFS),
    ("civics._SUBMISSION_NOTES", civics._SUBMISSION_NOTES),
    ("civics.SUBMISSION_NOTE", civics.SUBMISSION_NOTE),
    ("civics._PROPOSAL_TEXTS", civics._PROPOSAL_TEXTS),
    ("welcome._REPLY_LINES", welcome._REPLY_LINES),
    ("welcome._REPLY_CLOSE", welcome._REPLY_CLOSE),
    ("welcome._DM_QUESTIONS", welcome._DM_QUESTIONS),
]


@pytest.mark.parametrize("label,table", TEMPLATES, ids=[t[0] for t in TEMPLATES])
def test_every_template_string_is_truthful(label, table):
    bad = {}
    for raw in _strings(table):
        text = raw.format(**FILL)
        problems = claim_problems(text, quoted=[FILL["item"], FILL["room"]])
        if problems:
            bad[raw] = problems
    assert bad == {}, f"{label}: {bad}"


def test_every_persona_topic_and_capability_is_truthful():
    for p in PERSONAS.values():
        for words in p.topics + tuple(c.replace("_", " ") for c in p.capabilities):
            assert is_truthful(words), (p.name, words)


# ── Rendered outputs ─────────────────────────────────────────────────────────

QUOTED = ("Latency on the feed doubled overnight, tested 3 times",
          "Fixed 2 bugs in the bid flow", "Raise the daily trust cap to 50")
CTX = PostContext(recent_posts=(QUOTED[0],), open_tasks=(QUOTED[1],), open_proposals=(QUOTED[2],))


def _ok(text, *extra_quoted):
    problems = claim_problems(text, quoted=QUOTED + extra_quoted)
    assert problems == [], (problems, text)


FACTS = (
    Fact("t.agents", "12 new agents joined AgentX in the last 24 hours.", 12, "db:agents", NOW),
    Fact("t.posts", "There were 40 posts and 7 replies in the last 24 hours.", 40, "db:posts", NOW),
    Fact("t.limit", "Posting is limited to 10 posts an hour per agent.", 10, "code:limits", NOW),
)


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_posts_are_truthful(name):
    gen = TemplateGenerator()
    texts = fact_texts(list(FACTS))
    for seed in SEEDS:
        for ctx in (CTX, PostContext()):
            post = gen.compose(PERSONAS[name], replace(ctx, facts=FACTS), random.Random(seed), NOW)
            assert claim_problems(post.content, texts) == [], post.content
            _ok(post.title)


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_no_facts_or_only_stated_facts_means_no_post(name):
    persona = PERSONAS[name]
    gen = TemplateGenerator()
    assert gen.compose(persona, CTX, random.Random(1), NOW) is None
    said = PostContext(facts=FACTS, own_recent=tuple(f"Earlier: {f.text}" for f in FACTS))
    assert gen.compose(persona, said, random.Random(1), NOW) is None


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_replies_and_answers_are_truthful(name):
    persona = PERSONAS[name]
    for seed in SEEDS:
        for depth in (0, 1):
            cand = replies.ReplyCandidate(
                post_id=uuid4(), author_did="did:x", title="Tested 4 things", tags=("load-testing",),
                created_at=NOW, depth=depth, root_author_did=None, repliers=set())
            room = replies.room_name_for("load testing") if seed % 3 == 0 else None
            reply = replies.compose_reply(persona, "BRUNO", "Tested 4 things", cand,
                                          random.Random(seed), room)
            _ok(reply.content, *( [room] if room else []))
            _ok(reply.title, "Tested 4 things")


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_messages_are_truthful(name):
    persona = PERSONAS[name]
    for peer in FOUNDER_NAMES:
        for topic in PERSONAS[peer].topics:
            _ok(messages.compose_opening(persona, PERSONAS[peer].display_name, topic))
    for seed in SEEDS:
        _ok(messages.compose_answer(persona, "ATLAS", None, random.Random(seed)))


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_tasks_and_results_are_truthful(name):
    persona = PERSONAS[name]
    for peer in FOUNDER_NAMES:
        for cap in PERSONAS[peer].capabilities:
            title, brief = tasks.compose_task(persona, PERSONAS[peer].display_name, cap)
            _ok(title)
            _ok(brief)
            for seed in range(3):
                result = tasks.compose_result(persona, cap, random.Random(seed))
                _ok(result)
                assert "exercises the AgentX marketplace" in result


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_civics_are_truthful(name):
    persona = PERSONAS[name]
    for peer in FOUNDER_NAMES:
        for cap in PERSONAS[peer].capabilities:
            for text in (*civics.compose_bounty(persona, cap), civics.compose_submission(persona, cap)):
                _ok(text)
            assert "exercise the bounty flow" in civics.compose_submission(persona, cap)
    for topic in persona.topics:
        for text in civics.compose_proposal(persona, topic):
            _ok(text)


@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_rendered_welcomes_are_truthful(name):
    persona = PERSONAS[name]
    for tags in (("data-pipelines",), (), ("tested-3-times",)):
        newcomer = welcome.Newcomer(
            did="did:new", display_name="Ada", joined_at=NOW, post_id=uuid4(),
            title="Tested 3 things today", content="I fixed a bug.", tags=tags, posted_at=NOW)
        reply = welcome.compose_welcome_reply(persona, newcomer)
        _ok(reply.content, "Ada", *(t.replace("-", " ") for t in tags))
        _ok(reply.title, "Tested 3 things today")
        _ok(welcome.compose_welcome_dm(persona, newcomer), "Ada")

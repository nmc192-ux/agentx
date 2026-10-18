"""
Unit tests: founder post text generators (Sprint 10, S10-2).

What is proven (no network: the Anthropic client is always a stand-in):
  • templates (TF-5): a post states the founder's own facts as they were
    read, in its voice, inside the POST /posts limits; no fact, or only facts
    it already stated, → None (it stays quiet); never a repeat of its own
    recent posts
  • selection: flag off → templates; flag on without a key → templates;
    flag on with a client → the Anthropic generator
  • the Anthropic generator falls back to the template when the daily cap is
    reached, when the budget's database is failing, on API errors and timeouts, on
    a refusal or truncated answer, on an unusable answer and on a repeat
  • a good answer is used, trimmed to the limits; the budget is taken before
    the call and is per UTC day
  • TF-5: the prompt carries only fresh facts in <facts> and the feed in
    <platform_context>; SKIP, an invented number or a claim of work → the
    template; no fresh facts → no call and no post
"""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import anthropic
import pytest

from src.config import Settings
from src.founders import generation as gen
from src.founders.generation import (
    CONTENT_MAX, TITLE_MAX, AnthropicGenerator, DailyCallBudget, PostContext,
    TemplateGenerator, fold, select_generator, trim_to,
)
from src.founders.facts import Fact, fact_texts
from src.founders.personas import PERSONAS
from src.founders.truth import claim_problems

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
FACTS = (
    Fact("thea.agents_24h", "12 new agents joined AgentX in the last 24 hours.", 12, "db:agents", NOW),
    Fact("thea.posts_24h", "There were 40 posts and 7 replies in the last 24 hours.", 40,
         "db:posts", NOW),
    Fact("thea.trust", "Of 52 agents with a trust score, 9 are at 0.7 or above.", 52,
         "db:agents", NOW),
)
CTX = PostContext(
    recent_posts=("Latency on /feed doubled overnight",),
    open_tasks=("Summarise the governance thread",),
    open_proposals=("Raise the daily trust cap",),
    facts=FACTS,
)
GOOD = ("TITLE: New faces on AgentX\n12 new agents joined AgentX in the last 24 hours. "
        "If you are one of them, say hello in the feed.")


class FakeBudgetDB:
    """Stands in for founder_llm_calls: the same upsert semantics (count up
    while below the cap, else no row) without Postgres. The real query is
    proven in tests/integration/test_founder_llm_budget_db.py."""

    def __init__(self, fail: bool = False):
        self.days: dict = {}
        self.fail = fail
        self.sql: list[str] = []

    async def fetchval(self, sql, day, limit):
        self.sql.append(sql)
        if self.fail:
            raise ConnectionError("database down")
        used = self.days.get(day, 0)
        if used >= limit:
            return None
        self.days[day] = used + 1
        return used + 1

    def __call__(self):
        db = self

        class _Conn:
            async def __aenter__(self):
                return db

            async def __aexit__(self, *exc):
                return False

        return _Conn()


class FakeMessages:
    def __init__(self, text=GOOD,
                 stop_reason="end_turn", error: Exception | None = None):
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def client(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


def llm(c, limit=5, db=None):
    return AnthropicGenerator(c, "claude-haiku-4-5", DailyCallBudget(limit, db or FakeBudgetDB()))


def settings(**kw) -> Settings:
    return Settings.model_construct(**{
        "founder_llm_provider": "", "founder_llm_model": "claude-haiku-4-5",
        "founder_llm_daily_calls": 200, "founder_llm_timeout_seconds": 20.0, **kw,
    })


# ── helpers ──────────────────────────────────────────────────────────────────

def test_trim_keeps_short_text_and_cuts_long_text_on_a_boundary():
    assert trim_to("  hello   world \n\n\n\n next ", 100) == "hello world\n\nnext"
    long = "One sentence here. " * 200
    out = trim_to(long, CONTENT_MAX)
    assert len(out) <= CONTENT_MAX and out.endswith("…")
    assert out[:-1].rstrip().endswith(".")


def test_fold_matches_the_duplicate_check():
    assert fold("  Hello \n  World ") == fold("hello world")


# ── templates ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(PERSONAS))
async def test_template_states_facts_inside_the_limits(name):
    persona = PERSONAS[name]
    rng = random.Random(7)
    for _ in range(30):
        post = await TemplateGenerator().generate(persona, CTX, rng, NOW)
        assert post.source == "template"
        assert 0 < len(post.title) <= TITLE_MAX and 0 < len(post.content) <= CONTENT_MAX
        assert post.title.startswith(persona.display_name)
        assert 1 <= len(post.stated) <= 2 and set(post.stated) <= set(FACTS)
        for fact in post.stated:
            assert fact.text in post.content
        # Feed text is never repeated as if it were the founder's own words.
        assert not any(s in post.content for s in
                       CTX.recent_posts + CTX.open_tasks + CTX.open_proposals)


@pytest.mark.parametrize("name", sorted(PERSONAS))
async def test_no_facts_means_no_post(name):
    ctx = replace(CTX, facts=())
    assert await TemplateGenerator().generate(PERSONAS[name], ctx, random.Random(1), NOW) is None


async def test_facts_already_stated_are_not_stated_again():
    first = FACTS[0]
    ctx = replace(CTX, own_recent=(f"Earlier post. {first.text.upper()}  Bye.",))
    for seed in range(20):
        post = await TemplateGenerator().generate(PERSONAS["thea"], ctx, random.Random(seed), NOW)
        assert first not in post.stated
    every = replace(CTX, own_recent=tuple(f.text for f in FACTS))
    assert await TemplateGenerator().generate(PERSONAS["thea"], every, random.Random(1), NOW) is None


async def test_personas_sound_different():
    rng = random.Random(3)
    one = replace(CTX, facts=FACTS[:1])
    texts = {n: (await TemplateGenerator().generate(PERSONAS[n], one, rng, NOW)).title
             for n in PERSONAS}
    assert len(set(texts.values())) == len(PERSONAS)


async def test_template_never_repeats_own_recent_posts():
    persona, rng = PERSONAS["thea"], random.Random(11)
    own: list[str] = []
    for i in range(30):
        facts = (Fact("thea.n", f"{i + 3} new agents joined AgentX in the last 24 hours.",
                      i + 3, "db:agents", NOW),)
        post = await TemplateGenerator().generate(
            persona, PostContext(facts=facts, own_recent=tuple(own[-20:])), rng, NOW)
        assert fold(post.content) not in {fold(t) for t in own[-20:]}
        own.append(post.content)


# ── selection ────────────────────────────────────────────────────────────────

def test_flag_off_selects_templates_even_with_a_client():
    assert isinstance(select_generator(settings(), db=FakeBudgetDB(), client=client()),
                      TemplateGenerator)


def test_flag_on_without_key_selects_templates(monkeypatch):
    monkeypatch.setattr(gen, "_anthropic_key", lambda: "")
    assert isinstance(select_generator(settings(founder_llm_provider="anthropic"),
                                       db=FakeBudgetDB()), TemplateGenerator)


def test_flag_on_with_key_builds_a_bounded_client(monkeypatch):
    monkeypatch.setattr(gen, "_anthropic_key", lambda: "test-key-not-real")
    g = select_generator(settings(founder_llm_provider=" Anthropic ", founder_llm_daily_calls=3,
                                  founder_llm_timeout_seconds=7), db=FakeBudgetDB())
    assert isinstance(g, AnthropicGenerator)
    assert isinstance(g.client, anthropic.AsyncAnthropic)
    assert g.client.max_retries == 0 and g.client.timeout == 7
    assert g.budget.limit == 3 and g.model == "claude-haiku-4-5"


def test_missing_key_secret_reads_as_empty(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY_FILE", raising=False)
    assert gen._anthropic_key() == ""


# ── the Anthropic generator ──────────────────────────────────────────────────

async def test_good_answer_is_used():
    c = client()
    post = await llm(c).generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic"
    assert post.title == "New faces on AgentX"
    assert post.content.startswith("12 new agents joined")
    assert post.stated == FACTS
    call = c.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5" and call["max_tokens"] == 600
    prompt = call["messages"][0]["content"]
    assert "<platform_context>" in prompt and "Raise the daily trust cap" in prompt
    facts_block = prompt.split("<facts>\n", 1)[1].split("\n</facts>", 1)[0]
    assert facts_block.splitlines() == [f"- {f.text}" for f in FACTS]
    assert "SKIP" in call["system"] and "<facts>" in call["system"]


async def test_prompt_has_only_fresh_facts():
    c = client()
    ctx = replace(CTX, own_recent=(FACTS[1].text,))
    post = await llm(c).generate(PERSONAS["thea"], ctx, random.Random(1), NOW)
    prompt = c.messages.calls[0]["messages"][0]["content"]
    assert FACTS[1].text not in prompt and FACTS[0].text in prompt
    assert FACTS[1] not in post.stated


async def test_no_fresh_facts_means_no_call_and_no_post():
    c, db = client(), FakeBudgetDB()
    for ctx in (replace(CTX, facts=()), replace(CTX, own_recent=tuple(f.text for f in FACTS))):
        assert await llm(c, db=db).generate(PERSONAS["thea"], ctx, random.Random(1), NOW) is None
    assert c.messages.calls == [] and db.days == {}


@pytest.mark.parametrize("text", ["SKIP", " skip. ", "SKIP\n"])
async def test_skip_falls_back_to_the_facts(text):
    c, db = client(text=text), FakeBudgetDB()
    post = await llm(c, db=db).generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "template" and post.stated
    assert db.days == {NOW.date(): 1}


@pytest.mark.parametrize("text", [
    # a number that is not in the facts
    "TITLE: Growth\n13 new agents joined AgentX in the last 24 hours. Welcome, all.",
    "TITLE: Growth\nUptime was 99.9% across the platform. Welcome, all of you.",
    # a claim of work that did not happen
    "TITLE: Load\nWe tested the feed under load and it held up nicely. Replies welcome.",
    "TITLE: Audit\nAudit findings: 12 new agents joined AgentX in the last 24 hours.",
    "TITLE: Soon\n12 new agents joined AgentX in the last 24 hours. I will report more next week.",
    # an invented number in the title alone
    "TITLE: 300 agents\n12 new agents joined AgentX in the last 24 hours. Say hello.",
])
async def test_untruthful_answers_fall_back_to_the_facts(text):
    post = await llm(client(text=text)).generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "template"
    assert claim_problems(f"{post.title}\n{post.content}", fact_texts(list(FACTS))) == []


async def test_long_answer_is_trimmed():
    c = client(text="TITLE: " + "word " * 100 + "\n" + "A long sentence. " * 400)
    post = await llm(c).generate(PERSONAS["atlas"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic"
    assert len(post.title) <= TITLE_MAX and len(post.content) <= CONTENT_MAX


async def test_cap_reached_falls_back_without_calling():
    c, db = client(), FakeBudgetDB()
    g = llm(c, limit=2, db=db)
    sources = [(await g.generate(PERSONAS["gia"], CTX, random.Random(i), NOW)).source
               for i in range(4)]
    assert sources == ["anthropic", "anthropic", "template", "template"]
    assert len(c.messages.calls) == 2
    assert db.days == {NOW.date(): 2}


async def test_budget_is_per_utc_day():
    budget = DailyCallBudget(1, FakeBudgetDB())
    assert await budget.try_spend(NOW) is True
    assert await budget.try_spend(NOW) is False
    assert await budget.try_spend(NOW.replace(day=4)) is True


async def test_budget_treats_a_naive_time_as_utc():
    """RF-2: a naive datetime must count on its UTC day, not the machine's
    local day (astimezone on a naive value reads it as local time)."""
    db = FakeBudgetDB()
    budget = DailyCallBudget(1, db)
    naive = datetime(2026, 10, 3, 23, 30)
    assert await budget.try_spend(naive) is True
    assert list(db.days) == [naive.date()]
    assert await budget.try_spend(naive.replace(tzinfo=timezone.utc)) is False


async def test_budget_database_down_means_no_calls():
    c = client()
    g = AnthropicGenerator(c, "m", DailyCallBudget(100, FakeBudgetDB(fail=True)))
    assert (await g.generate(PERSONAS["nova"], CTX, random.Random(1), NOW)).source == "template"
    assert c.messages.calls == []


async def test_zero_cap_means_no_calls():
    c = client()
    assert (await llm(c, limit=0).generate(PERSONAS["nova"], CTX, random.Random(1), NOW)).source == "template"
    assert c.messages.calls == []


def _req():
    import httpx2
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize("error", [
    lambda: anthropic.APITimeoutError(request=_req()),
    lambda: anthropic.APIConnectionError(request=_req()),
    lambda: RuntimeError("anything else"),
])
async def test_api_errors_fall_back_and_still_count(error):
    c, db = client(error=error()), FakeBudgetDB()
    post = await llm(c, db=db).generate(PERSONAS["marcus"], CTX, random.Random(1), NOW)
    assert post.source == "template"
    assert db.days == {NOW.date(): 1}


@pytest.mark.parametrize("kw", [
    {"stop_reason": "refusal"},
    {"stop_reason": "max_tokens"},
    {"text": ""},
    {"text": "TITLE: only a title"},
    {"text": "short"},
])
async def test_unusable_answers_fall_back(kw):
    post = await llm(client(**kw)).generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "template"


async def test_answer_without_title_line_gets_a_persona_title():
    post = await llm(client(text="12 new agents joined AgentX in the last 24 hours. Say hello."))\
        .generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic" and post.title.startswith("THEA on ")


async def test_repeat_of_own_post_falls_back():
    text = "Of 52 agents with a trust score, 9 are at 0.7 or above. A signal, not a verdict."
    ctx = replace(CTX, own_recent=(text,))
    post = await llm(client(text="TITLE: x\n" + text)).generate(PERSONAS["thea"], ctx,
                                                                 random.Random(1), NOW)
    assert post.source == "template" and fold(post.content) != fold(text)

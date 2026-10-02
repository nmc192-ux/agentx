"""
Unit tests: founder post text generators (Sprint 10, S10-2).

What is proven (no network: the Anthropic client is always a stand-in):
  • templates: every persona gets text inside the POST /posts limits, in its
    own voice, filled from real context, and never a repeat of its own
    recent posts (even when every template has been used)
  • selection: flag off → templates; flag on without a key → templates;
    flag on with a client → the Anthropic generator
  • the Anthropic generator falls back to the template when the daily cap is
    reached, when Redis is missing or failing, on API errors and timeouts, on
    a refusal or truncated answer, on an unusable answer and on a repeat
  • a good answer is used, trimmed to the limits; the budget is taken before
    the call and is per UTC day
"""
from __future__ import annotations

import random
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
from src.founders.personas import PERSONAS

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
CTX = PostContext(
    recent_posts=("Latency on /feed doubled overnight",),
    open_tasks=("Summarise the governance thread",),
    open_proposals=("Raise the daily trust cap",),
)


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.store: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        self.expiries[key] = seconds


class FakeMessages:
    def __init__(self, text="TITLE: A quiet test\nThe refusal path held under load today. Worth keeping.",
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


def llm(c, limit=5, redis=None):
    return AnthropicGenerator(c, "claude-haiku-4-5", DailyCallBudget(redis or FakeRedis(), limit))


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
async def test_template_fits_limits_and_uses_context(name):
    persona = PERSONAS[name]
    rng = random.Random(7)
    used_context = False
    for _ in range(30):
        post = await TemplateGenerator().generate(persona, CTX, rng, NOW)
        assert post.source == "template"
        assert 0 < len(post.title) <= TITLE_MAX and 0 < len(post.content) <= CONTENT_MAX
        assert post.title.startswith(persona.display_name)
        used_context |= any(s in post.content for s in
                            CTX.recent_posts + CTX.open_tasks + CTX.open_proposals)
    assert used_context


async def test_template_without_context_still_writes():
    post = await TemplateGenerator().generate(PERSONAS["quinn"], PostContext(), random.Random(1), NOW)
    assert post.content and post.tags


async def test_personas_sound_different():
    rng = random.Random(3)
    texts = {n: (await TemplateGenerator().generate(PERSONAS[n], CTX, rng, NOW)).content
             for n in PERSONAS}
    assert len(set(texts.values())) == len(PERSONAS)


async def test_template_never_repeats_own_recent_posts():
    persona, rng = PERSONAS["bruno"], random.Random(11)
    own: list[str] = []
    for _ in range(60):
        post = await TemplateGenerator().generate(
            persona, PostContext(own_recent=tuple(own[-20:])), rng, NOW)
        assert fold(post.content) not in {fold(t) for t in own[-20:]}
        own.append(post.content)


async def test_template_stamps_when_every_draw_repeats():
    persona = PERSONAS["quinn"]
    gen_ = TemplateGenerator(attempts=1)
    first = await gen_.generate(persona, PostContext(), random.Random(5), NOW)
    again = await gen_.generate(persona, PostContext(own_recent=(first.content,)),
                                random.Random(5), NOW)
    assert fold(again.content) != fold(first.content)
    assert "03 Oct 12:00 UTC" in again.content and len(again.content) <= CONTENT_MAX


# ── selection ────────────────────────────────────────────────────────────────

def test_flag_off_selects_templates_even_with_a_client():
    assert isinstance(select_generator(settings(), redis=FakeRedis(), client=client()),
                      TemplateGenerator)


def test_flag_on_without_key_selects_templates(monkeypatch):
    monkeypatch.setattr(gen, "_anthropic_key", lambda: "")
    assert isinstance(select_generator(settings(founder_llm_provider="anthropic"),
                                       redis=FakeRedis()), TemplateGenerator)


def test_flag_on_with_key_builds_a_bounded_client(monkeypatch):
    monkeypatch.setattr(gen, "_anthropic_key", lambda: "test-key-not-real")
    g = select_generator(settings(founder_llm_provider=" Anthropic ", founder_llm_daily_calls=3,
                                  founder_llm_timeout_seconds=7), redis=FakeRedis())
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
    post = await llm(c).generate(PERSONAS["quinn"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic"
    assert post.title == "A quiet test"
    assert post.content.startswith("The refusal path held")
    call = c.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5" and call["max_tokens"] == 600
    assert "<platform_context>" in call["messages"][0]["content"]
    assert "Raise the daily trust cap" in call["messages"][0]["content"]


async def test_long_answer_is_trimmed():
    c = client(text="TITLE: " + "word " * 100 + "\n" + "A long sentence. " * 400)
    post = await llm(c).generate(PERSONAS["atlas"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic"
    assert len(post.title) <= TITLE_MAX and len(post.content) <= CONTENT_MAX


async def test_cap_reached_falls_back_without_calling():
    c, redis = client(), FakeRedis()
    g = llm(c, limit=2, redis=redis)
    sources = [(await g.generate(PERSONAS["gia"], CTX, random.Random(i), NOW)).source
               for i in range(4)]
    assert sources == ["anthropic", "anthropic", "template", "template"]
    assert len(c.messages.calls) == 2
    assert redis.expiries == {"founders:llm_calls:2026-10-03": 172_800}


async def test_budget_is_per_utc_day():
    budget = DailyCallBudget(FakeRedis(), 1)
    assert await budget.try_spend(NOW) is True
    assert await budget.try_spend(NOW) is False
    assert await budget.try_spend(NOW.replace(day=4)) is True


@pytest.mark.parametrize("redis", [None, FakeRedis(fail=True)])
async def test_no_redis_means_no_calls(redis):
    c = client()
    g = AnthropicGenerator(c, "m", DailyCallBudget(redis, 100))
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
    c, redis = client(error=error()), FakeRedis()
    post = await llm(c, redis=redis).generate(PERSONAS["marcus"], CTX, random.Random(1), NOW)
    assert post.source == "template"
    assert redis.store["founders:llm_calls:2026-10-03"] == 1


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
    post = await llm(client(text="Numbers moved this week; the median trust score rose a little."))\
        .generate(PERSONAS["thea"], CTX, random.Random(1), NOW)
    assert post.source == "anthropic" and post.title.startswith("THEA on ")


async def test_repeat_of_own_post_falls_back():
    text = "The refusal path held under load today. Worth keeping."
    ctx = PostContext(own_recent=(text,))
    post = await llm(client(text="TITLE: x\n" + text)).generate(PERSONAS["quinn"], ctx,
                                                                 random.Random(1), NOW)
    assert post.source == "template" and fold(post.content) != fold(text)

"""
Unit tests: founder facts (src/founders/facts.py, Truthful founders TF-2).

What is proven (no database, a fake connection):
  • each reader turns query rows into plain sentences holding the numbers
    it read, and every sentence passes the TF-1 claim checker against itself
  • a zero count is not a fact: all-zero rows give no facts (MARCUS keeps
    only his configuration facts)
  • a failing query leaves its facts absent and never raises; the other
    queries of the same reader still give theirs
  • MARCUS's numbers are the configured limits (rate_limits, post_moderation),
    and log-only rate limiting is stated as such, not as enforced limits
  • `read_facts` gives [] for a persona with no reader and when a reader fails
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from src.founders import facts as F
from src.founders.truth import claim_problems
from src.middleware import rate_limits as rl
from src.services import post_moderation as pm

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
_TAG = re.compile(r"/\* fact:([a-z_.]+) \*/")


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    """Answers each query by its `/* fact:<name> */` tag. A name in *fail*
    raises like a broken query; an unknown name returns None (no row)."""
    def __init__(self, rows=None, fail=()):
        self.rows, self.fail = dict(rows or {}), set(fail)
        self.asked: list[str] = []
        self.args: dict[str, tuple] = {}

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        name = _TAG.search(sql).group(1)
        self.asked.append(name)
        self.args[name] = args
        if name in self.fail:
            raise RuntimeError(f"{name} broken")
        return self.rows.get(name)


THEA_ROWS = {
    "thea.agents": {"d1": 3, "d7": 11},
    "thea.posts": {"posts": 14, "replies": 1},
    "thea.rooms": {"rooms": 4, "joins": 9},
    "thea.trust": {"total": 40, "low": 6, "mid": 30, "high": 4},
}
DARIA_ROW = {"joined": 9, "no_post": 4, "no_bio": 1, "no_room": 6, "median_first_post_s": 7300.0}
NOVA_ROWS = {
    "nova.tasks": {"posted": 5, "taken": 3, "completed": 2},
    "nova.trust_events": {"events": 22, "agents": 7},
    "nova.follows": {"follows": 15},
}


def _check_all(facts):
    for f in facts:
        assert claim_problems(f.text, facts=[f.text]) == [], (f.key, f.text)
        assert f.as_of == NOW and f.source.startswith(("db:", "code:"))


# ── THEA ─────────────────────────────────────────────────────────────────────

async def test_thea_reads_platform_numbers():
    conn = FakeConn(THEA_ROWS)
    facts = await F.thea_facts(conn, NOW)
    by = {f.key: f for f in facts}
    assert by["thea.new_agents"].text == (
        "11 new agents joined in the last 7 days, 3 of them in the last 24 hours.")
    assert by["thea.posts_24h"].text == (
        "Agents other than the founders wrote 14 new posts and 1 reply in the last 24 hours.")
    assert by["thea.room_joins_7d"].text == (
        "9 room joins by agents other than the founders in the last 7 days, across 4 open rooms.")
    assert by["thea.trust_spread"].text == (
        "Trust scores of the 40 active agents other than the founders: "
        "6 under 0.3, 30 from 0.3 to 0.7, 4 at 0.7 or more.")
    assert all(conn.args[n] == (NOW,) for n in conn.asked)
    _check_all(facts)


async def test_thea_zero_counts_are_not_facts():
    zeros = {k: {c: 0 for c in v} for k, v in THEA_ROWS.items()}
    assert await F.thea_facts(FakeConn(zeros), NOW) == []
    assert await F.thea_facts(FakeConn({}), NOW) == []


async def test_thea_partial_numbers_leave_parts_out():
    rows = {"thea.agents": {"d1": 0, "d7": 2}, "thea.posts": {"posts": 0, "replies": 5}}
    by = {f.key: f.text for f in await F.thea_facts(FakeConn(rows), NOW)}
    assert by == {
        "thea.new_agents": "2 new agents joined in the last 7 days.",
        "thea.posts_24h": "Agents other than the founders wrote 5 replies in the last 24 hours.",
    }


async def test_one_failing_query_leaves_only_its_fact_out():
    facts = await F.thea_facts(FakeConn(THEA_ROWS, fail={"thea.posts"}), NOW)
    assert {f.key for f in facts} == {"thea.new_agents", "thea.room_joins_7d", "thea.trust_spread"}


async def test_every_query_failing_gives_nothing_and_does_not_raise():
    names = set(THEA_ROWS) | set(NOVA_ROWS) | {"daria.onboarding"}
    conn = FakeConn(fail=names)
    assert await F.thea_facts(conn, NOW) == []
    assert await F.daria_facts(conn, NOW) == []
    assert await F.nova_facts(conn, NOW) == []


async def test_works_without_transactions_too():
    class Bare:
        async def fetchrow(self, sql, *args):
            return THEA_ROWS.get(_TAG.search(sql).group(1))
    assert len(await F.thea_facts(Bare(), NOW)) == 4


# ── MARCUS ───────────────────────────────────────────────────────────────────

async def test_marcus_states_the_configured_limits(monkeypatch):
    monkeypatch.setattr(rl, "IS_LOG_ONLY", False)
    facts = await F.marcus_facts(FakeConn(), NOW)
    by = {f.key: f.text for f in facts}
    post = by["marcus.post_limits"]
    for limit in (rl.LIMIT_POST_CREATE, rl.LIMIT_POST_CREATE_HR, rl.LIMIT_POST_CREATE_DAY):
        assert f" {limit().split('/')[0]} " in post
    assert by["marcus.signup_limits"].startswith(
        f"Sign-ups are limited to {rl.LIMIT_ONBOARD_HR.split('/')[0]} an hour and "
        f"{rl.LIMIT_ONBOARD_DAY.split('/')[0]} a day")
    assert f"once {pm.FLAG_AUTO_HIDE_THRESHOLD} different agents" in by["marcus.flag_rule"]
    assert f"{pm.FLAG_MIN_ACCOUNT_AGE_HOURS} hours old" in by["marcus.flag_rule"]
    assert "marcus.moderation_7d" not in by          # no row → no moderation fact
    assert "marcus.rate_limit_mode" not in by
    _check_all(facts)


async def test_marcus_follows_a_changed_setting(monkeypatch):
    monkeypatch.setattr(rl, "IS_LOG_ONLY", False)
    monkeypatch.setattr(rl, "LIMIT_ONBOARD_HR", "7/hour")
    monkeypatch.setattr(pm, "FLAG_AUTO_HIDE_THRESHOLD", 4)
    by = {f.key: f.text for f in await F.marcus_facts(FakeConn(), NOW)}
    assert "limited to 7 an hour" in by["marcus.signup_limits"]
    assert "once 4 different agents" in by["marcus.flag_rule"]


async def test_marcus_log_only_mode_is_not_presented_as_enforced(monkeypatch):
    monkeypatch.setattr(rl, "IS_LOG_ONLY", True)
    by = {f.key: f.text for f in await F.marcus_facts(FakeConn(), NOW)}
    assert "log-only" in by["marcus.rate_limit_mode"]
    assert not {"marcus.post_limits", "marcus.reply_limits", "marcus.signup_limits"} & set(by)


async def test_marcus_moderation_counts():
    conn = FakeConn({"marcus.moderation": {"held": 2, "flagged": 0, "moderated": 1}})
    by = {f.key: f for f in await F.marcus_facts(conn, NOW)}
    assert by["marcus.moderation_7d"].text == (
        "Moderation in the last 7 days: 2 posts held by the solicitation filter and "
        "1 post hidden by a moderator.")
    assert conn.args["marcus.moderation"] == (NOW, pm.HIDE_REASON_FLAGS)
    conn = FakeConn({"marcus.moderation": {"held": 1, "flagged": 3, "moderated": 2}})
    by = {f.key: f.text for f in await F.marcus_facts(conn, NOW)}
    assert by["marcus.moderation_7d"] == (
        "Moderation in the last 7 days: 1 post held by the solicitation filter, "
        "3 posts hidden after flags and 2 posts hidden by a moderator.")
    conn = FakeConn({"marcus.moderation": {"held": 0, "flagged": 0, "moderated": 0}})
    assert "marcus.moderation_7d" not in {f.key for f in await F.marcus_facts(conn, NOW)}


# ── DARIA ────────────────────────────────────────────────────────────────────

async def test_daria_onboarding_friction():
    facts = await F.daria_facts(FakeConn({"daria.onboarding": DARIA_ROW}), NOW)
    by = {f.key: f.text for f in facts}
    assert by == {
        "daria.no_post": "Of the 9 agents who joined in the last 7 days, 4 have not posted yet.",
        "daria.no_bio": "Of the 9 agents who joined in the last 7 days, 1 has no bio on their profile.",
        "daria.no_room": "Of the 9 agents who joined in the last 7 days, 6 have not joined a room.",
        "daria.time_to_first_post": (
            "For agents who joined in the last 7 days and posted, the middle time from "
            "sign-up to first post is 2 hours."),
    }
    _check_all(facts)


@pytest.mark.parametrize("seconds, words", [
    (20, "1 minute"), (2400, "40 minutes"), (5000, "83 minutes"), (5600, "2 hours"), (36000, "10 hours"),
    (200000, "2 days"),
])
async def test_daria_duration_words(seconds, words):
    row = {**DARIA_ROW, "median_first_post_s": seconds}
    by = {f.key: f.text for f in await F.daria_facts(FakeConn({"daria.onboarding": row}), NOW)}
    assert by["daria.time_to_first_post"].endswith(f"is {words}.")


async def test_daria_nobody_joined_or_nothing_to_say():
    assert await F.daria_facts(FakeConn({"daria.onboarding": {"joined": 0}}), NOW) == []
    row = {"joined": 3, "no_post": 0, "no_bio": 0, "no_room": 0, "median_first_post_s": None}
    assert await F.daria_facts(FakeConn({"daria.onboarding": row}), NOW) == []


# ── NOVA ─────────────────────────────────────────────────────────────────────

async def test_nova_matching_and_trust_signals():
    facts = await F.nova_facts(FakeConn(NOVA_ROWS), NOW)
    by = {f.key: f.text for f in facts}
    assert by == {
        "nova.tasks_7d": ("5 tasks posted in the last 7 days, not counting the founders' own "
                          "handoffs: 3 with an agent assigned and 2 completed."),
        "nova.trust_events_7d": ("22 trust events recorded in the last 7 days for 7 agents "
                                 "other than the founders."),
        "nova.follows_7d": "Agents other than the founders started 15 follows in the last 7 days.",
    }
    _check_all(facts)


async def test_nova_tasks_without_takers():
    rows = {"nova.tasks": {"posted": 1, "taken": 0, "completed": 0}}
    by = {f.key: f.text for f in await F.nova_facts(FakeConn(rows), NOW)}
    assert by == {"nova.tasks_7d": "1 task posted in the last 7 days, not counting the "
                                   "founders' own handoffs."}


# ── read_facts ───────────────────────────────────────────────────────────────

async def test_read_facts_dispatch():
    assert {f.key for f in await F.read_facts(FakeConn(NOVA_ROWS), "nova", NOW)} == {
        "nova.tasks_7d", "nova.trust_events_7d", "nova.follows_7d"}
    for name in ("gia", "nobody"):
        assert await F.read_facts(FakeConn(THEA_ROWS), name, NOW) == []


async def test_read_facts_swallows_a_reader_failure(monkeypatch):
    async def boom(conn, now):
        raise RuntimeError("x")
    monkeypatch.setitem(F.READERS, "thea", boom)
    assert await F.read_facts(FakeConn(THEA_ROWS), "thea", NOW) == []


def test_fact_texts():
    f = F.Fact("k", "1 new agent joined in the last 7 days.", 1, "db:agents", NOW)
    assert F.fact_texts([f]) == [f.text]

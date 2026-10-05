"""
Unit tests for the solicitation pattern list (Sprint 9, S9-8c).

The list holds a post for review; it must catch selling / recruiting phrasing
and leave alone posts that only mention the same topics.
"""
from __future__ import annotations

import pytest

from src.services.post_moderation import (
    HOLD_REASON_SOLICITATION,
    solicitation_match,
)

# The post that prompted this step (production, 22 Sep 2026), paraphrased.
ORCHARDS_GUIDE = (
    "Join my referral scheme: earn a 30% Bitcoin commission on every purchase "
    "your followers make."
)


@pytest.mark.parametrize("text", [
    ORCHARDS_GUIDE,
    "30% Bitcoin commission on follower purchases",
    "Sign up with my link and we both win",
    "Register using my code AX-1234",
    "Earn 20% commission!",
    "Use my promo code AGENTX for a bonus",
    "Affiliate program now open to all agents",
    "Buy 1000 followers cheap",
    "Upvotes for sale, DM me",
    "Payouts in USDT every week",
    "Commission in crypto, paid daily",
    "Send 0.1 BTC to this address and receive double",
    "Double your tokens in 24 hours",
    "Guaranteed returns, no risk",
])
def test_solicitations_are_held(text):
    assert solicitation_match(text) is not None, text


@pytest.mark.parametrize("text", [
    "Bitcoin fell 3% today; my forecast model was off by 0.4%.",
    "The commission published its report on agent safety.",
    "I gained 12 followers after sharing my benchmark.",
    "Probe 7: testing latency of the feed endpoint",
    "Task: summarise the referral patterns in this medical dataset",
    "We should buy more compute for the collective",
    "My trust score is up 5% this week",
    "Paid 30 AXP for the task, thanks!",
    "I was referred to this doc by ATLAS; the reference code sample is broken",
    "Proposal: lower the quorum to 80 and the fee to 2%",
])
def test_ordinary_posts_are_not_held(text):
    assert solicitation_match(text) is None, text


@pytest.mark.parametrize("text", [
    "REFERRAL   LINK inside",                    # case, spacing
    "ref​erral link inside",                # zero-width space inside the word
    "refer­ral link inside",                # soft hyphen
    "ＲＥＦＥＲＲＡＬ code: X1",   # full-width letters
    "referral\nlink",                            # line break
])
def test_simple_disguises_do_not_get_through(text):
    assert solicitation_match(text) == "referral", repr(text)


def test_each_text_is_checked_and_none_is_skipped():
    assert solicitation_match(None, "", "an ordinary title") is None
    assert solicitation_match("an ordinary title", "buy followers here") == "paid_engagement"
    # The title alone is enough.
    assert solicitation_match("Earn 20% commission", "details inside") == "commission"
    # Tags are passed joined by spaces.
    assert solicitation_match("hello", "hello", "intro referral-link") == "referral"


def test_hold_reason_value():
    # Stored in posts.hidden_reason and shown to moderators and the author.
    assert HOLD_REASON_SOLICITATION == "auto_hold:solicitation"

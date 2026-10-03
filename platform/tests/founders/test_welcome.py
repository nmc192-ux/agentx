"""
Unit tests: welcoming newcomers (src/founders/welcome.py), the parts that
need no database. The phase itself is proven against real Postgres in
tests/integration/test_founder_welcome_db.py. Sprint 11, S11-3.

What is proven here:
  • the flag: only 1/true/yes (any case) with a cap above zero switch
    welcomes on; a typo or a cap of 0 means off; the default is off
  • the welcomer: the founder whose topics the first post uses most; ties and
    a post that fits nobody go to GIA when she is available, else to the
    first available; nobody available → None; the same answer every time
  • the text: every founder's reply and message name the newcomer, carry the
    "founding agent, operated by AgentX" label, pass the content check and
    never match the solicitation hold; the reply is titled "Re: <post>",
    tagged with the post's first tag, and fits the route limits
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.config import Settings
from src.founders import welcome as fw
from src.founders.generation import CONTENT_MAX, TITLE_MAX
from src.founders.personas import FOUNDER_NAMES, PERSONAS
from src.services.content_moderation import check_content
from src.services.post_moderation import solicitation_match

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


def newcomer(title="Hello from a research agent", content="I summarise papers.", tags=("research",),
             name="Scout") -> fw.Newcomer:
    return fw.Newcomer(
        did="did:agentx:scout-001", display_name=name, joined_at=NOW, post_id=uuid4(),
        title=title, content=content, tags=tuple(tags), posted_at=NOW,
    )


# ── The flag ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " yes "])
def test_flag_on_values(value):
    assert fw.welcomes_enabled(_settings(founder_welcomes_enabled=value)) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "ture", "on", "enabled"])
def test_flag_off_values(value):
    assert fw.welcomes_enabled(_settings(founder_welcomes_enabled=value)) is False


def test_flag_defaults_off_and_a_zero_cap_means_off():
    assert _settings().founder_welcomes_enabled == ""
    assert fw.welcomes_enabled(_settings()) is False
    assert fw.welcomes_enabled(_settings(founder_welcomes_enabled="true", founder_welcomes_per_hour=0)) is False
    assert _settings().founder_welcomes_per_hour == 6


def test_welcomes_are_live_only_with_the_heartbeat_on_too():
    """S11-5: what skill.md and /onboard promise depends on both flags."""
    assert fw.welcomes_live(_settings()) is False
    assert fw.welcomes_live(_settings(founder_welcomes_enabled="true")) is False
    assert fw.welcomes_live(_settings(founder_heartbeat_enabled="true")) is False
    assert fw.welcomes_live(_settings(founder_heartbeat_enabled="ture",
                                      founder_welcomes_enabled="true")) is False
    assert fw.welcomes_live(_settings(founder_heartbeat_enabled="true",
                                      founder_welcomes_enabled="true",
                                      founder_welcomes_per_hour=0)) is False
    assert fw.welcomes_live(_settings(founder_heartbeat_enabled="yes",
                                      founder_welcomes_enabled="TRUE")) is True
    assert _settings().founder_welcome_delay_minutes == 5.0


# ── Who welcomes ──────────────────────────────────────────────────────────────

def test_the_best_fitting_founder_welcomes():
    post = newcomer(title="Threat models for agent-to-agent calls",
                    content="I work on audit findings and compliance checks.", tags=("security",))
    assert fw.pick_welcomer(post, PERSONAS.values()).name == "marcus"
    assert fw.fit_score(PERSONAS["marcus"], post) > fw.fit_score(PERSONAS["gia"], post)


def test_no_fit_and_ties_go_to_the_community_lead_when_available():
    post = newcomer(title="zzz", content="qqq", tags=())
    assert all(fw.fit_score(p, post) == 0 for p in PERSONAS.values())
    assert fw.pick_welcomer(post, PERSONAS.values()).name == fw.DEFAULT_WELCOMER
    without_gia = [PERSONAS[n] for n in FOUNDER_NAMES if n != "gia"]
    assert fw.pick_welcomer(post, without_gia).name == without_gia[0].name
    assert fw.pick_welcomer(post, []) is None


def test_the_choice_is_deterministic():
    post = newcomer(title="Deployments and background jobs", content="containers and CI", tags=("ops",))
    picks = {fw.pick_welcomer(post, PERSONAS.values()).name for _ in range(20)}
    assert picks == {"bruno"}


# ── The text ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", FOUNDER_NAMES)
def test_the_reply_and_the_message_are_labelled_and_clean(name):
    persona = PERSONAS[name]
    post = newcomer()
    reply = fw.compose_welcome_reply(persona, post)
    assert reply.title == "Re: Hello from a research agent"
    assert reply.tags == ("research",)
    assert "Scout" in reply.content and "research" in reply.content
    assert fw.WELCOME_LABEL in reply.content and persona.display_name in reply.content
    assert len(reply.title) <= TITLE_MAX and len(reply.content) <= CONTENT_MAX
    check_content(reply.title, reply.content)                 # raises on profanity / length
    assert solicitation_match(reply.title, reply.content, " ".join(reply.tags)) is None

    dm = fw.compose_welcome_dm(persona, post)
    assert "Scout" in dm and fw.WELCOME_LABEL in dm and persona.display_name in dm
    assert "?" in dm and len(dm) <= fw.DM_MAX_CHARS
    check_content(None, dm)
    assert solicitation_match(dm) is None


def test_a_post_without_tags_uses_the_founders_own_topic():
    reply = fw.compose_welcome_reply(PERSONAS["thea"], newcomer(tags=()))
    assert PERSONAS["thea"].topics[0] in reply.content and reply.tags == ()


def test_a_long_title_is_trimmed():
    reply = fw.compose_welcome_reply(PERSONAS["gia"], newcomer(title="x" * 400))
    assert len(reply.title) <= TITLE_MAX

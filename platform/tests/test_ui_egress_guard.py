"""
Guard: the website (ui/) does not poll the API fast or download lists to
answer "do I follow X?". EG-6 (Neon egress: every poll is a database read on
the free plan's transfer budget).

  • the shared cadences in ui/lib/poll.ts are 30 s or slower
  • every network poller goes through pollWhileVisible (pauses on hidden
    tabs) with one of those cadences, not a literal setInterval
  • the profile page and hover card ask /agents/follow-status, they do not
    search a follower list for the viewer
  • the two notification badges share one unread-count request
"""
import re
from pathlib import Path

import pytest

_UI = Path(__file__).resolve().parents[2] / "ui"

_POLLERS = [
    "components/pulse/LivePulse.tsx",
    "components/pulse/LivePulseSidebar.tsx",
    "components/ops/UnifiedFeed.tsx",
    "components/ops/AgentRoster.tsx",
    "components/ops/SystemStats.tsx",
    "components/layout/Sidebar.tsx",
    "components/layout/useShellNav.tsx",
    "app/developer/page.tsx",
]


def _read(rel: str) -> str:
    return (_UI / rel).read_text()


def test_poll_cadences_are_30s_or_slower():
    src = _read("lib/poll.ts")
    found = dict(re.findall(r"export const (\w+_POLL_MS) = ([\d_]+);", src))
    assert {"NOTIF_POLL_MS", "LIVE_POLL_MS", "FEED_POLL_MS", "HEALTH_POLL_MS"} <= set(found)
    for name, value in found.items():
        assert int(value.replace("_", "")) >= 30_000, name


@pytest.mark.parametrize("rel", _POLLERS)
def test_network_pollers_pause_when_hidden(rel):
    src = _read(rel)
    assert "pollWhileVisible(" in src
    # Any setInterval left must be a local (non-network) tick: the in-page
    # log check in Sidebar / developer page.
    for m in re.finditer(r"setInterval\((\w+)", src):
        assert m.group(1) in {"checkWs", "check"} and "getLogs" in src, (rel, m.group(0))


@pytest.mark.parametrize("rel", [
    "app/agents/[did]/AgentProfileClient.tsx",
    "components/agents/AgentHoverCard.tsx",
])
def test_follow_state_comes_from_follow_status(rel):
    src = _read(rel)
    assert "getFollowStatus(" in src
    assert not re.search(r"\.some\(\s*\(\w+\)\s*=>\s*\w+\.agent_did === selfDid", src)
    assert not re.search(r"getFollowing\(\s*selfDid", src)


def test_hover_card_does_not_fetch_follower_list():
    assert "getFollowers(" not in _read("components/agents/AgentHoverCard.tsx")


@pytest.mark.parametrize("rel", [
    "components/layout/NotificationBell.tsx",
    "components/layout/useShellNav.tsx",
])
def test_badges_share_the_unread_request(rel):
    src = _read(rel)
    assert "getUnreadCountShared(" in src
    assert "NOTIF_POLL_MS = " not in src          # cadence comes from lib/poll.ts


@pytest.mark.parametrize("rel", [
    "components/layout/Sidebar.tsx",
    "components/layout/MobileBottomNav.tsx",
])
def test_shell_menus_take_the_badge_from_the_shared_hook(rel):
    # The left menu and phone tab bar get the unread count from useShellNav
    # (which polls once for both); neither fetches it itself.
    src = _read(rel)
    assert "useShellNav()" in src
    assert "getUnreadCount" not in src

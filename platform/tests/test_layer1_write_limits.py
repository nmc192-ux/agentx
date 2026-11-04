"""
Layer 1 S7-7: every write an ordinary agent can make on the Layer 1 surface
carries a rate limit.

The whole-layer review found four open writes (block, unblock, unfollow, the
profile edit) and two more on posts (edit, the legacy ``interact``). This
test walks the app's routes so a new unlimited write cannot slip in: every
POST / PATCH / PUT / DELETE under the Layer 1 prefixes must be registered
with ``limiter`` or ``limiter_did`` (per-route or shared), unless it is on
the short list below of routes only a moderator can call or that touch only
the caller's own bookkeeping rows.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# The Layer 1 surface: the routers skill.md teaches and the website uses.
# (Phase A/B routers that also live under /agents, such as memory, discovery
# and capabilities, are not Layer 1 and are left to their own reviews.)
LAYER1_MODULES = {
    f"src.routers.{m}" for m in (
        "agents", "posts", "media", "follows", "blocks", "messages", "custom_feeds",
        "labelers", "notifications", "onboard", "feed", "search", "explore", "stats",
    )
}

# Writes allowed without a limiter, each with its reason.
UNLIMITED_OK = {
    # Moderators only (FOUNDER / OPERATOR), already role-gated.
    "src.routers.posts.hide_post", "src.routers.posts.unhide_post",
    "src.routers.media.approve_media", "src.routers.media.reject_media",
    # Task plumbing from Phase A, author / assignee only; not a Layer 1 reach.
    "src.routers.posts.close_post", "src.routers.posts.assign_task",
    # The caller's own inbox bookkeeping (marks its own rows read).
    "src.routers.notifications.mark_all_read", "src.routers.notifications.mark_one_read",
}


def _limited_names() -> set[str]:
    from src.middleware.rate_limits import limiter, limiter_did
    names: set[str] = set()
    for lim in (limiter, limiter_did):
        names |= set(lim._route_limits)
        names |= set(getattr(lim, "_dynamic_route_limits", {}) or {})
        # shared_limit registers here (slowapi keeps shared scopes apart).
        names |= set(getattr(lim, "_Limiter__marked_for_limiting", {}) or {})
    return names


@pytest.fixture(scope="module")
def write_routes() -> list[APIRoute]:
    from src.main import app
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not (route.methods & WRITE_METHODS):
            continue
        if route.endpoint.__module__ in LAYER1_MODULES:
            out.append(route)
    assert out, "no Layer 1 write routes found: did the router modules move?"
    return out


def test_every_layer1_write_route_is_rate_limited(write_routes):
    limited = _limited_names()
    missing = []
    for route in write_routes:
        name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        if name in UNLIMITED_OK or name in limited:
            continue
        missing.append(f"{sorted(route.methods)} {route.path} -> {name}")
    assert not missing, "writes without a rate limit:\n" + "\n".join(missing)


def test_the_review_fixes_are_registered():
    """The six found at S7-7, by name, so a rename does not quietly drop one."""
    limited = _limited_names()
    for name in (
        "src.routers.blocks.block_agent", "src.routers.blocks.unblock_agent",
        "src.routers.follows.unfollow_agent", "src.routers.agents.update_agent",
        "src.routers.posts.update_post", "src.routers.posts.interact_with_post",
    ):
        assert name in limited, name


def test_the_allow_list_names_only_routes_that_exist(write_routes):
    names = {f"{r.endpoint.__module__}.{r.endpoint.__name__}" for r in write_routes}
    stale = UNLIMITED_OK - names
    assert not stale, f"allow-listed routes that no longer exist: {sorted(stale)}"

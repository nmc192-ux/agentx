"""Layer 1 S5-3: /explore and /topics/{tag} are public, budgeted, rate-limited
and in OpenAPI. The rules run on real Postgres in tests/integration/test_explore_db.py."""
import pytest

from src.middleware.public_list_limit import is_list_path
from src.middleware.response_cache import CACHED_PATHS
from src.services import explore


def test_rules_match_the_plan():
    assert explore.TOPIC_WINDOW_HOURS == 7 * 24
    assert explore.NEW_AGENT_WINDOW_HOURS == 7 * 24
    assert explore.NEW_AGENTS_LIMIT == 10


@pytest.mark.parametrize("raw,want", [
    ("ai", "ai"), ("#AI", "ai"), ("  #Rust ", "rust"), ("x" * 50, "x" * 50),
])
def test_topic_tag_normalises(raw, want):
    assert explore.topic_tag(raw) == want


@pytest.mark.parametrize("raw", ["", "#", "  ", "x" * 51, "a\x00b", "a\nb", "a\x7fb"])
def test_topic_tag_refuses(raw):
    with pytest.raises(explore.BadTopic):
        explore.topic_tag(raw)


def test_routes_in_openapi_with_response_models():
    from src.main import app

    spec = app.openapi()
    for path in ("/explore", "/topics/{tag}"):
        op = spec["paths"][path]["get"]
        assert "$ref" in op["responses"]["200"]["content"]["application/json"]["schema"]
    schemas = spec["components"]["schemas"]
    assert {"trends", "new_agents", "topics"} <= set(schemas["ExploreResponse"]["properties"])
    assert {"posts_24h", "authors_7d", "top_agents", "related_tags"} <= set(
        schemas["TopicResponse"]["properties"])


def test_on_the_list_budget_and_explore_cached_for_visitors():
    assert is_list_path("/explore") and is_list_path("/topics/ai")
    assert not is_list_path("/topics/ai/extra")
    assert "/explore" in CACHED_PATHS


def test_routes_use_one_limiter_object():
    import src.main  # noqa: F401  (registers the routes)
    from src.middleware.rate_limits import limiter, limiter_did

    def registered(lim):
        return set(lim._route_limits) | set(lim._dynamic_route_limits)

    names = {f"src.routers.explore.{n}" for n in ("explore", "topic")}
    assert names <= registered(limiter_did)
    assert not names & registered(limiter)
    assert len(limiter_did._dynamic_route_limits["src.routers.explore.explore"]) == 2

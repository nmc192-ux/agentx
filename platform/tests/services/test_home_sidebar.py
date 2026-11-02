"""Layer 1 S2-6: the right-column routes are public, budgeted and cached.
The exclusion rules run on real Postgres in tests/integration/test_home_sidebar_db.py."""
from src.middleware.public_list_limit import is_list_path
from src.middleware.response_cache import CACHED_PATHS
from src.services import home_sidebar

PATHS = ("/feed/trends", "/feed/who-to-follow")


def test_rules_match_the_plan():
    assert home_sidebar.TREND_WINDOW_HOURS == 24
    assert home_sidebar.MIN_ACCOUNT_AGE_HOURS == 24
    assert home_sidebar.MIN_TREND_AUTHORS >= 2


def test_routes_in_openapi_with_a_bounded_limit():
    from src.main import app

    spec = app.openapi()
    for path in PATHS:
        op = spec["paths"][path]["get"]
        limit = next(p for p in op["parameters"] if p["name"] == "limit")
        assert limit["schema"]["maximum"] == 20


def test_routes_are_on_the_list_budget_and_cached_for_visitors():
    for path in PATHS:
        assert is_list_path(path)
        assert path in CACHED_PATHS

"""Guard: every write route needs a login, unless it is on the reviewed list.

Sprint 9 (S9-6d) found five always-on routes that either took no login or
took the acting agent from the request body. This test keeps the next one
out: a new POST / PUT / PATCH / DELETE route with no ``get_current_agent``
in its dependencies fails the suite until someone reviews it and adds it to
``PUBLIC_WRITE_ROUTES`` with the reason.

The suite mounts every router (conftest.py lifts the gate), so gated routers
are checked too. It does not prove a handler *uses* the caller correctly —
that is what the per-router tests are for.
"""
from fastapi.routing import APIRoute, APIWebSocketRoute

from src.auth.middleware import get_current_agent
from src.main import app

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# (method, path) → why it may be called without a login.
PUBLIC_WRITE_ROUTES = {
    # Getting a login in the first place.
    ("POST", "/auth/token"): "issues tokens",
    ("POST", "/auth/refresh"): "issues tokens",
    ("POST", "/onboard"): "open sign-up; rate-limited per IP",
    ("POST", "/agents"): "open sign-up; MEMBER / OBSERVER only without a FOUNDER token",
    ("POST", "/agents/register"): "open registry sign-up; DID is server-generated, no token issued",
    # Reads that happen to use POST.
    ("POST", "/agents/search"): "read-only search",
    ("POST", "/capabilities/route"): "read-only ranking",
    ("POST", "/economy/market-analysis"): "pure calculation on the request body",
    ("POST", "/economy/strategies/select"): "pure calculation on the request body",
    # Login enforced per JSON-RPC method inside the handler.
    ("POST", "/a2a"): "message/send needs a Bearer token; tasks/get is a read",
}

# WebSocket routes carry no Authorization header; each is reviewed by hand.
REVIEWED_WEBSOCKETS = {
    "/ws": "JWT in ?token=, checked before the connection is accepted",
    "/events/stream": "server-to-client only; ignores what the client sends",
}


def _needs_login(route: APIRoute) -> bool:
    stack = [route.dependant]
    while stack:
        dependant = stack.pop()
        if dependant.call is get_current_agent:
            return True
        stack.extend(dependant.dependencies)
    return False


def _write_routes():
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - _READ_METHODS):
                yield method, route.path, route


def test_every_write_route_needs_login_or_is_on_the_reviewed_list():
    unreviewed = [
        f"{method} {path}"
        for method, path, route in _write_routes()
        if not _needs_login(route) and (method, path) not in PUBLIC_WRITE_ROUTES
    ]
    assert unreviewed == [], (
        "Write routes with no login. Add Depends(get_current_agent), or review "
        f"and list them in PUBLIC_WRITE_ROUTES: {unreviewed}"
    )


def test_reviewed_list_has_no_stale_entries():
    public = {
        (method, path) for method, path, route in _write_routes() if not _needs_login(route)
    }
    stale = sorted(set(PUBLIC_WRITE_ROUTES) - public)
    assert stale == [], f"No longer public (or gone); remove from PUBLIC_WRITE_ROUTES: {stale}"


def test_every_websocket_route_is_reviewed():
    sockets = {r.path for r in app.routes if isinstance(r, APIWebSocketRoute)}
    assert sockets == set(REVIEWED_WEBSOCKETS)


def test_the_guard_sees_the_whole_api():
    """If the app stops mounting routers under test, the guard would pass vacuously."""
    paths = {path for _, path, _ in _write_routes()}
    assert len(paths) > 80
    assert {"/posts", "/tasks", "/wallets/transfer", "/services/register"} <= paths

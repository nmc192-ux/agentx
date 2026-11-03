"""Published OpenAPI schema.

A few Phase C routes stay mounted while their flag is off and answer 404
before reading anything. That 404 is the off signal (SDK, MCP, launch
checks). The published schema must not list them in that state, or clients
treat a switched-off route as part of the live API.

The schema is built from the settings object, same as the route. Flipping a
flag is an environment change and needs a process restart; the next
``/openapi.json`` then includes the operation.
"""
from __future__ import annotations

from fastapi import FastAPI

# Method names OpenAPI uses on a path item. Anything else (summary,
# parameters, servers) is not an operation.
_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def hidden_operations() -> set[tuple[str, str]]:
    """``(path, method)`` to drop while that operation's flag is off.

    Method is the lowercase OpenAPI key. Importing the flag helpers here
    (not at module import) avoids a cycle with the app that installs this.
    """
    from .services import economy_stats, faucet_service
    from .services.markets import showcase_service

    hidden: set[tuple[str, str]] = set()
    if not economy_stats.stats_enabled():
        hidden.add(("/stats/economy", "get"))
    if not showcase_service.showcase_enabled():
        hidden.add(("/markets/bounties/showcase", "get"))
    if not faucet_service.faucet_enabled():
        hidden.add(("/wallets/faucet", "post"))
    return hidden


def _omit(schema: dict, hidden: set[tuple[str, str]]) -> None:
    paths = schema.get("paths") or {}
    for path, method in hidden:
        item = paths.get(path)
        if not item:
            continue
        item.pop(method, None)
        if not _METHODS.intersection(item):
            paths.pop(path, None)


def install(app: FastAPI) -> None:
    """Serve a schema that matches the flags. Rebuilt when they change."""
    original = app.openapi

    def openapi() -> dict:
        hidden = hidden_operations()
        key = tuple(sorted(hidden))
        if app.openapi_schema is not None and getattr(app.state, "openapi_hidden_key", None) == key:
            return app.openapi_schema
        app.openapi_schema = None
        schema = original()
        _omit(schema, hidden)
        app.state.openapi_hidden_key = key
        return schema

    app.openapi = openapi  # type: ignore[method-assign]

"""
Tests: EG-1 — every list response is capped at 50 rows (Neon egress).

  - the middleware clamps ``limit`` above 50 to 50 and leaves everything else
    in the query string as it was
  - ``limit`` at or below 50, non-numeric, or absent is passed through
    unchanged, so the router's own 422 still answers bad values
  - the real app has the middleware: a route declared ``le=100`` answers
    ``limit=500`` (it used to 422) and its handler sees 50
  - no route in the app declares a ``limit`` default above 50 (a client that
    sends no ``limit`` would otherwise skip the cap)
"""
import inspect

import pytest
from fastapi import FastAPI, Query
from fastapi.params import Query as QueryParam
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.middleware.list_limit import MAX_LIST_LIMIT, ListLimitMiddleware


def _mini_app() -> FastAPI:
    mini = FastAPI()

    @mini.get("/items")
    async def items(limit: int = Query(default=20, ge=1, le=500), q: str = ""):
        return {"limit": limit, "q": q}

    mini.add_middleware(ListLimitMiddleware, max_limit=MAX_LIST_LIMIT)
    return mini


async def _get(asgi, url: str):
    async with AsyncClient(transport=ASGITransport(app=asgi), base_url="http://t") as c:
        return await c.get(url)


@pytest.mark.parametrize("sent", ["51", "100", "200", "500", "1000000", "1_000"])
async def test_large_limit_is_clamped(sent):
    r = await _get(_mini_app(), f"/items?limit={sent}&q=caf%C3%A9+x")
    assert r.status_code == 200
    assert r.json() == {"limit": 50, "q": "café x"}


@pytest.mark.parametrize("sent,expected", [("1", 1), ("20", 20), ("50", 50)])
async def test_small_limit_untouched(sent, expected):
    r = await _get(_mini_app(), f"/items?limit={sent}")
    assert r.json()["limit"] == expected


async def test_absent_limit_uses_route_default():
    r = await _get(_mini_app(), "/items")
    assert r.json()["limit"] == 20


@pytest.mark.parametrize("sent", ["abc", "0", "-5", ""])
async def test_bad_limit_still_rejected_by_route(sent):
    r = await _get(_mini_app(), f"/items?limit={sent}")
    assert r.status_code == 422


async def test_repeated_limit_all_clamped():
    # FastAPI takes the last value of a repeated scalar param; clamp them all
    # so neither copy can slip past.
    r = await _get(_mini_app(), "/items?limit=10&limit=999")
    assert r.json()["limit"] == 50


async def test_main_app_clamps(monkeypatch):
    # /agents/{did}/followers declares le=100; limit=500 used to be a 422.
    seen = {}

    async def fake_followers(agent_did, request, page=1, limit=20):
        seen["limit"] = limit
        return {"agents": [], "limit": limit}

    from src.routers import follows

    route = next(
        r for r in app.routes
        if isinstance(r, APIRoute) and r.endpoint is follows.list_followers
    )
    monkeypatch.setattr(route.dependant, "call", fake_followers)
    r = await _get(app, "/agents/did:agentx:abc/followers?limit=500")
    assert r.status_code == 200, r.text
    assert seen["limit"] == 50


def test_no_route_defaults_above_cap():
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for name, param in inspect.signature(route.endpoint).parameters.items():
            if name != "limit":
                continue
            default = param.default
            if isinstance(default, QueryParam):
                default = default.default
            if isinstance(default, int) and default > MAX_LIST_LIMIT:
                offenders.append(f"{route.path} limit={default}")
    assert offenders == []

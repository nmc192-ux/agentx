"""
scripts/measure_egress.py (EG-7): the byte-counting proxy and the monthly
arithmetic. No database: the proxy is checked against a local echo server.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "measure_egress.py"
_spec = importlib.util.spec_from_file_location("measure_egress", _PATH)
me = importlib.util.module_from_spec(_spec)
sys.modules["measure_egress"] = me
_spec.loader.exec_module(me)

ZERO_JOBS = {"scheduled_maintenance": 0, "auto_release": 0, "agent_of_week": 0}


def _measured(value: int = 1000) -> dict[str, int]:
    keys = {"heartbeat", "unread_badge", *me.AGENT_DAY, *me.PAGE_VIEW, *me.CACHED_TTL}
    return {k: value for k in keys}


def _lines(**kw):
    args = dict(agents=0, page_views=0, signed_in_hours=0, founder_tick=0, jobs=ZERO_JOBS,
                reconnect=0)
    args.update(kw)
    return {label: (calls, b) for label, calls, b in me.monthly(_measured(), **args)}


def test_proxy_counts_both_directions():
    async def run():
        async def echo(r, w):
            data = await r.read(100)
            w.write(data * 3)          # the "database" answers three times the request
            await w.drain()
            w.close()
        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        counter = me.Counter()
        proxy, port = await me.start_proxy(
            counter, "127.0.0.1", upstream.sockets[0].getsockname()[1])

        async def call():
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"x" * 10)
            await w.drain()
            got = await r.read()
            w.close()
            return got

        n, got = await me.charge(counter, call)
        proxy.close()
        upstream.close()
        return n, got, counter.up
    n, got, up = asyncio.run(run())
    assert got == b"x" * 30
    assert n == 30 and up == 10


def test_founder_tick_and_jobs_follow_their_intervals():
    lines = _lines(founder_tick=10_000,
                   jobs={"scheduled_maintenance": 1, "auto_release": 1, "agent_of_week": 1})
    calls, b = lines["Founder tick (every 5 min, 8 founders)"]
    assert calls == 30 * 288 and b == 30 * 288 * 10_000
    assert lines["Maintenance job (every 15 min)"][0] == 30 * 96
    assert lines["Agent-of-the-week job (hourly)"][0] == 30 * 24


def test_heartbeat_scales_with_agents():
    calls, b = _lines(agents=50)["Heartbeat (50 agents, every 4 h)"]
    assert calls == 50 * 6 * 30 and b == calls * 1000


def test_cached_website_reads_are_capped_by_the_cache_lifetime():
    """However many page views, a cached route misses at most once per
    lifetime per API process."""
    lines = _lines(page_views=10_000_000)
    calls, _ = lines["Website: feed_global (0.5/view)"]
    assert calls == me.API_PROCESSES * me.SECONDS_PER_MONTH / me.CACHED_TTL["feed_global"]
    # Uncached routes (post detail) are not capped.
    assert lines["Website: post_detail (0.2/view)"][0] == pytest.approx(10_000_000 * 0.2 * 30)


def test_website_ceiling_is_every_cached_route_every_lifetime():
    expected = sum(me.API_PROCESSES * me.SECONDS_PER_MONTH / ttl * 1000
                   for ttl in me.CACHED_TTL.values())
    assert me.website_ceiling(_measured()) == int(expected)


def test_render_states_total_against_target():
    result = {
        "routes": {"heartbeat": {"path": "POST /heartbeat", "status": 200, "first": 2048,
                                 "steady": 1024}},
        "founder_tick": 1024, "jobs": ZERO_JOBS, "connect": 400, "reconnect": 1400,
        "tick_quarters": [1000, 1100], "lines": [("x", 10, 1024 ** 3)],
        "total": 1024 ** 3, "website_ceiling": 5 * 1024 ** 3,
        "grid": {f"{a}x{v}": 0 for a in me.SENS_AGENTS for v in me.SENS_VIEWS},
        "params": {"days": 1, "agents": 50, "page_views": 300},
    }
    text = me.render(result)
    assert "**Total, +5 % for TLS: 1.00 GB** against a 2 GB target (50 %)" in text
    assert "5.00 GB" in text

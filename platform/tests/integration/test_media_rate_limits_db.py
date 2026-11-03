"""
Layer 1 S5-2b: every POST /media rate limit applies.

Found in cycle 349: slowapi lets only the outermost limiter object check a
request, so ``@limiter.limit`` (per IP) stacked above ``@limiter_did.limit``
(per agent) left the 10/minute and 30/hour per-agent upload caps unenforced.
The fix puts all three caps on ``limiter_did`` (the IP cap as a key-function
limit). These tests drive the real route with real tokens and real peers:

  - one agent uploading from a fresh IP every time is stopped at its 10th
    upload a minute (per-agent), and another agent is not affected;
  - seven agents sharing one IP are stopped at the IP's 60 an hour (per-ip),
    and the same agent from another IP is not.

Run: cd platform && .venv/bin/python -m pytest tests/integration/test_media_rate_limits_db.py -v --db
"""
import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

pytestmark = pytest.mark.integration   # skipped unless --db is given


@pytest_asyncio.fixture
async def media_root(tmp_path, monkeypatch):
    from src.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "media_enabled", "true")
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    monkeypatch.setattr(settings, "media_min_free_bytes", 0)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)   # the socket peer is the IP
    yield tmp_path


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _auth(who) -> dict:
    """The test harness signs the caller in by header; the real Bearer token is
    what the per-agent limiter keys on (it decodes the JWT, no DB lookup)."""
    from src.auth.jwt import create_access_token
    return {**who.headers, "Authorization": f"Bearer {create_access_token(who.did)}"}


async def _upload_from(ip: str, who, data: bytes):
    from src.main import app
    transport = ASGITransport(app=app, client=(ip, 4000), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        return await c.post("/media", files={"file": ("photo.png", data, "image/png")},
                            headers=_auth(who))


async def test_per_agent_minute_cap_holds_across_fresh_ip_buckets(agents, media_root):
    me = await agents("burst", age_days=30)
    other = await agents("calm", age_days=30)
    png = _png()
    codes = [(await _upload_from(f"203.0.113.{i + 1}", me, png)).status_code for i in range(10)]
    assert codes == [201] * 10, codes
    r = await _upload_from("203.0.113.100", me, png)             # 11th, yet another IP
    assert r.status_code == 429, r.text
    assert r.json()["scope"] == "per-did"
    assert r.headers["X-RateLimit-Scope"] == "per-did"
    assert r.json()["limit"] == "10 per 1 minute"
    # The cap is the agent's, not the network's: another agent is fine.
    r = await _upload_from("203.0.113.101", other, png)
    assert r.status_code == 201, r.text


async def test_per_ip_hour_cap_holds_across_agents(agents, media_root):
    crowd = [await agents(f"ip{i}", age_days=30) for i in range(7)]
    bad = b"\x89"   # not an image: refused before any work, but the limiter still counts it
    for who in crowd[:6]:
        codes = [(await _upload_from("198.51.100.5", who, bad)).status_code for _ in range(10)]
        assert all(c in (415, 422) for c in codes), codes   # per agent: 10 allowed
    r = await _upload_from("198.51.100.5", crowd[6], bad)   # 61st from this IP
    assert r.status_code == 429, r.text
    assert r.json()["scope"] == "per-ip"
    assert r.json()["limit"] == "60 per 1 hour"
    # The same agent from another address is not stopped (it has made no upload).
    r = await _upload_from("198.51.100.6", crowd[6], bad)
    assert r.status_code in (415, 422), r.text
    # The 6 agents that used up the IP are at their own minute cap as well.
    r = await _upload_from("198.51.100.7", crowd[0], bad)
    assert r.status_code == 429 and r.json()["scope"] == "per-did", r.text

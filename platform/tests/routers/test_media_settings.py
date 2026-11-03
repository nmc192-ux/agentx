"""
Tests: GET /media/settings (Layer 1 S4-10a2)

The website asks this public route whether to show its "attach image"
button and which limits to check before uploading. It must follow the two
switches exactly as the upload route and the link-card job read them, carry
the same limits the server enforces, and never be swallowed by
GET /media/{media_id}.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import app
from src.models.post import MAX_POST_MEDIA
from src.routers import media
from src.services import media_images


async def _get():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/media/settings")


async def test_off_by_default_and_needs_no_sign_in(monkeypatch):
    settings = get_settings()
    for name in ("media_enabled", "link_cards_enabled"):
        monkeypatch.setattr(settings, name, type(settings).model_fields[name].default)
    r = await _get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "media_enabled": False,
        "link_cards_enabled": False,
        "max_images": 4,
        "max_bytes": 5 * 1024 * 1024,
        "max_alt_text": 1000,
        "mimes": ["image/gif", "image/jpeg", "image/png", "image/webp"],
    }


async def test_limits_are_the_ones_the_server_enforces():
    body = (await _get()).json()
    assert body["max_images"] == MAX_POST_MEDIA
    assert body["max_bytes"] == media_images.MAX_INPUT_BYTES
    assert body["max_alt_text"] == media.MAX_ALT_TEXT
    assert set(body["mimes"]) == set(media_images.ALLOWED_MIMES)


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("1", True), ("YES", True), (" True ", True),
    ("false", False), ("", False), ("0", False), ("no", False), ("TRUE-ish", False),
])
async def test_switches_follow_the_settings(monkeypatch, value, expected):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_enabled", value)
    monkeypatch.setattr(settings, "link_cards_enabled", "false")
    body = (await _get()).json()
    assert body["media_enabled"] is expected
    assert body["media_enabled"] is media.media_enabled()
    assert body["link_cards_enabled"] is False

    monkeypatch.setattr(settings, "media_enabled", "false")
    monkeypatch.setattr(settings, "link_cards_enabled", value)
    body = (await _get()).json()
    assert body["media_enabled"] is False
    assert body["link_cards_enabled"] is expected


def test_registered_before_the_id_route_and_in_openapi():
    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/media")]
    assert paths.index("/media/settings") < paths.index("/media/{media_id}")
    spec = app.openapi()["paths"]["/media/settings"]
    assert set(spec) == {"get"}
    assert "security" not in spec["get"]

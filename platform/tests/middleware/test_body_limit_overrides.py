"""
Layer 1 S4-3: the body limit's per-path exception for image uploads.

Only ``POST /media`` (exact path) may send more than 64 KiB; every other path
and method, including ``/media/`` and ``/media/x``, keeps the default.
"""
import pytest

from src.main import MAX_BODY_BYTES, app
from src.middleware.body_limit import BodySizeLimitMiddleware
from src.routers.media import MAX_UPLOAD_BODY_BYTES
from src.services.media_images import MAX_INPUT_BYTES



async def _run(mw, method, path, body_len, declared=True):
    status = {"code": None}
    reached = {"app": False}
    body = b"x" * body_len

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status["code"] = msg["status"]

    async def inner(scope, receive_, send_):
        reached["app"] = True
        m = await receive_()
        assert len(m["body"]) == body_len
        await send_({"type": "http.response.start", "status": 200, "headers": []})
        await send_({"type": "http.response.body", "body": b""})

    mw.app = inner
    headers = [(b"content-length", str(body_len).encode())] if declared else []
    await mw({"type": "http", "method": method, "path": path, "headers": headers}, receive, send)
    return status["code"], reached["app"]


def _mw():
    return BodySizeLimitMiddleware(
        None, max_bytes=100, overrides={("POST", "/media"): 1000},
    )


@pytest.mark.parametrize("declared", [True, False])
async def test_override_path_takes_its_own_limit(declared):
    assert await _run(_mw(), "POST", "/media", 1000, declared) == (200, True)
    assert await _run(_mw(), "POST", "/media", 1001, declared) == (413, False)


@pytest.mark.parametrize("method,path", [
    ("POST", "/posts"),
    ("POST", "/media/"),
    ("POST", "/media/abc"),
    ("POST", "/mediax"),
    ("PUT", "/media"),
    ("PATCH", "/media"),
    ("POST", "/MEDIA"),
])
@pytest.mark.parametrize("declared", [True, False])
async def test_every_other_path_keeps_the_default(method, path, declared):
    assert await _run(_mw(), method, path, 100, declared) == (200, True)
    assert await _run(_mw(), method, path, 101, declared) == (413, False)


def test_app_wiring():
    """main.py: 64 KiB everywhere, one image plus framing for POST /media."""
    assert MAX_BODY_BYTES == 65_536
    assert MAX_INPUT_BYTES < MAX_UPLOAD_BODY_BYTES <= MAX_INPUT_BYTES + 64 * 1024
    found = [m for m in app.user_middleware if m.cls is BodySizeLimitMiddleware]
    assert len(found) == 1
    kwargs = found[0].kwargs
    assert kwargs["max_bytes"] == MAX_BODY_BYTES
    assert kwargs["overrides"] == {("POST", "/media"): MAX_UPLOAD_BODY_BYTES}

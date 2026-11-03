"""Images (Layer 1 S4-9): ``client.media`` upload/get/delete, ``media_ids`` on
create/reply/quote/thread, and the same on the async ``AgentClient``."""

import asyncio
import io
import json
from email.parser import BytesParser
from email.policy import HTTP

import httpx
import pytest
import respx

from agentx_sdk import AgentClient, AgentXClient, MediaNamespace
from agentx_sdk.exceptions import AgentXError, NotFoundError, RateLimitError
from agentx_sdk.media import MAX_IMAGE_BYTES
from agentx_sdk.models import Post

BASE = "http://test.agentx.local"
PID = "11111111-1111-1111-1111-111111111111"
MID = "22222222-2222-2222-2222-222222222222"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
UPLOADED = {"media_id": MID, "url": f"/media/{MID}.png", "mime": "image/png", "width": 1,
            "height": 1, "bytes": 72, "alt_text": "a dot", "status": "APPROVED",
            "owner_did": "did:agentx:me", "post_id": None, "created_at": "2026-11-03T00:00:00Z"}


def _sync() -> AgentXClient:
    return AgentXClient(api_key="k", base_url=BASE, max_retries=0)


def _form(request: httpx.Request) -> dict:
    """Parse a multipart request into ``{field: (filename, bytes)}``."""
    ctype = request.headers["content-type"]
    msg = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request.content)
    out = {}
    for part in msg.iter_parts():
        out[part.get_param("name", header="content-disposition")] = (
            part.get_filename(), part.get_payload(decode=True))
    return out


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


class TestUpload:
    @respx.mock
    def test_upload_path_sends_multipart_with_bearer(self, tmp_path):
        path = tmp_path / "dot.png"
        path.write_bytes(PNG)
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        out = _sync().media.upload(path, alt_text="a dot")
        assert out["media_id"] == MID
        req = route.calls.last.request
        assert req.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert req.headers["authorization"] == "Bearer k"
        form = _form(req)
        assert form["file"] == ("dot.png", PNG)
        assert form["alt_text"] == (None, b"a dot")

    @respx.mock
    def test_upload_bytes_and_file_object(self):
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        client = _sync()
        client.media.upload(PNG)
        assert _form(route.calls.last.request)["file"] == ("image", PNG)
        client.media.upload(io.BytesIO(PNG), filename="x.png")
        assert _form(route.calls.last.request)["file"] == ("x.png", PNG)
        assert _form(route.calls.last.request)["alt_text"] == (None, b"")

    @respx.mock
    def test_unicode_alt_text_round_trips(self):
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        _sync().media.upload(PNG, alt_text="Gráfico — 7 días ✓")
        assert _form(route.calls.last.request)["alt_text"][1].decode() == "Gráfico — 7 días ✓"

    @pytest.mark.parametrize("bad, exc", [
        (b"", ValueError),
        (b"x" * (MAX_IMAGE_BYTES + 1), ValueError),
        (io.StringIO("text mode"), TypeError),
        (12345, TypeError),
    ])
    @respx.mock
    def test_refused_before_sending(self, bad, exc):
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        with pytest.raises(exc):
            _sync().media.upload(bad)
        assert not route.called

    @respx.mock
    def test_big_file_and_missing_path_refused_before_sending(self, tmp_path):
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        big = tmp_path / "big.png"
        big.write_bytes(b"x" * (MAX_IMAGE_BYTES + 1))
        with pytest.raises(ValueError, match="5 MB"):
            _sync().media.upload(big)
        with pytest.raises(ValueError, match="not a file"):
            _sync().media.upload(tmp_path / "nope.png")
        with pytest.raises(ValueError, match="not a file"):
            _sync().media.upload(tmp_path)
        with pytest.raises(ValueError, match="alt_text"):
            _sync().media.upload(PNG, alt_text="a" * 1001)
        assert not route.called

    @respx.mock
    def test_exactly_5_mb_is_sent(self):
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        _sync().media.upload(b"x" * MAX_IMAGE_BYTES, alt_text="a" * 1000)
        assert route.called

    @pytest.mark.parametrize("status, exc", [
        (404, NotFoundError), (413, AgentXError), (415, AgentXError), (507, AgentXError),
    ])
    @respx.mock
    def test_server_refusals_raise(self, status, exc):
        respx.post(f"{BASE}/media").mock(return_value=httpx.Response(status, json={"detail": "no"}))
        with pytest.raises(exc):
            _sync().media.upload(PNG)

    @respx.mock
    def test_cap_is_rate_limit(self):
        respx.post(f"{BASE}/media").mock(return_value=httpx.Response(
            429, json={"detail": "50 a day"}, headers={"Retry-After": "60"}))
        with pytest.raises(RateLimitError):
            _sync().media.upload(PNG)

    @respx.mock
    def test_refresh_on_401_keeps_the_multipart_type(self):
        respx.post(f"{BASE}/auth/token").mock(return_value=httpx.Response(
            200, json={"access_token": "k2", "refresh_token": "r2", "expires_in": 3600}))
        route = respx.post(f"{BASE}/media").mock(side_effect=[
            httpx.Response(401, json={"detail": "expired"}),
            httpx.Response(201, json=UPLOADED),
        ])
        client = AgentXClient(api_key="k", refresh_token="r", base_url=BASE, max_retries=0)
        client.media.upload(PNG)
        req = route.calls.last.request
        assert req.headers["authorization"] == "Bearer k2"
        assert req.headers["content-type"].startswith("multipart/form-data")
        assert _form(req)["file"][1] == PNG

    @respx.mock
    def test_get_and_delete(self):
        get = respx.get(f"{BASE}/media/{MID}").mock(return_value=httpx.Response(200, json=UPLOADED))
        delete = respx.delete(f"{BASE}/media/{MID}").mock(return_value=httpx.Response(204))
        assert _sync().media.get(MID)["status"] == "APPROVED"
        assert _sync().media.delete(MID) == {}
        assert get.called and delete.called

    @respx.mock
    def test_ids_are_path_segments(self):
        route = respx.route(url__regex=r".*").mock(return_value=httpx.Response(404))
        for bad in ("../agents/me", "..", "a/b"):
            with pytest.raises(ValueError):
                _sync().media.get(bad)
            with pytest.raises(ValueError):
                _sync().media.delete(bad)
        assert not route.called

    def test_namespace_is_exported(self):
        assert isinstance(_sync().media, MediaNamespace)

    @respx.mock
    def test_json_calls_still_send_json(self):
        route = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        _sync().posts.create("UPDATE", "t", "c", metadata={"progress_percent": 1})
        assert route.calls.last.request.headers["content-type"] == "application/json"


class TestMediaIds:
    @respx.mock
    def test_create_reply_quote_thread_carry_media_ids(self):
        create = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        reply = respx.post(f"{BASE}/posts/{PID}/replies").mock(return_value=httpx.Response(201, json={}))
        thread = respx.post(f"{BASE}/posts/thread").mock(return_value=httpx.Response(201, json={"posts": []}))
        c = _sync()
        c.posts.create("UPDATE", "t", "", media_ids=[MID], metadata={"progress_percent": 1})
        assert _body(create)["media_ids"] == [MID] and _body(create)["content"] == ""
        c.posts.reply(PID, "t", "c", media_ids=[MID])
        assert _body(reply)["media_ids"] == [MID]
        c.posts.quote(PID, "", media_ids=[MID])
        assert _body(create)["media_ids"] == [MID]
        assert _body(create)["quote_post_id"] == PID and _body(create)["title"] == "Quote"
        c.posts.create_thread([{"content": "", "media_ids": [MID]}, "two"])
        assert _body(thread)["items"] == [{"content": "", "media_ids": [MID]}, {"content": "two"}]

    @respx.mock
    def test_no_media_ids_key_when_not_given(self):
        create = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))
        _sync().posts.create("UPDATE", "t", "c")
        assert "media_ids" not in _body(create)
        _sync().posts.quote(PID, "c")
        assert "media_ids" not in _body(create)

    @respx.mock
    def test_five_ids_refused_before_sending(self):
        route = respx.post(url__regex=r".*").mock(return_value=httpx.Response(201, json={}))
        five = [MID] * 5
        with pytest.raises(ValueError, match="at most 4"):
            _sync().posts.create("UPDATE", "t", "c", media_ids=five)
        with pytest.raises(ValueError):
            _sync().posts.reply(PID, "t", "c", media_ids=five)
        with pytest.raises(ValueError):
            _sync().posts.quote(PID, "c", media_ids=five)
        with pytest.raises(ValueError):
            _sync().posts.create_thread([{"content": "a", "media_ids": five}, "b"])
        assert not route.called

    def test_post_model_reads_media_and_link_card(self):
        post = Post.model_validate({
            "post_id": PID, "author_did": "did:x", "post_type": "UPDATE", "title": "t",
            "content": "", "tags": [], "status": "ACTIVE", "created_at": "2026-11-03T00:00:00Z",
            "media": [{"media_id": MID, "status": "PENDING", "url": None, "alt_text": None,
                       "width": 2, "height": 2}],
            "link_card": {"url": "https://example.org/", "title": "Ex", "description": None,
                          "site_name": None, "image": None},
        })
        assert post.media[0]["status"] == "PENDING"
        assert post.link_card["title"] == "Ex"
        old = Post.model_validate({
            "post_id": PID, "author_did": "did:x", "post_type": "UPDATE", "title": "t",
            "content": "c", "tags": [], "status": "ACTIVE", "created_at": "2026-11-03T00:00:00Z"})
        assert old.media == [] and old.link_card is None


class TestAsync:
    def _client(self) -> AgentClient:
        return AgentClient(base_url=BASE, token="tok")

    @respx.mock
    def test_upload_image_and_post_with_it(self):
        up = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(201, json=UPLOADED))
        create = respx.post(f"{BASE}/posts").mock(return_value=httpx.Response(201, json={}))

        async def run():
            async with self._client() as c:
                m = await c.upload_image(PNG, alt_text="a dot", filename="d.png")
                await c.post("look", media_ids=[m["media_id"]])
                await c.quote(PID, "q", media_ids=[m["media_id"]])
        asyncio.run(run())
        req = up.calls.last.request
        assert req.headers["content-type"].startswith("multipart/form-data")
        assert req.headers["authorization"] == "Bearer tok"
        assert _form(req) == {"file": ("d.png", PNG), "alt_text": (None, b"a dot")}
        assert _body(create)["media_ids"] == [MID]

    @respx.mock
    def test_get_delete_and_refusals(self):
        respx.get(f"{BASE}/media/{MID}").mock(return_value=httpx.Response(200, json=UPLOADED))
        respx.delete(f"{BASE}/media/{MID}").mock(return_value=httpx.Response(204))
        route = respx.post(f"{BASE}/media").mock(return_value=httpx.Response(415, json={"detail": "x"}))

        async def run():
            async with self._client() as c:
                assert (await c.get_media(MID))["media_id"] == MID
                assert await c.delete_media(MID) == {}
                with pytest.raises(ValueError):
                    await c.upload_image(b"")
                with pytest.raises(ValueError):
                    await c.post("x", media_ids=[MID] * 5)
                assert not route.called
                with pytest.raises(AgentXError):
                    await c.upload_image(PNG)
        asyncio.run(run())

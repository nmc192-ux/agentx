"""Layer 1 S4-9b: images through MCP — agentx_upload_image and media_ids on
agentx_create_post, agentx_reply, agentx_quote and agentx_post_thread, against
a mocked AgentX API, through a real MCP client.

Fail-closed cases: neither or both sources, a missing path, a folder, an empty
file, over 5 MB, bad base64, alt text over 1000 chars, and any file that is not
a JPEG/PNG/WebP/GIF (e.g. a credentials file or a key the host was talked into
uploading) are refused with no request made.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from mcp import Client

from agentx_mcp.api import AgentXAPI
from agentx_mcp.config import credentials_path
from agentx_mcp.server import INSTRUCTIONS, MAX_IMAGE_BYTES, build_server
from tests.test_write_tools import (
    BASE, DID, NEW_REFRESH, NEW_TOKEN, POST_ID, REFRESH, TOKEN, _call, _joined, _no_secrets, _payload,
    _text,
)

MEDIA_ID = "3e1d2c4b-5a6f-4e7d-8c9b-0a1b2c3d4e5f"
MEDIA_ID_2 = "4f2e3d5c-6b7a-4f8e-9d0c-1b2c3d4e5f60"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x40\x00\x00\x00WEBPVP8 " + b"\x00" * 64
UPLOADED = {"media_id": MEDIA_ID, "url": f"/media/{MEDIA_ID}.png", "status": "APPROVED",
            "width": 1, "height": 1, "alt_text": "A chart", "owner_did": DID, "post_id": None}


@pytest.fixture
def server():
    return build_server(AgentXAPI(BASE))


def _sent(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _parts(request: httpx.Request) -> dict[str, tuple[str | None, bytes]]:
    """The multipart form as {field: (filename, bytes)}, parsed back."""
    ctype = request.headers["content-type"]
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1].encode()
    out = {}
    for chunk in request.content.split(b"--" + boundary)[1:-1]:
        head, _, body = chunk.strip(b"\r\n").partition(b"\r\n\r\n")
        disp = head.split(b"\r\n")[0].decode()
        name = disp.split('name="', 1)[1].split('"', 1)[0]
        filename = disp.split('filename="', 1)[1].split('"', 1)[0] if 'filename="' in disp else None
        out[name] = (filename, body)
    return out


# ── listing ──────────────────────────────────────────────────────────────────

async def test_schemas(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    upload = tools["agentx_upload_image"]
    assert upload.annotations.read_only_hint is False
    assert upload.input_schema["properties"]["alt_text"]["maxLength"] == 1000
    for name in ("agentx_create_post", "agentx_reply", "agentx_quote"):
        schema = str(tools[name].input_schema["properties"]["media_ids"])
        assert "'maxItems': 4" in schema and "^[0-9a-fA-F-]{36}$" in schema
    thread = str(tools["agentx_post_thread"].input_schema["properties"]["media_ids"])
    assert "'maxItems': 4" in thread and "'maxItems': 25" in thread
    assert "agentx_upload_image" in INSTRUCTIONS and "media_ids" in INSTRUCTIONS


# ── upload ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", [PNG, JPEG, GIF, WEBP])
async def test_upload_from_path_sends_multipart(server, tmp_path, data):
    _joined()
    image = tmp_path / "chart.bin"
    image.write_bytes(data)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/media").respond(201, json=UPLOADED)
        result = await _call(server, "agentx_upload_image",
                             {"path": str(image), "alt_text": "Prix du BTC — 7 jours"})
    assert _payload(result) == UPLOADED
    _no_secrets(result)
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    parts = _parts(req)
    assert parts["file"] == ("chart.bin", data)
    assert parts["alt_text"] == (None, "Prix du BTC — 7 jours".encode())


async def test_upload_path_with_tilde(server, tmp_path):
    _joined()
    home = tmp_path / "home"
    home.mkdir()
    (home / "pic.png").write_bytes(PNG)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/media").respond(201, json=UPLOADED)
        result = await _call(server, "agentx_upload_image", {"path": "~/pic.png"})
    assert not result.is_error
    assert _parts(route.calls.last.request)["file"] == ("pic.png", PNG)


@pytest.mark.parametrize("encode", [
    lambda d: base64.b64encode(d).decode(),
    lambda d: "data:image/png;base64," + base64.b64encode(d).decode(),
    lambda d: "\n".join(base64.encodebytes(d).decode().split()),
])
async def test_upload_from_base64(server, encode):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/media").respond(201, json=UPLOADED)
        result = await _call(server, "agentx_upload_image", {"data_base64": encode(PNG)})
    assert not result.is_error
    parts = _parts(route.calls.last.request)
    assert parts["file"] == ("image", PNG) and parts["alt_text"] == (None, b"")


async def test_exactly_5_mb_is_sent(server, tmp_path):
    _joined()
    image = tmp_path / "big.png"
    image.write_bytes(PNG + b"\x00" * (MAX_IMAGE_BYTES - len(PNG)))
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/media").respond(201, json=UPLOADED)
        result = await _call(server, "agentx_upload_image", {"path": str(image)})
    assert not result.is_error
    assert len(_parts(route.calls.last.request)["file"][1]) == MAX_IMAGE_BYTES


def _refusals(tmp_path) -> list[tuple[dict, str]]:
    folder = tmp_path / "folder"
    folder.mkdir()
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    big = tmp_path / "big.png"
    big.write_bytes(PNG + b"\x00" * (MAX_IMAGE_BYTES + 1 - len(PNG)))
    text = tmp_path / "notes.png"
    text.write_text("not an image at all")
    key = tmp_path / "id_ed25519"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nSECRET\n-----END OPENSSH PRIVATE KEY-----\n")
    svg = tmp_path / "x.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    riff = tmp_path / "x.wav"
    riff.write_bytes(b"RIFF\x40\x00\x00\x00WAVEfmt " + b"\x00" * 64)
    return [
        ({}, "exactly one"),
        ({"path": str(empty), "data_base64": base64.b64encode(PNG).decode()}, "exactly one"),
        ({"path": str(tmp_path / "missing.png")}, "Not a file"),
        ({"path": str(folder)}, "Not a file"),
        ({"path": str(empty)}, "empty"),
        ({"path": str(big)}, "5 MB"),
        ({"path": str(text)}, "not a JPEG"),
        ({"path": str(key)}, "not a JPEG"),
        ({"path": str(svg)}, "not a JPEG"),
        ({"path": str(riff)}, "not a JPEG"),
        ({"data_base64": "!!! not base64 !!!"}, "not valid base64"),
        ({"data_base64": ""}, "empty"),
        ({"data_base64": base64.b64encode(b"hello world").decode()}, "not a JPEG"),
        ({"data_base64": "A" * (MAX_IMAGE_BYTES * 2)}, "5 MB"),
        ({"data_base64": base64.b64encode(PNG + b"\x00" * MAX_IMAGE_BYTES).decode()}, "5 MB"),
        ({"path": str(tmp_path / "x.png"), "alt_text": "a" * 1001}, ""),
    ]


async def test_refusals_never_reach_the_api(server, tmp_path):
    _joined()
    for args, message in _refusals(tmp_path):
        with respx.mock(base_url=BASE, assert_all_called=False) as mock:
            route = mock.post("/media")
            result = await _call(server, "agentx_upload_image", args)
        assert result.is_error, args
        assert not route.called, args
        assert message in _text(result), (args, _text(result))
        assert "SECRET" not in _text(result)


async def test_credentials_file_is_never_sent(server):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/media")
        result = await _call(server, "agentx_upload_image", {"path": str(credentials_path())})
    assert result.is_error and not route.called
    _no_secrets(result)


async def test_upload_needs_credentials(server, tmp_path):
    image = tmp_path / "a.png"
    image.write_bytes(PNG)
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/media")
        result = await _call(server, "agentx_upload_image", {"path": str(image)})
    assert result.is_error and not route.called
    assert "agentx_join" in _text(result)


async def test_upload_refreshes_once_and_resends_the_same_multipart(server, tmp_path):
    _joined()
    image = tmp_path / "a.png"
    image.write_bytes(PNG)
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/media").mock(side_effect=[
            httpx.Response(401, json={"detail": "expired"}),
            httpx.Response(201, json=UPLOADED),
        ])
        token = mock.post("/auth/token").respond(json={
            "access_token": NEW_TOKEN, "refresh_token": NEW_REFRESH, "agent_did": DID})
        result = await _call(server, "agentx_upload_image", {"path": str(image), "alt_text": "x"})
    assert not result.is_error
    _no_secrets(result)
    assert token.call_count == 1 and REFRESH in token.calls.last.request.content.decode()
    first, second = (c.request for c in route.calls)
    assert first.headers["authorization"] == f"Bearer {TOKEN}"
    assert second.headers["authorization"] == f"Bearer {NEW_TOKEN}"
    assert _parts(second) == {"file": ("a.png", PNG), "alt_text": (None, b"x")}


@pytest.mark.parametrize("status,detail,expect", [
    (404, "Not Found", "Images are not switched on"),
    (413, "Image too large", "413"),
    (415, {"code": "unsupported_type", "message": "Not an image we accept"}, "Not an image we accept"),
    (429, "Upload limit reached: 50 images per 24 hours.", "50 images"),
    (507, "Image storage is full right now; try again later.", "507"),
])
async def test_server_refusals_are_plain_errors(server, tmp_path, status, detail, expect):
    _joined()
    image = tmp_path / "a.png"
    image.write_bytes(PNG)
    with respx.mock(base_url=BASE) as mock:
        mock.post("/media").respond(status, json={"detail": detail})
        result = await _call(server, "agentx_upload_image", {"path": str(image)})
    assert result.is_error and expect in _text(result)
    _no_secrets(result)


# ── media_ids on posts ───────────────────────────────────────────────────────

async def test_create_post_with_media_ids_and_empty_text(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts").respond(201, json={"post_id": POST_ID})
        result = await _call(server, "agentx_create_post", {
            "title": "Chart", "content": "", "media_ids": [MEDIA_ID, MEDIA_ID_2]})
    assert not result.is_error
    sent = _sent(route)
    assert sent["media_ids"] == [MEDIA_ID, MEDIA_ID_2] and sent["content"] == ""


async def test_no_media_ids_key_when_not_given(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts").respond(201, json={"post_id": POST_ID})
        await _call(server, "agentx_create_post", {"title": "T", "content": "Hello"})
        assert "media_ids" not in _sent(route)
        await _call(server, "agentx_create_post", {"title": "T", "content": "Hello", "media_ids": []})
        assert "media_ids" not in _sent(route)


@pytest.mark.parametrize("tool,args,path", [
    ("agentx_create_post", {"title": "T"}, "/posts"),
    ("agentx_reply", {"post_id": POST_ID}, f"/posts/{POST_ID}/replies"),
    ("agentx_quote", {"post_id": POST_ID}, "/posts"),
])
async def test_empty_text_without_images_refused(server, tool, args, path):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post(path)
        result = await _call(server, tool, {**args, "content": ""})
    assert result.is_error and not route.called
    assert "media_ids" in _text(result)


@pytest.mark.parametrize("tool,args,path", [
    ("agentx_reply", {"post_id": POST_ID}, f"/posts/{POST_ID}/replies"),
    ("agentx_quote", {"post_id": POST_ID}, "/posts"),
])
async def test_reply_and_quote_carry_media_ids(server, tool, args, path):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post(path).respond(201, json={"post_id": POST_ID})
        result = await _call(server, tool, {**args, "content": "See", "media_ids": [MEDIA_ID]})
    assert not result.is_error
    assert _sent(route)["media_ids"] == [MEDIA_ID]


@pytest.mark.parametrize("ids", [
    [MEDIA_ID] * 5,
    ["../../etc/passwd"],
    ["not-a-uuid"],
    [MEDIA_ID + "/x"],
])
@pytest.mark.parametrize("tool,args,path", [
    ("agentx_create_post", {"title": "T"}, "/posts"),
    ("agentx_reply", {"post_id": POST_ID}, f"/posts/{POST_ID}/replies"),
    ("agentx_quote", {"post_id": POST_ID}, "/posts"),
])
async def test_bad_media_ids_never_reach_the_api(server, tool, args, path, ids):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post(path)
        result = await _call(server, tool, {**args, "content": "x", "media_ids": ids})
    assert result.is_error and not route.called


async def test_thread_media_ids_go_on_their_posts(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts/thread").respond(201, json={"posts": []})
        result = await _call(server, "agentx_post_thread", {
            "posts": ["one", "two", "three"], "media_ids": [[MEDIA_ID], [], [MEDIA_ID_2]]})
    assert not result.is_error
    assert _sent(route)["items"] == [
        {"content": "one", "media_ids": [MEDIA_ID]},
        {"content": "two"},
        {"content": "three", "media_ids": [MEDIA_ID_2]},
    ]


async def test_thread_fewer_media_lists_than_posts_is_fine(server):
    _joined()
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/posts/thread").respond(201, json={"posts": []})
        await _call(server, "agentx_post_thread", {"posts": ["one", "two"], "media_ids": [[MEDIA_ID]]})
    assert _sent(route)["items"] == [{"content": "one", "media_ids": [MEDIA_ID]}, {"content": "two"}]


@pytest.mark.parametrize("media", [
    [[MEDIA_ID], [], []],          # more lists than posts
    [[MEDIA_ID] * 5, []],          # 5 on one post
    [["bad"], []],
])
async def test_thread_bad_media_never_reaches_the_api(server, media):
    _joined()
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/posts/thread")
        result = await _call(server, "agentx_post_thread", {"posts": ["one", "two"], "media_ids": media})
    assert result.is_error and not route.called


async def test_post_answer_with_media_and_link_card_passes_through(server):
    _joined()
    answer = {"post_id": POST_ID, "media": [{"id": MEDIA_ID, "status": "PENDING"}],
              "link_card": {"url": "https://example.org/", "title": "Example"}}
    with respx.mock(base_url=BASE) as mock:
        mock.post("/posts").respond(201, json=answer)
        result = await _call(server, "agentx_create_post", {
            "title": "T", "content": "https://example.org/", "media_ids": [MEDIA_ID]})
    assert _payload(result) == answer

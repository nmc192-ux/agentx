"""Layer 1 S4-6: the SSRF-guarded fetcher.

The network tests run a tiny raw HTTP/HTTPS server on 127.0.0.1 and point a
crafted resolver at it. Two things are relaxed *only through the injection
points the module offers for tests*: `ip_allowed` accepts 127.0.0.1 (it plays
the public server), and the allowed-port set gains the server's ephemeral
port (a test cannot bind 80/443). A dedicated test checks each default is
still strict without the relaxation.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import os
import ssl
import time
from ipaddress import IPv4Address, IPv6Address, ip_address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.services import safe_fetch
from src.services.safe_fetch import FetchRefused, Target, check_url, connect_url, fetch, is_public_ip

LOOPBACK = IPv4Address("127.0.0.1")
HOST = "card.example.com"


# ── Local server ─────────────────────────────────────────────────────────────

class Server:
    """Raw HTTP server: `routes[path]` is `(status, headers, body)` or an
    async callable `(writer, request) -> None` for hand-written responses."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.requests: list[dict] = []
        self.sni: list[str | None] = []
        self.port = 0
        self._server = None

    async def start(self, ssl_ctx=None):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0, ssl=ssl_ctx)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()

    def url(self, path="/", scheme="http"):
        return f"{scheme}://{HOST}:{self.port}{path}"

    async def _handle(self, reader, writer):
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
                return
            lines = head.decode("latin-1").split("\r\n")
            method, path, _version = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            req = {"method": method, "path": path, "headers": headers}
            self.requests.append(req)
            route = self.routes.get(path.split("?", 1)[0])
            if route is None:
                await self._write(writer, 404, {"Content-Type": "text/plain"}, b"nope")
            elif callable(route):
                await route(writer, req)
            else:
                status, hdrs, body = route
                await self._write(writer, status, hdrs, body)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _write(writer, status, headers, body, *, content_length=True):
        reason = {200: "OK", 301: "Moved", 302: "Found", 404: "Not Found", 500: "Error"}.get(status, "X")
        out = [f"HTTP/1.1 {status} {reason}\r\n"]
        hdrs = dict(headers)
        if content_length and "Content-Length" not in hdrs:
            hdrs["Content-Length"] = str(len(body))
        hdrs.setdefault("Connection", "close")
        for k, v in hdrs.items():
            out.append(f"{k}: {v}\r\n")
        out.append("\r\n")
        writer.write("".join(out).encode("latin-1") + body)
        await writer.drain()


def html(body=b"<html><title>Hi</title></html>", **extra):
    return (200, {"Content-Type": "text/html; charset=utf-8", **extra}, body)


def redirect(location, status=302):
    return (status, {"Content-Type": "text/html", "Location": location}, b"")


def resolver_for(mapping: dict[str, list], calls: list[str] | None = None):
    async def _resolve(host: str):
        if calls is not None:
            calls.append(host)
        if host not in mapping:
            raise FetchRefused("dns_failed", f"no such host {host}")
        return [ip_address(x) if isinstance(x, str) else x for x in mapping[host]]
    return _resolve


def loopback_only(ip) -> bool:
    """Test policy: 127.0.0.1 plays the public server; nothing else passes."""
    return ip == LOOPBACK


@pytest.fixture
async def server(monkeypatch):
    srv = await Server().start()
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, srv.port}))
    try:
        yield srv
    finally:
        await srv.stop()


def _fetch(server, path="/", kind="html", resolver=None, scheme="http", **kw):
    kw.setdefault("ip_allowed", loopback_only)
    kw.setdefault("resolver", resolver or resolver_for({HOST: ["127.0.0.1"]}))
    kw.setdefault("connect_timeout", 2.0)
    kw.setdefault("read_timeout", 2.0)
    kw.setdefault("total_timeout", 5.0)
    return fetch(server.url(path, scheme), kind, **kw)


async def refused(coro) -> str:
    with pytest.raises(FetchRefused) as info:
        await coro
    return info.value.code


# ── Pure: URL checks ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "", "x" * 3000, "not a url", "//example.com/", "http:///x", "http:",
    "http://example.com/\x00", "http://exam\nple.com/",
])
def test_bad_urls(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code in {"bad_url", "bad_host", "bad_scheme"}


@pytest.mark.parametrize("url", [
    "ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)", "gopher://example.com/",
    "data:text/html,hi", "HTTPS+ssh://example.com/", "ws://example.com/",
])
def test_only_http_and_https(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code == "bad_scheme"


@pytest.mark.parametrize("url", [
    "http://user:pw@example.com/", "http://example.com@evil.com/", "http://user@example.com/",
    "http://example.com\\@evil.com/", "http://:@example.com/",
])
def test_userinfo_refused(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code == "userinfo"


@pytest.mark.parametrize("url", [
    "http://example.com:8080/", "http://example.com:22/", "https://example.com:8443/",
    "http://example.com:0/", "http://example.com:65536/", "http://example.com:abc/",
    "http://1.1.1.1:6379/", "http://[2606:4700::1]:11211/",
])
def test_only_ports_80_and_443(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code == "bad_port"


@pytest.mark.parametrize("url, host, port", [
    ("http://example.com/", "example.com", 80),
    ("http://example.com:80/", "example.com", 80),
    ("https://example.com/", "example.com", 443),
    ("https://example.com:443/", "example.com", 443),
    ("http://example.com:443/", "example.com", 443),
    ("https://example.com:80/", "example.com", 80),
    ("HTTP://EXAMPLE.COM./path?q=1#frag", "example.com", 80),
    ("http://例え.jp/", "xn--r8jz45g.jp", 80),
    ("http://sub.domain.example.co.uk/", "sub.domain.example.co.uk", 80),
    ("http://1.1.1.1/", "1.1.1.1", 80),
    ("http://[2606:4700::1]/", "2606:4700::1", 80),
])
def test_accepted_urls(url, host, port):
    t = check_url(url)
    assert (t.host, t.port) == (host, port)
    assert "#" not in t.url
    assert t.path.startswith("/")


def test_fragment_dropped_and_query_kept():
    t = check_url("http://example.com/a/b?x=1&y=2#top")
    assert t.url == "http://example.com/a/b?x=1&y=2"
    assert t.host_header == "example.com"
    assert check_url("http://example.com:443/").host_header == "example.com:443"


@pytest.mark.parametrize("url", [
    "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://127.1/",
    "http://0x7f.0.0.1/", "http://127.0.0.0x1/", "http://017700000001/", "http://0/",
    "http://1.1.1.1./", "http://localhost1/", "http://example/", "http://-bad.example.com/",
    "http://bad-.example.com/", "http://ex ample.com/", "http://exa_mple.com/",
    "http://example.123/", "http://example.1com/", "http://" + "a" * 64 + ".com/",
    "http://" + ".".join(["a"] * 130) + ".com/", "http://[fe80::1%25eth0]/", "http://[::1", "http://[zz::1]/",
    "http://[1.2.3.4]/", "http://example..com/", "http://.example.com/",
])
def test_non_domain_hosts_refused(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code in {"bad_host", "bad_url"}, url


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://LOCALHOST./", "http://foo.localhost/", "http://db.local/",
    "http://metadata.google.internal/", "http://api.internal/", "http://box.localdomain/",
    "http://router.home.arpa/", "http://abc.onion/", "http://foo.test/", "http://foo.example/",
    "http://foo.invalid/", "http://agentx.social/", "http://api.agentx.social/x",
    "https://API-VPS.AgentX.Social/", "http://deep.sub.agentx.social./",
])
def test_blocked_names_and_own_hosts(url):
    with pytest.raises(FetchRefused) as info:
        check_url(url)
    assert info.value.code == "blocked_host", url


def test_blocked_hosts_parameter_extends_the_default():
    assert check_url("http://pinkpopcorn.example.org/").host == "pinkpopcorn.example.org"
    with pytest.raises(FetchRefused) as info:
        check_url("http://x.pinkpopcorn.example.org/", blocked_hosts=("pinkpopcorn.example.org",))
    assert info.value.code == "blocked_host"
    # Blocking is by whole label, so a lookalike that merely ends with the
    # string is not blocked, and a caller-supplied list is matched the same way.
    assert check_url("http://xagentx.social/", blocked_hosts=("agentx.social",)).host == "xagentx.social"
    # A lookalike that merely ends with the string is not blocked.
    assert check_url("http://notagentx.social/").host == "notagentx.social"


# ── Pure: address policy ─────────────────────────────────────────────────────

PRIVATE_LITERALS = [
    "127.0.0.1", "127.255.255.254", "10.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1",
    "169.254.169.254", "169.254.0.1", "100.64.0.1", "100.127.255.255", "0.0.0.0", "0.1.2.3",
    "192.0.0.1", "192.0.2.1", "192.88.99.1", "198.18.0.1", "198.19.255.255", "198.51.100.1",
    "203.0.113.1", "224.0.0.1", "239.255.255.255", "240.0.0.1", "255.255.255.255",
    "::1", "::", "::ffff:127.0.0.1", "::ffff:7f00:1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "::ffff:1.1.1.1", "::127.0.0.1", "::1.1.1.1", "64:ff9b::7f00:1", "64:ff9b::1.1.1.1",
    "64:ff9b:1::7f00:1", "2002:7f00:1::", "2002:101:101::", "2001:0:7f00:1::1", "2001:0:101:101::1",
    "fe80::1", "fe80::a", "fec0::1", "fc00::1", "fd12:3456::1", "ff02::1", "ff0e::1", "100::1",
    "2001:db8::1", "2001:2::1", "2001:10::1", "3fff::1",
]


@pytest.mark.parametrize("literal", PRIVATE_LITERALS)
def test_private_and_transition_addresses_refused(literal):
    ip = ip_address(literal)
    assert is_public_ip(ip) is False, literal
    bracket = f"[{literal}]" if ":" in literal else literal
    with pytest.raises(FetchRefused) as info:
        check_url(f"http://{bracket}/")
    assert info.value.code == "private_address", literal


@pytest.mark.parametrize("literal", ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:4700::1111", "2001:4860:4860::8888", "2a00:1450::1"])
def test_public_addresses_allowed(literal):
    assert is_public_ip(ip_address(literal)) is True


def test_scoped_ipv6_refused():
    assert is_public_ip(IPv6Address("2606:4700::1%1")) is False


def test_connect_url_uses_the_address_not_the_name():
    t = check_url("https://example.com/p?q=1#x")
    assert connect_url(t, IPv4Address("93.184.216.34")) == "https://93.184.216.34/p?q=1"
    assert connect_url(t, IPv6Address("2606:2800:220:1:248:1893:25c8:1946")) == "https://[2606:2800:220:1:248:1893:25c8:1946]/p?q=1"
    t2 = check_url("http://example.com:443/")
    assert connect_url(t2, IPv4Address("93.184.216.34")) == "http://93.184.216.34:443/"


def test_target_url_for_v6_literal():
    t = check_url("http://[2606:4700::1]:443/a")
    assert t.url == "http://[2606:4700::1]:443/a"
    assert isinstance(t, Target)


# ── Resolution and pinning ───────────────────────────────────────────────────

async def test_name_resolving_to_private_address_refused():
    for bad in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:10.0.0.1", "fd00::1"]:
        code = await refused(fetch("http://evil.example.com/", "html", resolver=resolver_for({"evil.example.com": [bad]})))
        assert code == "private_address", bad


async def test_mixed_answers_refused_before_any_connection():
    code = await refused(fetch("http://evil.example.com/", "html",
                               resolver=resolver_for({"evil.example.com": ["93.184.216.34", "10.0.0.1"]})))
    assert code == "private_address"


async def test_dns_failures_fail_closed():
    code = await refused(fetch("http://nx.example.com/", "html", resolver=resolver_for({})))
    assert code == "dns_failed"

    async def empty(host):
        return []
    assert await refused(fetch("http://nx.example.com/", "html", resolver=empty)) == "dns_failed"

    async def boom(host):
        raise OSError("resolver down")
    assert await refused(fetch("http://nx.example.com/", "html", resolver=boom)) == "read_failed"


async def test_real_resolver_refuses_localhost_style_answers():
    # The OS resolver turns these into loopback; the guard refuses them
    # before that, and `resolve` itself refuses a name with no address.
    with pytest.raises(FetchRefused) as info:
        await safe_fetch.resolve("nonexistent-host-for-agentx-tests.invalid")
    assert info.value.code == "dns_failed"


async def test_default_policy_is_strict_without_test_relaxation(server):
    # Same server, same resolver, but the real address policy: refused.
    code = await refused(fetch(server.url("/"), "html", resolver=resolver_for({HOST: ["127.0.0.1"]})))
    assert code == "private_address"
    assert server.requests == []


async def test_default_ports_are_strict(monkeypatch):
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443}))
    assert await refused(fetch(f"http://{HOST}:8080/", "html", resolver=resolver_for({HOST: ["127.0.0.1"]}), ip_allowed=loopback_only)) == "bad_port"


# ── Network: happy paths ─────────────────────────────────────────────────────

async def test_fetch_html_connects_to_pinned_ip_with_host_header(server):
    server.routes["/page"] = html(b"<title>Hello</title>")
    calls: list[str] = []
    got = await _fetch(server, "/page?x=1", resolver=resolver_for({HOST: ["127.0.0.1"]}, calls))
    assert got.data == b"<title>Hello</title>"
    assert got.content_type == "text/html"
    assert got.truncated is False
    assert got.url == server.url("/page?x=1")
    assert calls == [HOST]  # resolved exactly once
    req = server.requests[0]
    assert req["path"] == "/page?x=1"
    assert req["headers"]["host"] == f"{HOST}:{server.port}"
    assert req["headers"]["user-agent"] == safe_fetch.USER_AGENT
    assert "cookie" not in req["headers"]
    assert "authorization" not in req["headers"]
    assert req["headers"]["accept-encoding"] == "identity"


async def test_fetch_image(server):
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    server.routes["/i.png"] = (200, {"Content-Type": "image/png"}, png)
    got = await _fetch(server, "/i.png", kind="image")
    assert got.data == png and got.content_type == "image/png" and not got.truncated


async def test_env_proxy_and_netrc_ignored(server, monkeypatch, tmp_path):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1/")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1/")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1/")
    netrc = tmp_path / ".netrc"
    netrc.write_text(f"machine {HOST} login u password p\n")
    monkeypatch.setenv("NETRC", str(netrc))
    server.routes["/"] = html()
    got = await _fetch(server, "/")
    assert got.data.startswith(b"<html>")
    assert "authorization" not in server.requests[0]["headers"]
    assert "proxy-authorization" not in server.requests[0]["headers"]


# ── Network: redirects ───────────────────────────────────────────────────────

async def test_three_redirects_followed_each_re_resolved(server):
    server.routes["/a"] = redirect(server.url("/b"), 301)
    server.routes["/b"] = redirect("/c", 302)                      # relative
    server.routes["/c"] = redirect(f"//{HOST}:{server.port}/d", 307)  # scheme-relative
    server.routes["/d"] = html(b"end")
    calls: list[str] = []
    got = await _fetch(server, "/a", resolver=resolver_for({HOST: ["127.0.0.1"]}, calls))
    assert got.data == b"end" and got.url == server.url("/d")
    assert [r["path"] for r in server.requests] == ["/a", "/b", "/c", "/d"]
    assert calls == [HOST] * 4


async def test_fourth_redirect_refused(server):
    for i in range(5):
        server.routes[f"/r{i}"] = redirect(f"/r{i + 1}")
    assert await refused(_fetch(server, "/r0")) == "too_many_redirects"
    assert len(server.requests) == 4


@pytest.mark.parametrize("location, code", [
    ("http://127.0.0.1/", "private_address"),
    ("http://169.254.169.254/latest/meta-data/", "private_address"),
    ("http://[::ffff:127.0.0.1]/", "private_address"),
    ("http://0x7f000001/", "bad_host"),
    ("http://2130706433/", "bad_host"),
    ("http://localhost/", "blocked_host"),
    ("http://api.agentx.social/wallet", "blocked_host"),
    ("file:///etc/passwd", "bad_scheme"),
    ("ftp://example.com/", "bad_scheme"),
    ("http://user:pw@example.com/", "userinfo"),
    ("http://example.com:6379/", "bad_port"),
    ("http://evil.example.com/", "private_address"),   # resolves to 10.0.0.1 below
    ("http://nx.example.com/", "dns_failed"),
    ("http://example.com/\tx", "read_failed"),    # h11 refuses a header with a control character
])
async def test_redirect_targets_rechecked(server, location, code):
    server.routes["/go"] = redirect(location)
    resolver = resolver_for({HOST: ["127.0.0.1"], "evil.example.com": ["10.0.0.1"]})
    assert await refused(_fetch(server, "/go", resolver=resolver)) == code
    assert len(server.requests) == 1  # nothing was fetched after the redirect


async def test_redirect_without_location_refused(server):
    server.routes["/go"] = (302, {"Content-Type": "text/html"}, b"")
    assert await refused(_fetch(server, "/go")) == "bad_redirect"


async def test_cookies_do_not_cross_hops(server):
    server.routes["/a"] = (302, {"Location": "/b", "Set-Cookie": "session=secret; Path=/"}, b"")
    server.routes["/b"] = html(b"ok")
    await _fetch(server, "/a")
    assert "cookie" not in server.requests[1]["headers"]


# ── Network: status, type, size, speed ───────────────────────────────────────

@pytest.mark.parametrize("status", [201, 204, 304, 400, 401, 403, 404, 500, 503])
async def test_non_200_refused(server, status):
    server.routes["/s"] = (status, {"Content-Type": "text/html"}, b"<html>x</html>")
    assert await refused(_fetch(server, "/s")) == "http_status"


@pytest.mark.parametrize("kind, ctype", [
    ("html", "application/json"), ("html", "image/png"), ("html", "text/plain"), ("html", ""),
    ("html", "application/octet-stream"), ("html", "text/html-not"),
    ("image", "text/html"), ("image", "image/svg+xml"), ("image", "application/octet-stream"),
    ("image", "image/x-icon"), ("image", "image/heic"), ("image", ""),
])
async def test_wrong_content_type_refused(server, kind, ctype):
    headers = {"Content-Type": ctype} if ctype else {}
    server.routes["/t"] = (200, headers, b"\x89PNG\r\n\x1a\n" + b"x" * 10)
    assert await refused(_fetch(server, "/t", kind=kind)) == "wrong_type"


async def test_content_type_parameters_and_case_ignored(server):
    server.routes["/t"] = (200, {"Content-Type": "TEXT/HTML ; charset=ISO-8859-1"}, b"<p>x</p>")
    got = await _fetch(server, "/t")
    assert got.content_type == "text/html"


async def test_html_over_cap_is_cut(server):
    body = b"<html>" + b"a" * 5000
    server.routes["/big"] = html(body)
    got = await _fetch(server, "/big", max_bytes=1000)
    assert got.truncated is True and len(got.data) == 1000 and got.data == body[:1000]


async def test_default_cap_applies_when_no_max_bytes_given(server, monkeypatch):
    # Loopback on the engine's Mac moves ~170 KB/s, so the real 1 MiB cap is
    # checked as a constant below and the default path with a small cap here.
    monkeypatch.setitem(safe_fetch._MAX_BYTES, "html", 3000)
    monkeypatch.setitem(safe_fetch._MAX_BYTES, "image", 2000)
    server.routes["/big"] = html(b"b" * 20_000)
    got = await _fetch(server, "/big")
    assert got.truncated is True and len(got.data) == 3000
    server.routes["/img"] = (200, {"Content-Type": "image/webp"}, b"w" * 2001)
    assert await refused(_fetch(server, "/img", kind="image")) == "too_large"
    # max_bytes above the cap is clamped to the cap.
    got = await _fetch(server, "/big", max_bytes=10_000)
    assert len(got.data) == 3000


async def test_html_exactly_at_cap_not_truncated(server):
    server.routes["/eq"] = html(b"c" * 1000)
    got = await _fetch(server, "/eq", max_bytes=1000)
    assert got.truncated is False and len(got.data) == 1000


async def test_max_bytes_cannot_raise_the_cap():
    with pytest.raises(FetchRefused):  # the host is private, but the cap is clamped first
        await fetch("http://127.0.0.1/", "image", max_bytes=10 ** 9)
    with pytest.raises(ValueError):
        await fetch("http://example.com/", "image", max_bytes=0)
    with pytest.raises(ValueError):
        await fetch("http://example.com/", "video")  # type: ignore[arg-type]


async def test_image_over_cap_refused_by_declared_length(server):
    bytes_sent = []

    async def handler(writer, req):
        await Server._write(writer, 200, {"Content-Type": "image/png", "Content-Length": "2000"}, b"")
        bytes_sent.append(0)
        # Hold the connection open briefly; the client should have left.
        await asyncio.sleep(0.2)
    server.routes["/i"] = handler
    assert await refused(_fetch(server, "/i", kind="image", max_bytes=1000)) == "too_large"


async def test_image_over_cap_refused_while_streaming_chunked(server):
    async def handler(writer, req):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
        for _ in range(10):
            chunk = b"x" * 300
            writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()
    server.routes["/i"] = handler
    assert await refused(_fetch(server, "/i", kind="image", max_bytes=1000)) == "too_large"


async def test_image_at_cap_ok(server):
    server.routes["/i"] = (200, {"Content-Type": "image/gif"}, b"G" * 1000)
    got = await _fetch(server, "/i", kind="image", max_bytes=1000)
    assert len(got.data) == 1000 and not got.truncated


async def test_gzip_body_is_decoded_and_capped(server):
    import gzip
    raw = b"<html>" + b"z" * 200_000
    gz = gzip.compress(raw)
    assert len(gz) < 2000
    server.routes["/gz"] = (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, gz)
    got = await _fetch(server, "/gz", max_bytes=5000)
    assert got.truncated is True and len(got.data) == 5000 and got.data == raw[:5000]


async def test_bad_content_length_refused(server):
    server.routes["/cl"] = (200, {"Content-Type": "text/html", "Content-Length": "abc"}, b"<p>")
    code = await refused(_fetch(server, "/cl"))
    assert code == "read_failed"


async def test_slow_headers_time_out(server):
    async def handler(writer, req):
        await asyncio.sleep(3)
    server.routes["/slow"] = handler
    t0 = time.monotonic()
    assert await refused(_fetch(server, "/slow", read_timeout=0.3, total_timeout=5)) == "timeout"
    assert time.monotonic() - t0 < 2


async def test_slow_loris_body_hits_total_deadline(server):
    async def handler(writer, req):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n")
        for _ in range(200):
            writer.write(b"<")
            try:
                await writer.drain()
            except ConnectionError:
                return
            await asyncio.sleep(0.05)
    server.routes["/drip"] = handler
    t0 = time.monotonic()
    assert await refused(_fetch(server, "/drip", read_timeout=2.0, total_timeout=0.8)) == "timeout"
    assert time.monotonic() - t0 < 2.5


async def test_total_deadline_covers_redirect_chains(server):
    async def slowish(writer, req):
        await asyncio.sleep(0.3)
        await Server._write(writer, 302, {"Location": req["path"][:-1] + str(int(req["path"][-1]) + 1)}, b"")
    for i in range(4):
        server.routes[f"/h{i}"] = slowish
    server.routes["/h4"] = html()
    t0 = time.monotonic()
    assert await refused(_fetch(server, "/h0", read_timeout=2.0, total_timeout=0.7)) == "timeout"
    assert time.monotonic() - t0 < 2


async def test_connection_refused(monkeypatch):
    # A closed port on loopback: refused as connect_failed, never raised raw.
    srv = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    srv.close()
    await srv.wait_closed()
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, port}))
    code = await refused(fetch(f"http://{HOST}:{port}/", "html", resolver=resolver_for({HOST: ["127.0.0.1"]}),
                               ip_allowed=loopback_only, connect_timeout=1, total_timeout=3))
    assert code == "connect_failed"


async def test_garbage_response_refused(server):
    async def handler(writer, req):
        writer.write(b"\x00\x01garbage\r\n\r\n")
        await writer.drain()
    server.routes["/g"] = handler
    assert await refused(_fetch(server, "/g")) == "read_failed"


async def test_server_closing_mid_body_refused(server):
    async def handler(writer, req):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 1000\r\n\r\n<html>")
        await writer.drain()
    server.routes["/cut"] = handler
    assert await refused(_fetch(server, "/cut")) == "read_failed"


# ── TLS: certificate verified against the host name, not the address ─────────

def _make_cert(tmp_path, name: str, ca=None):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
    )
    if ca is None:
        builder = builder.issuer_name(subject).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        cert = builder.sign(key, hashes.SHA256())
    else:
        ca_cert, ca_key = ca
        builder = (
            builder.issuer_name(ca_cert.subject)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        )
        cert = builder.sign(ca_key, hashes.SHA256())
    cert_path = tmp_path / f"{name}.crt"
    key_path = tmp_path / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return cert, key, cert_path, key_path


@pytest.fixture
def tls(tmp_path):
    ca_cert, ca_key, ca_path, _ = _make_cert(tmp_path, "AgentX Test CA")
    client_ctx = ssl.create_default_context(cafile=os.fspath(ca_path))

    def server_ctx_for(name: str, sni_log: list):
        _, _, crt, key = _make_cert(tmp_path, name, (ca_cert, ca_key))
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(os.fspath(crt), os.fspath(key))

        def on_sni(sock, server_name, _ctx):
            sni_log.append(server_name)
        ctx.sni_callback = on_sni
        return ctx
    return client_ctx, server_ctx_for


async def test_https_verifies_certificate_for_host_name_via_sni(tls, monkeypatch):
    client_ctx, server_ctx_for = tls
    sni: list = []
    srv = await Server({"/": html(b"secure")}).start(server_ctx_for(HOST, sni))
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, srv.port}))
    try:
        got = await _fetch(srv, "/", scheme="https", verify=client_ctx)
        assert got.data == b"secure"
        assert sni == [HOST]  # the TLS server name is the host, not 127.0.0.1
        assert srv.requests[0]["headers"]["host"] == f"{HOST}:{srv.port}"
    finally:
        await srv.stop()


async def test_https_wrong_certificate_name_refused(tls, monkeypatch):
    client_ctx, server_ctx_for = tls
    srv = await Server({"/": html(b"secure")}).start(server_ctx_for("other.example.com", []))
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, srv.port}))
    try:
        assert await refused(_fetch(srv, "/", scheme="https", verify=client_ctx)) == "tls_failed"
        assert srv.requests == []
    finally:
        await srv.stop()


async def test_https_untrusted_certificate_refused(tls, monkeypatch):
    _client_ctx, server_ctx_for = tls
    srv = await Server({"/": html(b"secure")}).start(server_ctx_for(HOST, []))
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, srv.port}))
    try:
        # The default trust store (verify=True) does not know the test CA.
        assert await refused(_fetch(srv, "/", scheme="https")) == "tls_failed"
    finally:
        await srv.stop()


async def test_plain_http_to_tls_port_refused(tls, monkeypatch):
    _client_ctx, server_ctx_for = tls
    srv = await Server({"/": html()}).start(server_ctx_for(HOST, []))
    monkeypatch.setattr(safe_fetch, "_ALLOWED_PORTS", frozenset({80, 443, srv.port}))
    try:
        code = await refused(_fetch(srv, "/", scheme="http"))
        assert code in {"read_failed", "timeout", "connect_failed"}
    finally:
        await srv.stop()


# ── Constants the next steps rely on ─────────────────────────────────────────

def test_limits_match_the_plan():
    assert safe_fetch.MAX_REDIRECTS == 3
    assert safe_fetch.CONNECT_TIMEOUT == 3.0
    assert safe_fetch.TOTAL_TIMEOUT == 8.0
    assert safe_fetch.MAX_HTML_BYTES == 1024 * 1024
    assert safe_fetch.MAX_IMAGE_BYTES == 5 * 1024 * 1024
    assert safe_fetch.OWN_HOSTS == ("agentx.social",)
    assert safe_fetch.IMAGE_TYPES == {"image/jpeg", "image/png", "image/webp", "image/gif"}
    assert isinstance(ipaddress.ip_address("1.1.1.1"), IPv4Address)

"""
AgentX Platform — SSRF-guarded outbound fetcher (Layer 1, S4-6)
═══════════════════════════════════════════════════════════════
The only code on the platform that fetches a URL an agent typed. Link cards
(S4-7) call it for the page and for the card image. It never runs inside a
request: the link-card job calls it after the post is stored.

What it refuses, in the order it checks (every refusal is a `FetchRefused`
with a stable `code`; nothing is connected to before the checks pass):

  * URLs that are not plain `http://` / `https://` with a host; user-info
    (`user:pw@host`, `host@evil`); any port but 80 / 443; fragments are dropped.
  * Hosts that are not real DNS names: single labels, numeric or hex forms
    (`2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1`), bad labels; the names
    `localhost`, `*.localhost`, `*.local`, `*.internal`, `*.localdomain`,
    `*.home.arpa`, `*.onion`, `*.test`, `*.example`, `*.invalid`; and our own
    hosts (`agentx.social` and every subdomain) so the platform never fetches
    from itself.
  * Addresses (literal, or anything the name resolves to): loopback, private,
    link-local (incl. the cloud metadata address 169.254.169.254), CGNAT
    100.64/10, multicast, reserved, benchmarking, documentation, unspecified,
    broadcast, deprecated site-local, discard, ORCHID, Teredo, and *every*
    IPv6 transition form (IPv4-mapped, IPv4-compatible, NAT64, 6to4), with an
    address refused if it fails any one check. A name is refused if *any*
    address it resolves to is refused.
  * DNS rebinding: the name is resolved once per hop and the TCP connection
    is made to that checked address (the URL given to httpx carries the IP;
    the `Host` header and the TLS server name carry the real host, so the
    certificate is still verified against the host name).
  * More than 3 redirects; a redirect without a usable `Location`; every hop
    goes through all the checks above again.
  * Any status but 200 (after redirects); a `Content-Type` that is not HTML
    (for `kind="html"`) or a JPEG/PNG/WebP/GIF image (for `kind="image"`).
  * Bodies over the cap: HTML is cut at 1 MiB (`truncated=True`); an image
    over 5 MiB is refused (a cut image is useless). The body is streamed, so
    a bigger body is never held in memory. A declared `Content-Length` over
    the cap refuses an image before any byte is read.
  * Slow servers: 3 s to connect, 3 s between bytes, 8 s for the whole fetch
    (DNS, every redirect, the body).

What it never sends: cookies (a fresh client per hop, no jar), `Authorization`
or any header from the environment (`trust_env=False`: no `HTTP_PROXY`, no
`.netrc`), anything but a fixed user agent. HTTP/2 is off.

Pure except for DNS and the connection itself; both are injectable
(`resolver`, `ip_allowed`) so tests can point a name at a local server. The
default policy is the strict one; there is no switch that relaxes it in
production code.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("agentx.safe_fetch")

Kind = Literal["html", "image"]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], Awaitable[list[IPAddress]]]
IPAllowed = Callable[[IPAddress], bool]

USER_AGENT = "AgentXBot/1.0 (+https://agentx.social; link cards)"
MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0
TOTAL_TIMEOUT = 8.0
MAX_HTML_BYTES = 1 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_CHUNK = 64 * 1024

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_ACCEPT = {
    "html": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    "image": "image/jpeg,image/png,image/webp,image/gif;q=0.9,*/*;q=0.1",
}
_MAX_BYTES = {"html": MAX_HTML_BYTES, "image": MAX_IMAGE_BYTES}
_ALLOWED_TYPES = {"html": HTML_TYPES, "image": IMAGE_TYPES}

_ALLOWED_PORTS = frozenset({80, 443})
_DEFAULT_PORT = {"http": 80, "https": 443}

# Our own public hosts: the platform must never be made to fetch from itself.
OWN_HOSTS: tuple[str, ...] = ("agentx.social",)

# Names that only ever mean "inside this machine or this network", plus the
# reserved TLDs that never resolve on the public internet.
_BLOCKED_NAMES = frozenset({"localhost"})
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".localdomain", ".home.arpa",
    ".onion", ".test", ".example", ".invalid",
)

# Address ranges refused on top of `ip.is_global`, which (in Python 3.12)
# still calls some of these global: deprecated site-local fec0::/10, NAT64
# 64:ff9b::/96, IPv4-mapped ::ffff:0:0/96 with a public IPv4 inside.
_DENIED_V4 = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8",          # "this" network
    "10.0.0.0/8",         # private
    "100.64.0.0/10",      # CGNAT shared address space
    "127.0.0.0/8",        # loopback
    "169.254.0.0/16",     # link-local, incl. 169.254.169.254 metadata
    "172.16.0.0/12",      # private
    "192.0.0.0/24",       # IETF protocol assignments
    "192.0.2.0/24",       # documentation
    "192.88.99.0/24",     # deprecated 6to4 relay anycast
    "192.168.0.0/16",     # private
    "198.18.0.0/15",      # benchmarking
    "198.51.100.0/24",    # documentation
    "203.0.113.0/24",     # documentation
    "224.0.0.0/4",        # multicast
    "240.0.0.0/4",        # reserved, incl. 255.255.255.255 broadcast
))
_DENIED_V6 = tuple(ipaddress.ip_network(n) for n in (
    "::/128",             # unspecified
    "::1/128",            # loopback
    "::/96",              # IPv4-compatible (deprecated transition form)
    "::ffff:0:0/96",      # IPv4-mapped
    "64:ff9b::/96",       # NAT64 well-known prefix
    "64:ff9b:1::/48",     # NAT64 local-use
    "100::/64",           # discard-only
    "2001::/32",          # Teredo
    "2001:2::/48",        # benchmarking
    "2001:10::/28",       # ORCHID
    "2001:db8::/32",      # documentation
    "2002::/16",          # 6to4
    "3fff::/20",          # documentation (RFC 9637)
    "fc00::/7",           # unique local
    "fe80::/10",          # link-local
    "fec0::/10",          # deprecated site-local
    "ff00::/8",           # multicast
))


class FetchRefused(Exception):
    """The fetch was not done (or not completed). `code` is stable."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class Target:
    """A checked URL, ready to resolve. `host` is lowercase ASCII (IDNA)."""
    scheme: str
    host: str
    port: int
    path: str
    query: str
    ip: IPAddress | None  # set when the host is an address literal

    @property
    def url(self) -> str:
        """The URL as the outside world would write it (no fragment)."""
        return urlunsplit((self.scheme, self.host_header, self.path, self.query, ""))

    @property
    def host_header(self) -> str:
        host = f"[{self.host}]" if self.ip is not None and self.ip.version == 6 else self.host
        if self.port != _DEFAULT_PORT[self.scheme]:
            return f"{host}:{self.port}"
        return host


@dataclass(frozen=True)
class Fetched:
    url: str            # the URL that answered 200 (after redirects)
    content_type: str   # media type only, lowercase, no parameters
    data: bytes
    truncated: bool     # HTML cut at the cap; never True for an image


# ── Pure checks ──────────────────────────────────────────────────────────────

def is_public_ip(ip: IPAddress) -> bool:
    """True only for an address on the public internet, in its plain form.

    Every IPv6 transition form (mapped, compatible, NAT64, 6to4, Teredo) is
    refused outright: a real link never uses one, and each can smuggle a
    private IPv4 address past a check that looks only at the IPv6 ranges.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id:
            return False
        if ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None:
            return False
        if any(ip in net for net in _DENIED_V6):
            return False
    else:
        if any(ip in net for net in _DENIED_V4):
            return False
    return bool(ip.is_global)


def check_ip(ip: IPAddress, ip_allowed: IPAllowed = is_public_ip) -> None:
    if not ip_allowed(ip):
        raise FetchRefused("private_address", f"address {ip} is not public")


def _parse_ip_literal(hostname: str, bracketed: bool) -> IPAddress | None:
    """The address if *hostname* is an address literal, else None.

    Only a dotted quad (`1.2.3.4`) or a bracketed IPv6 literal counts.
    Shorthand and numeric spellings (`127.1`, `2130706433`, `0x7f000001`,
    `0177.0.0.1`) are refused by the host-name rules instead of being
    resolved, because the OS resolver would turn them into addresses.
    """
    if bracketed:
        if "%" in hostname:
            raise FetchRefused("bad_host", "IPv6 zone identifiers are not allowed")
        try:
            return ipaddress.IPv6Address(hostname)
        except ValueError:
            raise FetchRefused("bad_host", "malformed IPv6 literal") from None
    try:
        return ipaddress.IPv4Address(hostname)
    except ValueError:
        return None


def _check_hostname(hostname: str, blocked_hosts: tuple[str, ...]) -> str:
    """Return the ASCII (IDNA) lowercase host, or refuse."""
    if not hostname:
        raise FetchRefused("bad_host", "URL has no host")
    host = hostname.rstrip(".").lower()
    if not host or len(host) > 253:
        raise FetchRefused("bad_host", "host name is empty or too long")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise FetchRefused("bad_host", "host name is not a valid IDNA name") from None
    if host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise FetchRefused("blocked_host", "host is a local or reserved name")
    labels = host.split(".")
    if len(labels) < 2:
        raise FetchRefused("bad_host", "host must be a public domain name")
    for label in labels:
        if not label or len(label) > 63:
            raise FetchRefused("bad_host", "bad host label")
        if label[0] == "-" or label[-1] == "-":
            raise FetchRefused("bad_host", "bad host label")
        if any(not (c.isascii() and (c.isalnum() or c == "-")) for c in label):
            raise FetchRefused("bad_host", "bad host label")
    # A TLD never starts with a digit; this refuses every numeric/hex/octal
    # spelling of an address (`127.1`, `0x7f.1`, `2130706433`, `0177.0.0.1`).
    if not labels[-1][0].isalpha():
        raise FetchRefused("bad_host", "host must be a public domain name")
    for own in blocked_hosts:
        own = own.lower().strip(".")
        if own and (host == own or host.endswith("." + own)):
            raise FetchRefused("blocked_host", "host is one of our own")
    return host


def check_url(url: str, blocked_hosts: tuple[str, ...] = OWN_HOSTS) -> Target:
    """Parse and check a URL without touching the network."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise FetchRefused("bad_url", "URL is empty or too long")
    if any(ord(c) < 0x20 or c == "\x7f" for c in url):
        raise FetchRefused("bad_url", "URL contains control characters")
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        raise FetchRefused("bad_url", "URL cannot be parsed") from None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT:
        raise FetchRefused("bad_scheme", "only http and https are fetched")
    netloc = parts.netloc
    if not netloc:
        raise FetchRefused("bad_host", "URL has no host")
    if "@" in netloc or "\\" in netloc or parts.username is not None or parts.password is not None:
        raise FetchRefused("userinfo", "URLs with user info are not fetched")
    try:
        port = parts.port
    except ValueError:
        raise FetchRefused("bad_port", "malformed port") from None
    if port is None:
        port = _DEFAULT_PORT[scheme]
    elif port not in _ALLOWED_PORTS:
        raise FetchRefused("bad_port", "only ports 80 and 443 are fetched")
    hostname = parts.hostname or ""
    bracketed = netloc.startswith("[")
    ip = _parse_ip_literal(hostname, bracketed)
    if ip is not None:
        check_ip(ip)
        host = str(ip)
    else:
        host = _check_hostname(hostname, blocked_hosts)
    path = parts.path or "/"
    if not path.startswith("/"):
        raise FetchRefused("bad_url", "URL path must be absolute")
    return Target(scheme=scheme, host=host, port=port, path=path, query=parts.query, ip=ip)


# ── Network ──────────────────────────────────────────────────────────────────

async def resolve(host: str) -> list[IPAddress]:
    """Every address *host* resolves to, in resolver order, without duplicates."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError, UnicodeError) as exc:
        raise FetchRefused("dns_failed", f"could not resolve {host}: {exc}") from None
    out: list[IPAddress] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise FetchRefused("dns_failed", "resolver returned a non-address") from None
        if ip not in out:
            out.append(ip)
    if not out:
        raise FetchRefused("dns_failed", f"{host} has no address")
    return out


async def pin(target: Target, resolver: Resolver, ip_allowed: IPAllowed) -> IPAddress:
    """Resolve once, check every answer, and return the address to connect to."""
    if target.ip is not None:
        check_ip(target.ip, ip_allowed)
        return target.ip
    ips = await resolver(target.host)
    if not ips:
        raise FetchRefused("dns_failed", f"{target.host} has no address")
    for ip in ips:
        if isinstance(ip, ipaddress.IPv6Address) and ip.scope_id:
            raise FetchRefused("private_address", "scoped address")
        check_ip(ip, ip_allowed)
    return ips[0]


def connect_url(target: Target, ip: IPAddress) -> str:
    """The URL handed to httpx: the checked address, never the name."""
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    if target.port != _DEFAULT_PORT[target.scheme]:
        host = f"{host}:{target.port}"
    return urlunsplit((target.scheme, host, target.path, target.query, ""))


def _host_for_log(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "?")[:253]
    except ValueError:
        return "?"


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _classify(exc: Exception) -> FetchRefused:
    if isinstance(exc, FetchRefused):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return FetchRefused("timeout", "the server was too slow")
    if isinstance(exc, httpx.ConnectError):
        text = str(exc).lower()
        if "ssl" in text or "certificate" in text or "tls" in text:
            return FetchRefused("tls_failed", "TLS handshake or certificate check failed")
        return FetchRefused("connect_failed", "could not connect")
    if isinstance(exc, (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError, OSError)):
        return FetchRefused("read_failed", "the response could not be read")
    raise exc


async def _one_hop(
    target: Target,
    ip: IPAddress,
    kind: Kind,
    max_bytes: int,
    *,
    connect_timeout: float,
    read_timeout: float,
    verify,
) -> Fetched | str:
    """GET one URL. Returns a `Fetched`, or the redirect `Location` string."""
    headers = {
        "Host": target.host_header,
        "User-Agent": USER_AGENT,
        "Accept": _ACCEPT[kind],
        "Accept-Encoding": "identity",
        "Accept-Language": "en",
    }
    extensions = {}
    if target.scheme == "https" and target.ip is None:
        extensions["sni_hostname"] = target.host
    timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
    # One client per hop: no cookie jar carries anything between hops, and
    # trust_env=False keeps HTTP(S)_PROXY, NO_PROXY and .netrc out of it.
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        verify=verify,
        http2=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        max_redirects=0,
    ) as client:
        request = client.build_request("GET", connect_url(target, ip), headers=headers, extensions=extensions)
        response = await client.send(request, stream=True)
        try:
            status = response.status_code
            if status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise FetchRefused("bad_redirect", "redirect without a Location")
                return location
            if status != 200:
                raise FetchRefused("http_status", f"server answered {status}")
            media_type = _media_type(response.headers.get("content-type", ""))
            if media_type not in _ALLOWED_TYPES[kind]:
                raise FetchRefused("wrong_type", f"unexpected content type {media_type or '(none)'}")
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    declared_n = int(declared)
                except ValueError:
                    raise FetchRefused("read_failed", "bad Content-Length") from None
                if declared_n > max_bytes and kind == "image":
                    raise FetchRefused("too_large", "image is over the size cap")
            chunks: list[bytes] = []
            size = 0
            truncated = False
            async for chunk in response.aiter_bytes(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    if kind == "image":
                        raise FetchRefused("too_large", "image is over the size cap")
                    chunks.append(chunk[: max(0, len(chunk) - (size - max_bytes))])
                    truncated = True
                    break
                chunks.append(chunk)
            return Fetched(url=target.url, content_type=media_type, data=b"".join(chunks), truncated=truncated)
        finally:
            await response.aclose()


async def fetch(
    url: str,
    kind: Kind,
    *,
    max_bytes: int | None = None,
    blocked_hosts: tuple[str, ...] = OWN_HOSTS,
    resolver: Resolver = resolve,
    ip_allowed: IPAllowed = is_public_ip,
    connect_timeout: float = CONNECT_TIMEOUT,
    read_timeout: float = READ_TIMEOUT,
    total_timeout: float = TOTAL_TIMEOUT,
    verify=True,
) -> Fetched:
    """Fetch *url* under the guard. Raises `FetchRefused` for anything but a
    clean 200 of the expected kind; never raises anything else for a network
    or server problem."""
    if kind not in _MAX_BYTES:
        raise ValueError(f"unknown kind {kind!r}")
    cap = _MAX_BYTES[kind] if max_bytes is None else min(int(max_bytes), _MAX_BYTES[kind])
    if cap <= 0:
        raise ValueError("max_bytes must be positive")
    current = url
    try:
        async with asyncio.timeout(total_timeout):
            for hop in range(MAX_REDIRECTS + 1):
                target = check_url(current, blocked_hosts)
                ip = await pin(target, resolver, ip_allowed)
                result = await _one_hop(
                    target, ip, kind, cap,
                    connect_timeout=connect_timeout, read_timeout=read_timeout, verify=verify,
                )
                if isinstance(result, Fetched):
                    return result
                if hop == MAX_REDIRECTS:
                    raise FetchRefused("too_many_redirects", "more than 3 redirects")
                if any(ord(c) < 0x20 or c == "\x7f" for c in result):
                    raise FetchRefused("bad_redirect", "Location contains control characters")
                current = urljoin(target.url, result.strip())
                logger.debug("safe_fetch redirect %s -> %s", target.url, current)
    except Exception as exc:  # noqa: BLE001 — classified below; unknown ones re-raise
        refused = _classify(exc)
        # Only the host goes to the log: a query string can carry tokens.
        logger.info("safe_fetch refused host=%s: %s (%s)", _host_for_log(url), refused.code, refused.message)
        raise refused from None
    raise FetchRefused("too_many_redirects", "more than 3 redirects")  # pragma: no cover

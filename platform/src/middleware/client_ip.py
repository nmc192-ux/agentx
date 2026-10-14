"""
AgentX Platform — Who is calling?
══════════════════════════════════
One answer to "which address is this request from?", used by every per-IP
rate limit (RL-1, T1 fix of a hole found in cycle 172).

Why this exists. On Fly the app runs ``uvicorn`` without ``--proxy-headers``,
so ``request.client`` is Fly's proxy for every caller and every per-IP budget
(sign-up 5/hour and 20/day on ``/onboard`` and ``POST /agents``, the economy
calculators, ``/health``) was one global budget: five sign-ups an hour from
anyone stopped sign-ups for everyone. On the VPS stack uvicorn runs with
``--proxy-headers`` trusting only Caddy, so ``request.client`` is already the
real caller there.

Rules (fail closed: when in doubt, fall back to the shared peer address,
which is the old behaviour, never to something the caller chose):

  - ``Fly-Client-IP`` is believed only when ``FLY_APP_NAME`` is set. Fly sets
    that variable on every machine it runs, and Fly's proxy overwrites the
    header on every request it forwards, so a caller cannot choose it. Off Fly
    the header is ignored, so a spoofed header on the VPS or locally does
    nothing.
  - The header must parse as one IP address (no lists, no ports, no more than
    64 characters), otherwise the peer address is used.
  - Rate-limit keys bucket IPv6 by its /64 (one subscriber's usual allocation);
    an IPv6 caller could otherwise rotate through 2**64 addresses and the
    sign-up limit would mean nothing. IPv4-mapped IPv6 addresses count as the
    IPv4 address. ``client_address`` (for logs) keeps the exact address.
"""
from __future__ import annotations

import ipaddress
import os

FLY_HEADER = "fly-client-ip"
_MAX_HEADER_LEN = 64


def on_fly() -> bool:
    return bool(os.getenv("FLY_APP_NAME"))


def _parse_ip(value: str | None):
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > _MAX_HEADER_LEN:
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if getattr(ip, "scope_id", None):     # "fe80::1%eth0": not a routable caller
        return None
    return ip


def resolve_address(peer: str | None, fly_client_ip: str | None) -> str:
    """The caller's address given the socket peer and the raw ``Fly-Client-IP`` header."""
    if on_fly():
        ip = _parse_ip(fly_client_ip)
        if ip is not None:
            return str(ip)
    return peer or "unknown"


def bucket(address: str) -> str:
    """Rate-limit key for an address: IPv4 as is, IPv6 by its /64."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 6:
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return str(mapped)
        return str(ipaddress.ip_network((int(ip), 64), strict=False))
    return str(ip)


# ── ASGI scope ────────────────────────────────────────────────────────────────

def _scope_header(scope, name: str) -> str | None:
    wanted = name.encode("latin-1")
    for k, v in scope.get("headers", ()) or ():
        if k.lower() == wanted:
            return v.decode("latin-1")
    return None


def client_address(scope) -> str:
    client = scope.get("client")
    peer = client[0] if client else None
    return resolve_address(peer, _scope_header(scope, FLY_HEADER))


def client_bucket(scope) -> str:
    return bucket(client_address(scope))


# ── Starlette Request ─────────────────────────────────────────────────────────

def request_address(request) -> str:
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None) if client else None
    return resolve_address(peer, request.headers.get(FLY_HEADER))


def request_bucket(request) -> str:
    return bucket(request_address(request))

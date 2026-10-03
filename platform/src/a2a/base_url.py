"""AgentX Platform — the public base URL the discovery documents print.

``/.well-known/skill.md`` and the Agent Cards tell outside agents which URL to
call. Sprint 9 (S9-13a): the Agent Card used ``PLATFORM_BASE_URL`` with a
``http://localhost:8000`` default (not set in production, so the live card
pointed at localhost) and skill.md took the scheme as the app saw it — plain
``http`` behind the TLS-terminating proxy, so every ``curl`` in it would have
been redirected.
"""
from __future__ import annotations

import os
import re

from fastapi import HTTPException, Request, status

from ..config import get_settings

# host, host:port or [ipv6]:port — nothing that could break out of a URL.
_HOST_RE = re.compile(r"[A-Za-z0-9.\-]+(:\d{1,5})?|\[[0-9A-Fa-f:.]+\](:\d{1,5})?")


def public_base_url(request: Request) -> str:
    """Return the base URL (no trailing slash) to print in discovery documents.

    A configured value wins (``PLATFORM_BASE_URL``, then ``AGENTX_BASE_URL``).
    Otherwise it is the URL the caller used, so the document works on every
    environment; outside development the scheme is always ``https`` (staging
    and production sit behind a proxy that terminates TLS and redirects http).
    """
    configured = os.environ.get("PLATFORM_BASE_URL") or os.environ.get("AGENTX_BASE_URL")
    if configured:
        return configured.rstrip("/")

    # The raw header, not request.base_url: Starlette pastes the header into a
    # URL and parses it, so "host/extra" would come back as a path.
    host = request.headers.get("host") or request.base_url.netloc
    if not _HOST_RE.fullmatch(host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Host header",
        )
    scheme = request.url.scheme
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto == "https" or not get_settings().is_development:
        scheme = "https"
    root_path = request.scope.get("root_path", "")
    return f"{scheme}://{host}{root_path}".rstrip("/")

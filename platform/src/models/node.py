"""
AgentX Platform — Federated Node Models
════════════════════════════════════════
Phase 17: Pydantic schemas for federated node management.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Hostnames that only resolve inside our own network. This node POSTs event
# payloads to every registered peer URL, so a peer URL must never point inward.
_INTERNAL_HOSTS = {"localhost"}
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal")


def validate_peer_url(url: str) -> str:
    """Return *url* if it is a public https URL, else raise ValueError.

    SSRF guard for federation: rejects non-https schemes, embedded credentials,
    internal hostnames and literal loopback / private / link-local / reserved
    addresses. Hostnames are not resolved here (a public name can still point
    at a private address), which is why registration is also FOUNDER-only.
    """
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise ValueError(f"node_url is not a valid URL: {exc}") from exc
    if parts.scheme != "https":
        raise ValueError("node_url must be an https:// URL")
    if not host:
        raise ValueError("node_url must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("node_url must not contain credentials")
    if host in _INTERNAL_HOSTS or host.endswith(_INTERNAL_SUFFIXES):
        raise ValueError("node_url must not point at an internal host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A hostname, not a literal address. Require a real domain name: bare
        # labels and numeric forms like "2130706433" or "127.1" are alternate
        # spellings of an IP address to the resolver.
        tld = host.rsplit(".", 1)[-1]
        if "." not in host or not tld[:1].isalpha():
            raise ValueError("node_url host must be a public domain name")
        return url.strip()
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        raise ValueError("node_url must not point at a private or reserved address")
    return url.strip()


class RegisterNodeRequest(BaseModel):
    """Body for POST /nodes/register."""
    node_url: str = Field(..., min_length=1, max_length=500, description="Public https URL of the peer node")
    node_name: str | None = Field(default=None, max_length=100, description="Human-readable name")
    public_key: str | None = Field(default=None, max_length=2000, description="Node public key (PEM / JWK)")

    @field_validator("node_url")
    @classmethod
    def _public_https_url(cls, v: str) -> str:
        return validate_peer_url(v)


class NodeResponse(BaseModel):
    """Response model for a single registered node."""
    node_id: UUID
    node_url: str
    node_name: str | None = None
    public_key: str | None = None
    status: str = "active"
    trust_level: float = 0.5
    registered_at: datetime
    last_seen_at: datetime | None = None


class NodeMessageResponse(BaseModel):
    """Response model for a logged federated message."""
    message_id: UUID
    node_id: UUID | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    direction: str = "inbound"
    created_at: datetime


class FederatedEventRequest(BaseModel):
    """Body for POST /nodes/events — inbound event from a peer node."""
    event_type: str = Field(..., min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    source_node_url: str | None = Field(default=None, max_length=500)

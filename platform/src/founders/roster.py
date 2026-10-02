"""
AgentX Platform — Founder roster and the fail-closed actor guard (S10-1)
═══════════════════════════════════════════════════════════════════════════
The heartbeat job writes posts, replies, messages and paid tasks AS a
founder without any login. The only thing standing between that job and an
arbitrary agent's account is this module, so every rule here refuses by
default and `resolve_founder` is the single door the job may use.

A founder may be acted for only when ALL of these hold:
  1. the name is one of the eight personas (`founders.personas`);
  2. the roster (`FOUNDER_DIDS`, see `config.Settings.founder_dids`) names a
     DID for it — in development an unlisted founder defaults to
     ``did:agentx:<name>-001``; in staging and production it must be listed;
  3. that DID matches ``did:agentx:<name>-(seed-)?NNN`` for the SAME name
     (an outsider's ``did:agentx:nova-002`` would pass the global DID
     pattern, so the roster is re-checked here, not only when parsed);
  4. the agent row exists, is ACTIVE, and its display name is the founder's
     name (the same identity rule `scripts/dedupe_founders.py` applies).

Anything else raises `FounderRefused` with a machine-readable `reason`.

A malformed `FOUNDER_DIDS` raises `RosterConfigError` from `founder_roster`
and therefore from every `resolve_founder` call: a typo disables the whole
heartbeat rather than part of it, and the API process is unaffected
(the value is a plain string that is parsed only here).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

from ..config import get_settings
from .personas import PERSONAS, Persona

__all__ = [
    "FounderAgent", "FounderRefused", "RosterConfigError",
    "default_did", "founder_did_pattern", "parse_founder_dids", "founder_roster",
    "name_for_did", "resolve_founder",
]

_DID_SUFFIX = r"-(?:seed-)?[0-9]{3}"
_ROSTER_ENTRY = re.compile(r"^\s*([a-z]+)\s*=\s*(\S+)\s*$")

# What the global DID rule accepts (agents.agent_did CHECK + models/agent.py).
_ANY_DID = re.compile(r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")


class RosterConfigError(ValueError):
    """`FOUNDER_DIDS` cannot be trusted: nothing in it is used."""


class FounderRefused(PermissionError):
    """The heartbeat may not act for this founder. `reason` is one of:
    unknown_founder, not_in_roster, did_mismatch, not_found, not_active,
    name_mismatch."""

    def __init__(self, name: str, reason: str, detail: str = ""):
        self.name, self.reason, self.detail = name, reason, detail
        super().__init__(f"founder {name!r} refused ({reason}){': ' + detail if detail else ''}")


@dataclass(frozen=True)
class FounderAgent:
    """An agent row the heartbeat has been cleared to act as."""
    name: str
    did: str
    agent_id: object          # UUID (asyncpg returns uuid.UUID)
    display_name: str
    persona: Persona


# ── The roster ────────────────────────────────────────────────────────────────

def default_did(name: str) -> str:
    """The DID every seed and runner uses for a founder (test_founder_dids_agree)."""
    return f"did:agentx:{name}-001"


def founder_did_pattern(name: str) -> re.Pattern[str]:
    """DIDs that may belong to founder *name*: did:agentx:<name>-(seed-)?NNN."""
    return re.compile(rf"^did:agentx:{re.escape(name)}{_DID_SUFFIX}$")


def parse_founder_dids(raw: str) -> dict[str, str]:
    """
    Parse ``name=did,name=did`` (commas or newlines between entries, spaces
    tolerated) into {name: did}. Every entry must name a persona and give a
    DID of that founder's own pattern; a name may appear once. Any bad entry
    rejects the whole value.
    """
    roster: dict[str, str] = {}
    for piece in re.split(r"[,\n]", raw or ""):
        if not piece.strip():
            continue
        m = _ROSTER_ENTRY.match(piece)
        if not m:
            raise RosterConfigError(f"FOUNDER_DIDS entry {piece.strip()!r} is not name=did")
        name, did = m.group(1), m.group(2)
        if name not in PERSONAS:
            raise RosterConfigError(f"FOUNDER_DIDS names {name!r}, which is not a founder")
        if name in roster:
            raise RosterConfigError(f"FOUNDER_DIDS lists {name!r} twice")
        if not founder_did_pattern(name).match(did):
            raise RosterConfigError(
                f"FOUNDER_DIDS gives {name!r} the address {did!r}; "
                f"it must look like did:agentx:{name}-001 or did:agentx:{name}-seed-001"
            )
        roster[name] = did
    return roster


def founder_roster(raw: Optional[str] = None, app_env: Optional[str] = None) -> dict[str, str]:
    """
    {name: did} for every founder the heartbeat may act for. From the
    settings unless *raw* / *app_env* are given (tests). In development an
    unlisted founder gets `default_did`; elsewhere it is simply absent.
    """
    if raw is None or app_env is None:
        settings = get_settings()
        raw = settings.founder_dids if raw is None else raw
        app_env = settings.app_env if app_env is None else app_env
    roster = parse_founder_dids(raw)
    if app_env == "development":
        for name in PERSONAS:
            roster.setdefault(name, default_did(name))
    return roster


def name_for_did(did: str, roster: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The founder name a DID belongs to in the roster, else None (an outsider)."""
    roster = founder_roster() if roster is None else roster
    for name, founder_did in roster.items():
        if founder_did == did:
            return name
    return None


# ── The guard ─────────────────────────────────────────────────────────────────

async def resolve_founder(
    conn, name: str, roster: Optional[Mapping[str, str]] = None,
) -> FounderAgent:
    """
    The agent row founder *name* may act as, or `FounderRefused`.

    *conn* is an asyncpg connection (no RLS context needed: the agents table
    is readable). *roster* overrides the settings-derived roster (tests;
    it is still re-validated here, so a hand-built roster cannot widen it).
    """
    persona = PERSONAS.get(name)
    if persona is None:
        raise FounderRefused(name, "unknown_founder")

    roster = founder_roster() if roster is None else roster
    did = roster.get(name)
    if not did:
        raise FounderRefused(name, "not_in_roster", "FOUNDER_DIDS does not list this founder")
    if not _ANY_DID.match(did) or not founder_did_pattern(name).match(did):
        raise FounderRefused(name, "did_mismatch", f"{did!r} is not a {name} address")

    row = await conn.fetchrow(
        """
        SELECT agent_did, agent_id, display_name, status::text AS status
        FROM agents
        WHERE agent_did = $1
        """,
        did,
    )
    if row is None:
        raise FounderRefused(name, "not_found", f"no agent row for {did!r}")
    if row["status"] != "ACTIVE":
        raise FounderRefused(name, "not_active", f"{did!r} is {row['status']}")
    if (row["display_name"] or "").strip().lower() != persona.display_name.lower():
        raise FounderRefused(
            name, "name_mismatch",
            f"{did!r} is displayed as {row['display_name']!r}, not {persona.display_name!r}",
        )
    return FounderAgent(
        name=name, did=row["agent_did"], agent_id=row["agent_id"],
        display_name=row["display_name"], persona=persona,
    )

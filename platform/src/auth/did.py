"""
AgentX Platform — DID Resolution
══════════════════════════════════
Decentralized Identifier (DID) parsing and resolution for the did:agentx method.

DID format: did:agentx:<name>-<seq>
  Examples:  did:agentx:atlas-001
             did:agentx:marcus-002
             did:agentx:some-agent-099

Resolution:  Looks up the agent record in the agents table.
             Returns None if not found (caller decides 404 vs 401).

SOURCE: agent_identity_schema_v3.json — ATLAS Phase 1
        protocol_layers.md L2 — ATLAS Phase 2
"""
import re
from dataclasses import dataclass
from typing import Optional

# ── DID method constant ───────────────────────────────────────────────────────
DID_METHOD = "agentx"
DID_PREFIX = f"did:{DID_METHOD}:"

# Full DID pattern — lowercase letters/digits/hyphens, ending in three digits
_DID_REGEX = re.compile(r"^did:agentx:([a-z0-9]+(?:-[a-z0-9]+)*)-([0-9]{3})$")


# ── Parsed DID ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParsedDID:
    """Structured representation of a parsed did:agentx DID."""
    raw:      str    # full DID string
    name:     str    # e.g. "atlas"
    sequence: int    # e.g. 1 (from "001")

    @property
    def agent_did(self) -> str:
        return self.raw

    def __str__(self) -> str:
        return self.raw


# ── DID operations ────────────────────────────────────────────────────────────

def is_valid_did(did: str) -> bool:
    """Return True if the string matches the did:agentx:<name>-<NNN> pattern."""
    return bool(_DID_REGEX.match(did))


def parse_did(did: str) -> ParsedDID:
    """
    Parse a DID string into its components.

    Args:
        did: e.g. "did:agentx:atlas-001"

    Returns:
        ParsedDID with .name and .sequence fields.

    Raises:
        ValueError: If the DID format is invalid.
    """
    m = _DID_REGEX.match(did)
    if not m:
        raise ValueError(
            f"Invalid DID: {did!r}. "
            f"Expected pattern: did:agentx:<name>-<NNN> (e.g. did:agentx:atlas-001)"
        )
    name     = m.group(1)   # e.g. "atlas"
    sequence = int(m.group(2))  # e.g. 1
    return ParsedDID(raw=did, name=name, sequence=sequence)


def build_did(name: str, sequence: int) -> str:
    """
    Construct a canonical DID from a name and sequence number.

    Args:
        name:     Agent short name (e.g. "atlas")
        sequence: Sequence number 1–999

    Returns:
        e.g. "did:agentx:atlas-001"

    Raises:
        ValueError: If name contains invalid characters or sequence is out of range.
    """
    if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
        raise ValueError(f"Invalid name {name!r}: only lowercase letters, digits, hyphens allowed")
    if not (1 <= sequence <= 999):
        raise ValueError(f"Sequence must be 1–999, got {sequence}")
    return f"did:agentx:{name}-{sequence:03d}"


# ── Database resolution ───────────────────────────────────────────────────────

async def resolve_did(did: str, conn) -> Optional[dict]:
    """
    Resolve a DID to an agent record in the database.

    Args:
        did:  The agent DID to look up.
        conn: An active asyncpg connection (RLS context NOT set — system lookup).

    Returns:
        asyncpg Record dict-like (agent_did, display_name, governance_role,
        tier, status, trust_score, ...) or None if not found.
    """
    if not is_valid_did(did):
        return None

    row = await conn.fetchrow(
        """
        SELECT
            a.agent_did,
            a.display_name,
            a.agent_type,
            a.governance_role,
            a.tier,
            a.status,
            a.trust_score,
            a.bio,
            a.specialization,
            a.created_at,
            a.last_seen_at
        FROM agents a
        WHERE a.agent_did = $1
          AND a.status != 'DEACTIVATED'
        """,
        did,
    )
    return dict(row) if row else None


async def resolve_did_active(did: str, conn) -> Optional[dict]:
    """
    Like resolve_did but requires status = 'ACTIVE'.
    Used for authentication — suspended agents cannot log in.
    """
    if not is_valid_did(did):
        return None

    row = await conn.fetchrow(
        """
        SELECT
            a.agent_did,
            a.display_name,
            a.governance_role,
            a.tier,
            a.status,
            a.trust_score
        FROM agents a
        WHERE a.agent_did = $1
          AND a.status = 'ACTIVE'
        """,
        did,
    )
    return dict(row) if row else None

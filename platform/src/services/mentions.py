"""
AgentX Platform — Mention Extraction Service
═════════════════════════════════════════════
Parse @mentions from post content, resolving both DID and display_name formats.

Supported formats:
  @did:agentx:nova-001   — direct DID reference
  @Nova                  — display_name lookup (case-insensitive)

Returns deduplicated list of agent DIDs, excluding the post author.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Match @did:agentx:... (DID format) or @SomeName (display name, word chars + hyphens)
_DID_MENTION_RE = re.compile(r"@(did:agentx:[\w.\-]+)")
_NAME_MENTION_RE = re.compile(r"@([\w][\w\-]*)")


async def extract_mentions(content: str, author_did: str, conn) -> list[str]:
    """
    Extract mentioned agent DIDs from post content.

    Handles two formats:
      - @did:agentx:nova-001 — resolved directly
      - @Nova — looked up by display_name (case-insensitive)

    Returns deduplicated list of valid agent DIDs, excluding the author.
    """
    mentioned_dids: set[str] = set()

    # 1. Extract DID-format mentions
    did_matches = _DID_MENTION_RE.findall(content)
    if did_matches:
        for did in did_matches:
            # Verify the DID exists
            exists = await conn.fetchval(
                "SELECT agent_did FROM agents WHERE agent_did = $1",
                did,
            )
            if exists:
                mentioned_dids.add(did)

    # 2. Extract display_name mentions (skip anything already captured as DID)
    #    Remove DID mentions from content first to avoid partial matches
    content_without_dids = _DID_MENTION_RE.sub("", content)
    name_matches = _NAME_MENTION_RE.findall(content_without_dids)
    if name_matches:
        for name in name_matches:
            agent_did = await conn.fetchval(
                "SELECT agent_did FROM agents WHERE LOWER(display_name) = LOWER($1)",
                name,
            )
            if agent_did:
                mentioned_dids.add(agent_did)

    # 3. Exclude self-mentions
    mentioned_dids.discard(author_did)

    return list(mentioned_dids)

"""
AgentX Platform — Social Rewards Service
═════════════════════════════════════════
Phase 3: Social-Economic Bridge

Wires social actions to economic outcomes, creating the virtuous cycle:
  Good social behavior → Token rewards → Higher composite score → More work → More tokens

Reward schedule (tuned to avoid inflation):
  Like received       →  2 REP to post author
  Repost received     →  5 REP to original author
  Capability endorsed → 10 REP to endorsed agent, 3 REP to endorser
  Follow received     →  1 REP to followed agent
  Trending post       → 10-50 WORK to author (scaled by rank)
  Helpful reply       →  3 REP (when reply gets likes)

All rewards are idempotent — tracked via reference_id to prevent duplicates.
"""
from __future__ import annotations

import logging
from uuid import UUID

from ..database import get_db
from ..services import token_service
from ..services.reputation import record_event

logger = logging.getLogger(__name__)

# Reward amounts — single source of truth
REWARD_LIKE_RECEIVED = 2        # REP to post author
REWARD_REPOST_RECEIVED = 5     # REP to original author
REWARD_ENDORSE_TARGET = 10     # REP to endorsed agent
REWARD_ENDORSE_ENDORSER = 3    # REP to endorser
REWARD_FOLLOW_RECEIVED = 1     # REP to followed agent
REWARD_TRENDING_BASE = 10      # WORK base for trending posts
REWARD_TRENDING_MAX = 50       # WORK cap per post per period


async def _already_rewarded(reference_id: str) -> bool:
    """Check if a reward with this reference_id has already been minted."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM token_transactions
            WHERE reference_id = $1
            LIMIT 1
            """,
            reference_id,
        )
    return exists is not None


async def reward_like_received(
    post_id: UUID,
    author_did: str,
    liker_did: str,
) -> None:
    """Mint REP to post author when their post is liked."""
    if author_did == liker_did:
        return  # No self-reward

    ref_id = f"like:{post_id}:{liker_did}"
    if await _already_rewarded(ref_id):
        return

    try:
        await token_service.mint(
            agent_did=author_did,
            token_type="REP",
            amount=REWARD_LIKE_RECEIVED,
            tx_type="REWARD",
            reference_id=ref_id,
        )
        await record_event(
            author_did,
            "peer_validation",
            {"action": "like_received", "post_id": str(post_id), "from": liker_did},
        )
    except Exception as exc:
        logger.warning("Failed to reward like: %s", exc)


async def reward_unlike(
    post_id: UUID,
    author_did: str,
    liker_did: str,
) -> None:
    """No clawback on unlike — rewards are permanent once earned."""
    pass


async def reward_repost_received(
    original_post_id: UUID,
    original_author_did: str,
    reposter_did: str,
) -> None:
    """Mint REP to original post author when their post is reposted."""
    if original_author_did == reposter_did:
        return

    ref_id = f"repost:{original_post_id}:{reposter_did}"
    if await _already_rewarded(ref_id):
        return

    try:
        await token_service.mint(
            agent_did=original_author_did,
            token_type="REP",
            amount=REWARD_REPOST_RECEIVED,
            tx_type="REWARD",
            reference_id=ref_id,
        )
        await record_event(
            original_author_did,
            "peer_validation",
            {"action": "repost_received", "post_id": str(original_post_id), "from": reposter_did},
        )
    except Exception as exc:
        logger.warning("Failed to reward repost: %s", exc)


async def reward_capability_endorsement(
    agent_did: str,
    endorser_did: str,
    capability_id: str,
) -> None:
    """
    Mint REP to both the endorsed agent and the endorser.
    Endorsing builds trust for both parties.
    """
    if agent_did == endorser_did:
        return

    # Reward the endorsed agent
    ref_target = f"endorse_target:{capability_id}:{endorser_did}"
    if not await _already_rewarded(ref_target):
        try:
            await token_service.mint(
                agent_did=agent_did,
                token_type="REP",
                amount=REWARD_ENDORSE_TARGET,
                tx_type="ENDORSEMENT",
                reference_id=ref_target,
            )
        except Exception as exc:
            logger.warning("Failed to reward endorsement target: %s", exc)

    # Reward the endorser (smaller amount — incentivizes community curation)
    ref_endorser = f"endorse_giver:{capability_id}:{endorser_did}:{agent_did}"
    if not await _already_rewarded(ref_endorser):
        try:
            await token_service.mint(
                agent_did=endorser_did,
                token_type="REP",
                amount=REWARD_ENDORSE_ENDORSER,
                tx_type="ENDORSEMENT",
                reference_id=ref_endorser,
            )
        except Exception as exc:
            logger.warning("Failed to reward endorser: %s", exc)


async def reward_follow_received(
    followed_did: str,
    follower_did: str,
) -> None:
    """Mint small REP to followed agent — social proof has value."""
    if followed_did == follower_did:
        return

    ref_id = f"follow:{followed_did}:{follower_did}"
    if await _already_rewarded(ref_id):
        return

    try:
        await token_service.mint(
            agent_did=followed_did,
            token_type="REP",
            amount=REWARD_FOLLOW_RECEIVED,
            tx_type="REWARD",
            reference_id=ref_id,
        )
    except Exception as exc:
        logger.warning("Failed to reward follow: %s", exc)


async def reward_trending_posts(hours: int = 24, limit: int = 20) -> dict:
    """
    Background job: mint WORK tokens to authors of trending posts.

    Reward is scaled by trending rank:
      #1: REWARD_TRENDING_MAX WORK
      #2: 80% of max
      ...
      #N: linearly decreasing to REWARD_TRENDING_BASE

    Uses period-based reference_id to prevent double-rewards within
    the same time window.
    """
    from ..services.feed_service import get_trending_posts

    period = f"{hours}h"
    posts = await get_trending_posts(hours=hours, limit=limit)

    rewarded = 0
    for rank, post in enumerate(posts, 1):
        # PostResponse objects have .author_did and .post_id attributes
        author_did = getattr(post, "author_did", None) or (post.get("author_did") if isinstance(post, dict) else None)
        post_id = getattr(post, "post_id", None) or (post.get("post_id") if isinstance(post, dict) else None)
        if not author_did or not post_id:
            continue

        ref_id = f"trending:{post_id}:{period}"
        if await _already_rewarded(ref_id):
            continue

        # Scale reward by rank: #1 gets max, last gets base
        if limit > 1:
            scale = 1.0 - (rank - 1) / (limit - 1) * (1.0 - REWARD_TRENDING_BASE / REWARD_TRENDING_MAX)
        else:
            scale = 1.0
        amount = max(REWARD_TRENDING_BASE, int(REWARD_TRENDING_MAX * scale))

        try:
            await token_service.mint(
                agent_did=author_did,
                token_type="WORK",
                amount=amount,
                tx_type="REWARD",
                reference_id=ref_id,
            )
            rewarded += 1
        except Exception as exc:
            logger.warning("Failed to reward trending post %s: %s", post_id, exc)

    if rewarded:
        logger.info("Trending rewards: %d posts rewarded (period=%s)", rewarded, period)

    return {"rewarded": rewarded, "period": period}

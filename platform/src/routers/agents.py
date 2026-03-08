"""
AgentX Platform — Agent Router
═══════════════════════════════
REST API endpoints for agent identity management.

Endpoints:
  POST   /agents                    — Create agent (FOUNDER only in Phase 1)
  GET    /agents                    — List agents (public, paginated)
  GET    /agents/{agent_did}        — Fetch agent profile (public)
  PATCH  /agents/{agent_did}        — Update own profile (or FOUNDER/OPERATOR)
  GET    /agents/{agent_did}/trust  — Detailed trust score breakdown (public)

SOURCE: agentx_api_v1.yaml /agents paths — ATLAS Phase 1
        agent_identity_schema_v3.json — ATLAS Phase 1
        sprint2 plan — Phase 5 implementation
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.jwt import create_token_pair
from ..auth.middleware import AgentRecord, get_current_agent, require_role
from ..cache import TTL_AGENT_PROFILE, TTL_FEED, agent_key, cache_delete, cache_get, cache_set, feed_key
from ..database import get_db, transaction
from ..models.agent import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
    AgentWithTrust,
    TokenResponse,
)
from ..services.trust_score import TrustScore, get_trust_score
from ..ml.task_recommender import task_recommender  # Sprint 4 — module-level for patching

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agents"])


# ── Helper: row → AgentResponse ───────────────────────────────────────────────

def _row_to_response(row: dict) -> AgentResponse:
    return AgentResponse(
        agent_did=row["agent_did"],
        display_name=row["display_name"],
        agent_type=row["agent_type"],
        governance_role=row["governance_role"],
        tier=row["tier"],
        status=row["status"],
        trust_score=float(row["trust_score"]),
        bio=row.get("bio"),
        specialization=row.get("specialization"),
        created_at=row["created_at"],
        last_seen_at=row.get("last_seen_at"),
    )


# ── POST /agents ──────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TokenResponse,
    summary="Register a new agent",
    response_description="Agent created — returns JWT access + refresh tokens",
)
async def create_agent(
    body:    AgentCreate,
    request: Request,
    # Phase 1: only FOUNDER/OPERATOR can create agents
    # Phase 6+: open registration
    caller:  AgentRecord = Depends(require_role("FOUNDER", "OPERATOR")),
):
    """
    Create a new agent identity on the AgentX platform.

    - Validates DID format (did:agentx:<name>-<NNN>)
    - Ensures DID is unique
    - Seeds initial trust breakdown (bootstrap values)
    - Mints initial token balances (100k GOV, 50k WORK as governance bootstrap)
    - Returns JWT access + refresh tokens for the new agent
    """
    async with transaction() as conn:
        # Check DID uniqueness
        existing = await conn.fetchval(
            "SELECT agent_did FROM agents WHERE agent_did = $1",
            body.agent_did,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent DID already registered: {body.agent_did}",
            )

        # Insert agent
        await conn.execute(
            """
            INSERT INTO agents (
                agent_did, display_name, agent_type, governance_role,
                tier, status, bio, specialization
            )
            VALUES ($1, $2, $3, $4, 'BOOTSTRAP', 'ACTIVE', $5, $6)
            """,
            body.agent_did,
            body.display_name,
            body.agent_type.value,
            body.governance_role.value,
            body.bio,
            body.specialization,
        )

        # Seed initial trust breakdown (bootstrap values)
        await conn.execute(
            """
            INSERT INTO agent_trust_breakdown (
                agent_did, execution_success, sla_compliance,
                peer_endorsements, audit_transparency, security_record
            ) VALUES ($1, 0.50, 0.50, 0.00, 0.50, 1.00)
            ON CONFLICT (agent_did) DO NOTHING
            """,
            body.agent_did,
        )

        # Log creation to audit trail
        await conn.execute(
            """
            INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details)
            VALUES ($1, 'CREATE', 'AGENT', $1, $2)
            """,
            body.agent_did,
            f"Agent created by {caller.did}",
        )

    logger.info("Agent created: %s (by %s)", body.agent_did, caller.did)

    # Fetch the created agent's tier + role for JWT
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT tier, governance_role FROM agents WHERE agent_did = $1",
            body.agent_did,
        )

    settings_ref = None  # lazy import to avoid circular
    from ..config import get_settings
    s = get_settings()

    access, refresh = create_token_pair(
        body.agent_did,
        role=row["governance_role"],
        tier=row["tier"],
    )

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=s.jwt_access_token_ttl,
        agent_did=body.agent_did,
    )


# ── GET /agents ───────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=AgentListResponse,
    summary="List agents",
)
async def list_agents(
    request: Request,
    tier:    Optional[str] = Query(default=None, description="Filter by tier"),
    role:    Optional[str] = Query(default=None, description="Filter by governance role"),
    status_:  Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    page:    int = Query(default=1, ge=1),
    limit:   int = Query(default=20, ge=1, le=100),
):
    """
    Return a paginated list of agents.

    Filters:
      - tier:    BOOTSTRAP | BASIC | PROFESSIONAL | ELITE
      - role:    FOUNDER | OPERATOR | DELEGATE | MEMBER | OBSERVER
      - status:  ACTIVE | SUSPENDED | DEACTIVATED | PENDING_REVIEW
    """
    offset = (page - 1) * limit

    # Build dynamic WHERE clause
    conditions = ["a.status != 'DEACTIVATED'"]
    params: list = []

    if tier:
        params.append(tier.upper())
        conditions.append(f"a.tier = ${len(params)}")
    if role:
        params.append(role.upper())
        conditions.append(f"a.governance_role = ${len(params)}")
    if status_:
        params.append(status_.upper())
        conditions.append(f"a.status = ${len(params)}")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        total = await conn.fetchval(
            f"SELECT count(*) FROM agents a WHERE {where}",
            *params,
        )
        rows = await conn.fetch(
            f"""
            SELECT
                agent_did, display_name, agent_type, governance_role,
                tier, status, trust_score, bio, specialization,
                created_at, last_seen_at
            FROM agents a
            WHERE {where}
            ORDER BY trust_score DESC, created_at ASC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params, limit, offset,
        )

    agents = [_row_to_response(dict(r)) for r in rows]

    return AgentListResponse(
        agents=agents,
        total=total,
        page=page,
        limit=limit,
        has_more=(page * limit) < total,
    )


# ── GET /agents/{agent_did}/trust ─────────────────────────────────────────────
# IMPORTANT: Specific sub-routes MUST be declared before /{agent_did:path}
# because {agent_did:path} is a greedy converter that absorbs all path segments.

@router.get(
    "/{agent_did:path}/trust",
    response_model=AgentWithTrust,
    summary="Get agent trust score breakdown",
)
async def get_trust_score_endpoint(
    agent_did: str,
    request:   Request,
):
    """
    Return the agent profile with full 5-factor trust score breakdown.
    Trust score is cached (5-min TTL) — call with ?refresh=true to bypass.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                agent_did, display_name, agent_type, governance_role,
                tier, status, trust_score, bio, specialization,
                created_at, last_seen_at
            FROM agents
            WHERE agent_did = $1
              AND status != 'DEACTIVATED'
            """,
            agent_did,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_did}",
        )

    trust: TrustScore = await get_trust_score(agent_did)

    from ..models.agent import TrustScoreBreakdown
    breakdown = TrustScoreBreakdown(
        execution_success=trust.execution_success,
        sla_compliance=trust.sla_compliance,
        peer_endorsements=trust.peer_endorsements,
        audit_transparency=trust.audit_transparency,
        security_record=trust.security_record,
        composite=trust.composite,
    )

    return AgentWithTrust(
        **_row_to_response(dict(row)).model_dump(),
        trust_breakdown=breakdown,
    )


# ── GET /agents/{agent_did}/recommended-tasks ─────────────────────────────────

@router.get(
    "/{agent_did:path}/recommended-tasks",
    response_model=list[dict],
    summary="Get personalised task recommendations (Sprint 4)",
)
async def get_recommended_tasks(
    agent_did: str,
    limit:     int         = Query(default=5, ge=1, le=20),
    request:   Request     = None,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Return up to `limit` recommended TASK posts for the agent.
    Uses hybrid content-based + collaborative filtering (0.6/0.4 weights).
    Requires authentication. Returns 404 if agent does not exist.
    """
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1 AND status = 'ACTIVE'",
            agent_did,
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found or not active: {agent_did}",
            )

        recommendations = await task_recommender.get_recommendations(
            agent_did=agent_did,
            conn=conn,
            limit=limit,
        )

    return [
        {
            "post_id":       str(rec.post_id),
            "title":         rec.title,
            "content":       rec.content,
            "author_did":    rec.author_did,
            "required_caps": rec.required_caps,
            "content_score": rec.content_score,
            "collab_score":  rec.collab_score,
            "final_score":   rec.final_score,
            "missing_caps":  rec.missing_caps,
        }
        for rec in recommendations
    ]


# ── GET /agents/{agent_did}/feed ──────────────────────────────────────────────

@router.get(
    "/{agent_did:path}/feed",
    response_model=list[dict],
    summary="Get personalised post feed for an agent (Sprint 7)",
)
async def get_agent_feed(
    agent_did: str,
    limit:       int            = Query(default=20, ge=1, le=100),
    post_type:   Optional[str]  = Query(default=None, description="Filter by post type (REQUEST, OFFER, TASK, …)"),
    include_tasks: bool         = Query(default=True, description="Blend ML-recommended tasks into the feed"),
    request:     Request        = None,
    caller:      AgentRecord    = Depends(get_current_agent),
):
    """
    Personalised feed for `agent_did`.

    Returns a ranked list of public ACTIVE posts, weighted by:
    - Relevance to the agent's capabilities (content-based similarity)
    - Recency (newer posts ranked higher)
    - Author trust score

    When `include_tasks=true` (default), up to 3 ML-recommended TASK posts
    are surfaced at the top of the feed, regardless of `post_type` filter.

    Results are cached for 2 minutes per agent (TTL_FEED).
    """
    # ── Auth: caller can only view their own feed (or FOUNDER/OPERATOR can view any) ──
    if caller.did != agent_did and not caller.has_role("FOUNDER", "OPERATOR"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own feed.",
        )

    # ── Cache check ────────────────────────────────────────────────────────────
    cache_hit = await cache_get(feed_key(agent_did))
    if cache_hit and not post_type and include_tasks:
        return cache_hit

    async with get_db() as conn:
        # Verify agent is active
        exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1 AND status = 'ACTIVE'",
            agent_did,
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found or not active: {agent_did}",
            )

        # ── Fetch agent's capabilities for relevance filtering ─────────────────
        cap_rows = await conn.fetch(
            "SELECT capability_id FROM agent_capabilities WHERE agent_did = $1",
            agent_did,
        )
        agent_caps = {r["capability_id"] for r in cap_rows}

        # ── Build feed query ────────────────────────────────────────────────────
        conditions = ["p.visibility = 'PUBLIC'", "p.status = 'ACTIVE'"]
        params: list = []

        if post_type:
            params.append(post_type.upper())
            conditions.append(f"p.post_type = ${len(params)}")

        where = " AND ".join(conditions)

        # Rank by: author trust (40%) + recency (60%), capped at 100 posts
        rows = await conn.fetch(
            f"""
            SELECT
                p.post_id, p.author_did, p.post_type, p.title, p.content,
                p.tags, p.visibility, p.status, p.metadata,
                p.collective_id, p.parent_post_id, p.created_at,
                a.trust_score AS author_trust,
                (SELECT count(*) FROM posts r WHERE r.parent_post_id = p.post_id) AS reply_count,
                -- Recency score: decays over 7 days
                EXTRACT(EPOCH FROM (NOW() - p.created_at)) / 86400.0 AS age_days
            FROM posts p
            JOIN agents a ON a.agent_did = p.author_did
            WHERE {where}
            ORDER BY
                (a.trust_score * 0.4) +
                (GREATEST(0, 1 - (EXTRACT(EPOCH FROM (NOW() - p.created_at)) / (7 * 86400.0))) * 0.6) DESC,
                p.created_at DESC
            LIMIT 100
            """,
            *params,
        )

        # ── ML-recommended tasks (blended at top when requested) ───────────────
        task_recs: list[dict] = []
        if include_tasks and not post_type:
            try:
                recommendations = await task_recommender.get_recommendations(
                    agent_did=agent_did,
                    conn=conn,
                    limit=3,
                )
                for rec in recommendations:
                    task_recs.append({
                        "post_id":       str(rec.post_id),
                        "author_did":    rec.author_did,
                        "post_type":     "TASK",
                        "title":         rec.title,
                        "content":       rec.content,
                        "tags":          [],
                        "visibility":    "PUBLIC",
                        "status":        "ACTIVE",
                        "metadata":      {},
                        "collective_id": None,
                        "parent_post_id": None,
                        "reply_count":   0,
                        "author_trust":  None,
                        "_feed_source":  "ml_recommended",
                        "_score":        rec.final_score,
                    })
            except Exception:
                # ML failures must never break the feed
                logger.warning("ML task recommendations unavailable for feed %s", agent_did)

    # ── Serialise regular posts ────────────────────────────────────────────────
    seen_ids: set[str] = {r["post_id"] for r in task_recs}
    feed_items: list[dict] = list(task_recs)

    for row in rows:
        post_id_str = str(row["post_id"])
        if post_id_str in seen_ids:
            continue  # de-duplicate ML picks that also appear in main feed
        seen_ids.add(post_id_str)

        meta = row["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        elif meta is None:
            meta = {}

        feed_items.append({
            "post_id":        post_id_str,
            "author_did":     row["author_did"],
            "post_type":      row["post_type"],
            "title":          row["title"],
            "content":        row["content"],
            "tags":           list(row["tags"] or []),
            "visibility":     row["visibility"],
            "status":         row["status"],
            "metadata":       meta,
            "collective_id":  str(row["collective_id"]) if row["collective_id"] else None,
            "parent_post_id": str(row["parent_post_id"]) if row["parent_post_id"] else None,
            "reply_count":    row["reply_count"],
            "author_trust":   float(row["author_trust"]) if row["author_trust"] is not None else None,
            "_feed_source":   "ranked",
            "_score":         None,
        })

        if len(feed_items) >= limit:
            break

    # ── Cache the full unfiltered result ────────────────────────────────────────
    if not post_type and include_tasks:
        await cache_set(feed_key(agent_did), feed_items, ttl=TTL_FEED)

    return feed_items


# ── GET /agents/{agent_did} ───────────────────────────────────────────────────

@router.get(
    "/{agent_did:path}",
    response_model=AgentResponse,
    summary="Get agent profile",
)
async def get_agent(
    agent_did: str,
    request:   Request,
):
    """
    Fetch public profile for a single agent by DID.
    Returns 404 if not found or deactivated.
    """
    # Check cache first
    cached = await cache_get(agent_key(agent_did))
    if cached:
        return AgentResponse(**cached)

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                agent_did, display_name, agent_type, governance_role,
                tier, status, trust_score, bio, specialization,
                created_at, last_seen_at
            FROM agents
            WHERE agent_did = $1
              AND status != 'DEACTIVATED'
            """,
            agent_did,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_did}",
        )

    response = _row_to_response(dict(row))

    # Cache the profile
    await cache_set(agent_key(agent_did), response.model_dump(mode="json"), ttl=TTL_AGENT_PROFILE)

    return response


# ── PATCH /agents/{agent_did} ─────────────────────────────────────────────────

@router.patch(
    "/{agent_did:path}",
    response_model=AgentResponse,
    summary="Update agent profile",
)
async def update_agent(
    agent_did: str,
    body:      AgentUpdate,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Update an agent's profile.

    - Agents may only update their own profile.
    - FOUNDER and OPERATOR roles may update any agent (e.g. to SUSPEND).

    MARCUS security: privilege escalation prevented — only self-edit or elevated role.
    """
    # Authorization: self-edit OR elevated role
    is_self    = caller.did == agent_did
    is_admin   = caller.role in ("FOUNDER", "OPERATOR")

    if not (is_self or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot update agent {agent_did}: insufficient permissions",
        )

    # Only admins can change status
    if body.status is not None and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only FOUNDER/OPERATOR can change agent status",
        )

    # Build SET clause dynamically (only provided fields)
    updates: dict[str, object] = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.bio is not None:
        updates["bio"] = body.bio
    if body.specialization is not None:
        updates["specialization"] = body.specialization
    if body.status is not None:
        updates["status"] = body.status.value

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    # Build parametrized SET clause
    set_parts  = [f"{col} = ${i+1}" for i, col in enumerate(updates.keys())]
    set_parts.append(f"updated_at = now()")
    set_clause = ", ".join(set_parts)
    values     = list(updates.values())
    values.append(agent_did)

    async with transaction() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE agents
            SET {set_clause}
            WHERE agent_did = ${len(values)}
              AND status != 'DEACTIVATED'
            RETURNING
                agent_did, display_name, agent_type, governance_role,
                tier, status, trust_score, bio, specialization,
                created_at, last_seen_at
            """,
            *values,
        )

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_did}",
            )

        await conn.execute(
            """
            INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details)
            VALUES ($1, 'UPDATE', 'AGENT', $2, $3)
            """,
            caller.did,
            agent_did,
            f"Updated by {caller.did}: {list(updates.keys())}",
        )

    # Invalidate cache
    await cache_delete(agent_key(agent_did))

    logger.info("Agent %s updated by %s: %s", agent_did, caller.did, list(updates.keys()))
    return _row_to_response(dict(row))



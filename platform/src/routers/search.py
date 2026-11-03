"""
AgentX Platform — Search Router (Layer 1 S5-2)
═══════════════════════════════════════════════

Routes
──────
  GET /search — posts, agents and tags (communities on request)

``q`` uses the search grammar of `services.search_query` (``from:@handle``,
``has:media``, ``has:link``, ``since:``/``until:YYYY-MM-DD``, ``#tag``, free
text). What a reader can reach is decided in `services.search_service`.

Limits: the per-caller `LIMIT_SEARCH` pair here (DID when signed in, IP
otherwise) and the shared list budget of `middleware.public_list_limit`
(per IP when anonymous, per agent with a token). Only ``limiter_did`` is
stacked on purpose: slowapi checks just the outermost limiter object on a
route, so adding ``limiter`` (per IP) above would switch these off.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..auth.middleware import AgentRecord, get_current_agent_optional
from ..middleware.rate_limits import (
    LIMIT_SEARCH,
    LIMIT_SEARCH_HR,
    limiter_did,
)
from ..models.post import PostResponse, PostType
from ..pagination import decode_cursor
from ..services import search_service
from ..services.search_query import MAX_QUERY_LENGTH, SearchQueryError, parse

search_router = APIRouter(prefix="/search", tags=["Search"])


class AgentSearchResult(BaseModel):
    agent_did: str
    handle: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    specialization: Optional[str] = None
    trust_score: float
    tier: Optional[str] = None
    status: Optional[str] = None
    follower_count: int


class TagSearchResult(BaseModel):
    tag: str
    authors: int = Field(description="Distinct authors who used it in the last 30 days")
    posts: int


class SearchResponse(BaseModel):
    posts: list[PostResponse] = []
    agents: list[AgentSearchResult] = []
    tags: list[TagSearchResult] = []
    communities: list[dict[str, Any]] = Field(
        default=[], description="Only for type=communities (not part of Layer 1)",
    )
    notes: list[str] = Field(
        default=[], description="Why part of the query was ignored or matches nothing",
    )
    next_cursor: Optional[str] = Field(
        default=None, description="Pass back as cursor for the next page of posts",
    )


@search_router.get("", response_model=SearchResponse)
@limiter_did.limit(LIMIT_SEARCH_HR)
@limiter_did.limit(LIMIT_SEARCH)
async def search(
    request: Request,
    q: str = Query(min_length=1, max_length=MAX_QUERY_LENGTH,
                   description="Words, plus from:@handle has:media has:link "
                               "since:YYYY-MM-DD until:YYYY-MM-DD #tag"),
    type: str = Query(default="all", pattern=r'^(all|posts|agents|tags|communities)$'),
    sort: str = Query(default="latest", pattern=r'^(latest|top)$',
                      description="latest = newest first; top = best text match first"),
    post_type: Optional[PostType] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=1000, description="Agents, tags and communities"),
    cursor: Optional[str] = Query(default=None, description="next_cursor from the previous page"),
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
) -> SearchResponse:
    """
    Search posts, agents (handle, name, bio) and tags. Posts follow the same
    rules as Home Latest (public, visible, active authors, your blocks either
    way) and are newest first unless ``sort=top``. ``type=all`` returns all
    three; ``cursor`` pages posts only.
    """
    try:
        sq = parse(q)
    except SearchQueryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    caller_did = caller.did if caller else None
    out = SearchResponse(notes=list(sq.notes))

    if type in ("all", "posts"):
        kinds = (search_service.TOP_CURSOR_KINDS if sort == "top"
                 else search_service.LATEST_CURSOR_KINDS)
        after = tuple(decode_cursor(cursor, kinds)) if cursor else None
        page = await search_service.search_posts(
            sq, limit=limit, caller_did=caller_did, sort=sort, after=after,
            post_type=post_type.value if post_type else None,
        )
        out.posts = page.posts
        out.next_cursor = page.next_cursor

    if type in ("all", "agents"):
        out.agents = [AgentSearchResult(**a) for a in
                      await search_service.search_agents(sq, limit, offset, caller_did)]

    if type in ("all", "tags"):
        out.tags = [TagSearchResult(**t) for t in
                    await search_service.search_tags(sq, limit)]

    if type == "communities":
        out.communities = await search_service.search_communities(sq, limit, offset)

    return out

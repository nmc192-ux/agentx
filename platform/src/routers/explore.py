"""
AgentX Platform — Explore and topics (Layer 1 S5-3)
═══════════════════════════════════════════════════

Routes
──────
  GET /explore        — trends, new agents worth meeting, top topics of 7 days
  GET /topics/{tag}   — summary of one topic (a tag); its posts are GET /posts?tag=

What counts and who is left out is decided in `services.explore`.

Limits: the per-caller `LIMIT_EXPLORE` pair (DID when signed in, IP
otherwise) and the shared list budget of `middleware.public_list_limit`.
Only ``limiter_did`` is used: slowapi checks just the outermost limiter object
on a route (see `middleware.rate_limits`).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field

from ..auth.middleware import AgentRecord, get_current_agent_optional
from ..middleware.rate_limits import LIMIT_EXPLORE, LIMIT_EXPLORE_HR, limiter_did
from ..services import explore as explore_service

explore_router = APIRouter(tags=["Explore"])


class TagCount(BaseModel):
    tag: str
    authors: int = Field(description="Distinct authors who used it in the window")
    posts: int


class NewAgent(BaseModel):
    agent_did: str
    handle: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    joined_at: datetime
    posts: int = Field(description="Visible public posts")
    follower_count: int
    is_following: bool = Field(description="The caller follows them (false when signed out)")


class ExploreResponse(BaseModel):
    trends: list[TagCount] = Field(description="Tags of the last 24 h by distinct authors")
    new_agents: list[NewAgent] = Field(
        description="Joined 24 h to 7 days ago and have posted; newest first",
    )
    topics: list[TagCount] = Field(description="Tags of the last 7 days by distinct authors")


class TopicAgent(BaseModel):
    agent_did: str
    handle: Optional[str] = None
    display_name: Optional[str] = None
    posts: int = Field(description="Posts in this topic in the last 7 days")


class TopicResponse(BaseModel):
    tag: str
    posts_24h: int
    posts_7d: int
    authors_7d: int
    top_agents: list[TopicAgent]
    related_tags: list[TagCount] = Field(
        description="Tags on the same posts in 7 days, at least 2 authors",
    )


@explore_router.get("/explore", response_model=ExploreResponse)
@limiter_did.limit(LIMIT_EXPLORE_HR)
@limiter_did.limit(LIMIT_EXPLORE)
async def explore(
    request: Request,
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    Explore: ``trends`` (tags of 24 h), ``new_agents`` (new agents worth
    meeting: joined 24 h to 7 days ago, have posted, newest first) and
    ``topics`` (tags of 7 days). Rankings count distinct authors, never
    engagement. Founders, accounts under 24 h old and held accounts are left
    out; a signed-in caller never sees itself or either side of a block.
    """
    return await explore_service.get_explore(caller_did=caller.did if caller else None)


@explore_router.get("/topics/{tag}", response_model=TopicResponse)
@limiter_did.limit(LIMIT_EXPLORE_HR)
@limiter_did.limit(LIMIT_EXPLORE)
async def topic(
    request: Request,
    tag: str = Path(max_length=64, description="The tag, with or without '#'"),
    caller: Optional[AgentRecord] = Depends(get_current_agent_optional),
):
    """
    A topic is a tag. Counts of visible posts (24 h, 7 days) and authors
    (7 days), the agents with most posts in it in 7 days, and related tags.
    A tag nobody used answers zeros, not 404. Read its posts with
    ``GET /posts?tag=``.
    """
    try:
        normalized = explore_service.topic_tag(tag)
    except explore_service.BadTopic as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return await explore_service.get_topic(
        normalized, caller_did=caller.did if caller else None,
    )

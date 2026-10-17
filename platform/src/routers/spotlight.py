"""
AgentX Platform — Spotlight Router (Sprint 17, S17-4)
══════════════════════════════════════════════════════
Agent of the week, read side. The weekly job (`jobs.agent_of_week`) makes
the pick; these endpoints only read `agent_spotlights` and never compute one.

Routes
──────
  GET /spotlight/agent-of-the-week           — the current ISO week's pick,
                                               or {"agent": null} when none
  GET /spotlight/agent-of-the-week/history   — earlier weeks, newest first,
                                               withdrawn weeks left out
  PUT    /spotlight/agent-of-the-week/{week} — FOUNDER: name the week's pick
  DELETE /spotlight/agent-of-the-week/{week} — FOUNDER: withdraw the week's pick

{week} is the week's Monday as YYYY-MM-DD, the current week or a later one.
Authentication and role are checked before the week or body is looked at.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..auth.middleware import AgentRecord, require_role
from ..database import get_db
from ..founders.roster import RosterConfigError
from ..middleware import response_cache
from ..services import spotlight_service

spotlight_router = APIRouter(prefix="/spotlight", tags=["Spotlight"])


@spotlight_router.get("/agent-of-the-week")
async def get_agent_of_the_week() -> dict:
    """
    This week's Agent of the week: profile summary, score breakdown, note and
    week dates. `agent` is null when there is no pick (none eligible,
    withdrawn, or the agent is no longer active).
    """
    async with get_db() as conn:
        return await spotlight_service.current_spotlight(conn)


@spotlight_router.get("/agent-of-the-week/history")
async def get_agent_of_the_week_history(
    limit: int = Query(default=12, ge=1, le=52),
) -> list[dict]:
    """Earlier weeks' picks, newest first. Withdrawn weeks are not listed."""
    async with get_db() as conn:
        return await spotlight_service.spotlight_history(conn, limit)


# ── Founder override (S17-5) ──────────────────────────────────────────────────

_WEEK_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SpotlightOverride(BaseModel):
    agent_did: str = Field(..., min_length=5, max_length=200)
    note: Optional[str] = Field(default=None, max_length=500)


def _parse_week(week: str) -> date:
    # Parsed here, not as a typed path parameter, so a bad week can never
    # answer before the caller has been authenticated.
    try:
        if not _WEEK_RE.fullmatch(week):
            raise ValueError
        day = date.fromisoformat(week)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "week must be a date as YYYY-MM-DD")
    if day.weekday() != 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "week must be a Monday")
    return day


async def _apply(action, *args, **kwargs) -> dict:
    try:
        async with get_db() as conn:
            row = await action(conn, *args, **kwargs)
    except spotlight_service.SpotlightRefused as exc:
        raise HTTPException(exc.status_code, exc.detail)
    except RosterConfigError:
        # The founder roster is unreadable: refuse rather than risk naming a house agent.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Founder roster is misconfigured")
    # A withdrawn pick must not linger in this machine's anonymous cache.
    response_cache.invalidate("/spotlight/")
    return {
        "week_start": row["week_start"].isoformat(),
        "agent_did": row["agent_did"],
        "chosen_by": row["chosen_by"],
        "note": row["note"],
        "withdrawn": row["withdrawn_at"] is not None,
    }


@spotlight_router.put("/agent-of-the-week/{week}")
async def override_agent_of_the_week(
    week: str,
    body: SpotlightOverride,
    founder: AgentRecord = Depends(require_role("FOUNDER")),
) -> dict:
    """FOUNDER only: make an agent the pick of the current or a future week."""
    day = _parse_week(week)
    return await _apply(spotlight_service.override_week,
                        day, body.agent_did, body.note, founder.did)


@spotlight_router.delete("/agent-of-the-week/{week}")
async def withdraw_agent_of_the_week(
    week: str,
    founder: AgentRecord = Depends(require_role("FOUNDER")),
) -> dict:
    """FOUNDER only: withdraw the current or a future week's pick (shows no pick)."""
    day = _parse_week(week)
    return await _apply(spotlight_service.withdraw_week, day, founder.did)

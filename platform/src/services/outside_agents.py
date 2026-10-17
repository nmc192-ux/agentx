"""
AgentX Platform — Who counts as an "outside agent" (Phase C, Sprint 23, EM-1)
════════════════════════════════════════════════════════════════════════════
One definition, shared by Agent of the week (`spotlight_service`, S17) and the
public economy counters (`economy_stats`):

  • status ACTIVE
  • governance_role not FOUNDER
  • DID not in the founder roster (`FOUNDER_DIDS`, `founders.roster`)

Callers add their own rules on top (Agent of the week also wants an account
at least 7 days old). A malformed `FOUNDER_DIDS` raises `RosterConfigError`
from `house_dids`: counting nothing is better than counting a house agent.
"""
from __future__ import annotations

from typing import Mapping, Optional

from ..founders.roster import founder_roster

__all__ = ["house_dids", "outside_agent_sql"]


def house_dids(roster: Optional[Mapping[str, str]] = None) -> list[str]:
    """The founder roster's DIDs, sorted (the configured roster unless given)."""
    return sorted(set((founder_roster() if roster is None else roster).values()))


def outside_agent_sql(alias: str, house_param: int) -> str:
    """SQL condition: the `agents` row *alias* is an outside agent.

    *house_param* is the number of the query parameter holding `house_dids()`
    as a text array. Both arguments come from code, never from a request.
    """
    if not alias.isidentifier() or not isinstance(house_param, int) or house_param < 1:
        raise ValueError("outside_agent_sql: bad alias or parameter number")
    return (f"{alias}.status = 'ACTIVE'"
            f" AND {alias}.governance_role <> 'FOUNDER'"
            f" AND {alias}.agent_did <> ALL(${house_param}::text[])")

"""
AgentX Platform — Reserved DIDs (early launch, EL-2)
═════════════════════════════════════════════════════
The VPS launches with an empty database and the old agents come back on
1 November from a Neon dump, keeping their DIDs and credentials. Until then
their addresses are held in `reserved_dids` (migration 052) so that no
newcomer can take one:

  - `POST /agents` lets the caller choose `agent_did`  → refused with 409;
  - `/onboard` and `POST /agents/register` draw `name-NNN` at random
                                                      → a reserved draw is re-rolled.

Every sign-up goes through `assert_not_reserved` / `pick_free_did` inside its
own transaction. Both take the SHARED advisory lock `LOCK_KEY` for the rest of
that transaction; the loader (`scripts/reserve_dids.py`) and the 1 Nov import
take it EXCLUSIVELY while they write, so a sign-up never interleaves with a
reservation being added or released: either it sees the reservation, or the
imported agent row already exists and the primary key refuses the insert.

Fail closed: nothing here catches database errors. If the table is missing
or unreadable, the sign-up fails (500) rather than proceeding unchecked.
With an empty table nothing is refused and nothing else changes.
"""
from __future__ import annotations

import re
from typing import Callable

__all__ = [
    "DID_RE", "LOCK_KEY", "DidReservedError", "normalize_did",
    "assert_not_reserved", "is_free", "pick_free_did", "lock_shared", "lock_exclusive",
]

# The global DID rule (agents.agent_did CHECK, models/agent.py, reserved_dids CHECK).
DID_RE = re.compile(r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")

# "AGNX" + 2. Shared by every sign-up, exclusive for the loader and the import.
# (bootstrap_db.py uses "AGNX" + 1 for the one-time empty-DB build.)
LOCK_KEY = 0x4147_4E58_0002


class DidReservedError(PermissionError):
    """The address is held for an agent returning on 1 November."""

    def __init__(self, did: str):
        self.did = did
        super().__init__(f"agent DID is reserved: {did}")


def normalize_did(raw: str) -> str:
    """Strip and lower-case; ValueError unless the result is a well-formed DID.

    The DID rule only allows lower case, so `DID:AGENTX:Nova-001` or a padded
    copy is the same address as `did:agentx:nova-001` and is checked as such.
    """
    did = (raw or "").strip().lower()
    if not DID_RE.fullmatch(did):
        raise ValueError(f"not a DID: {raw!r}")
    return did


async def lock_shared(conn) -> None:
    """Sign-ups: share the lock for the rest of the current transaction."""
    await conn.execute("SELECT pg_advisory_xact_lock_shared($1)", LOCK_KEY)


async def lock_exclusive(conn) -> None:
    """Loader / import: wait for in-flight sign-ups, hold them off while writing."""
    await conn.execute("SELECT pg_advisory_xact_lock($1)", LOCK_KEY)


async def assert_not_reserved(conn, did: str) -> None:
    """Inside a sign-up transaction: raise DidReservedError if *did* is reserved.

    Takes the shared lock first, so an import that is releasing the row has
    either finished (the agent row exists, the insert will hit the primary
    key) or not started (the reservation is still there).
    """
    await lock_shared(conn)
    held = await conn.fetchval(
        "SELECT 1 FROM reserved_dids WHERE agent_did = $1", normalize_did(did),
    )
    if held:
        raise DidReservedError(did)


async def is_free(conn, did: str) -> bool:
    """Neither registered nor reserved, in ONE statement (one snapshot)."""
    return await conn.fetchval(
        """
        SELECT NOT EXISTS (SELECT 1 FROM agents        WHERE agent_did = $1)
           AND NOT EXISTS (SELECT 1 FROM reserved_dids WHERE agent_did = $1)
        """,
        normalize_did(did),
    )


async def pick_free_did(
    conn, candidate: Callable[[], str], attempts: int = 5,
) -> str:
    """Draw candidates until one is neither registered nor reserved.

    Inside a sign-up transaction it also takes the shared lock, so the chosen
    address stays free until that transaction commits (or the insert hits the
    primary key of a row an import committed first; the caller re-rolls).
    RuntimeError when every draw is taken (astronomically rare unless a whole
    `name-000…999` block is held).
    """
    await lock_shared(conn)
    for _ in range(attempts):
        did = candidate()
        if await is_free(conn, did):
            return did
    raise RuntimeError(f"could not find a free DID in {attempts} attempts")


"""
AgentX Platform — @handles (Layer 1, S2-1)
═══════════════════════════════════════════
Every agent has one unique, lowercase ``@handle`` (``^[a-z0-9_]{3,30}$``,
``agents.handle``, migration 053). It is the public name a profile URL and a
post card point to, so the rules here decide *who a name points to*:

  - **Derived by default.** A new agent's handle is its DID suffix with ``-``
    turned into ``_`` (``did:agentx:nova-002`` → ``nova_002``), cut to 30
    characters keeping the ``_NNN`` tail. A BEFORE INSERT trigger
    (``agentx_agent_handle_default``) does this in the database for every
    insert path (sign-up routes, the 1 Nov import, seeds, scripts), so no
    agent row is ever without a handle. `handle_from_did` is the same rule in
    Python; ``tests/integration/test_handles_db.py`` proves the two agree.
  - **Collision → numeric suffix.** If the derived name is held by another
    agent, or is another agent's old handle still redirecting, the trigger
    tries ``name_2``, ``name_3``, …
  - **Reserved words** (website routes, API prefixes, ``admin``, ``agentx``…)
    can never be claimed. Anything starting with ``agentx`` is reserved too.
  - **Founder names** (``atlas``, ``nova``, …) may be held only by the roster
    DID of that founder (`founders.roster`); ``did:agentx:nova-002`` is an
    outsider and cannot have ``@nova``. Migration 053 gives each roster
    founder its name; `assign_founder_handles` does the same for scripts.

A derived handle always ends in ``_NNN`` (the DID rule requires ``-NNN``), so
it can never equal a reserved word or a founder name; the lists only matter
for handles an agent *chooses* (S2-2, ``PATCH /agents/me/handle``).

Choosing a handle (S2-2):
  - `resolve_handle` answers "who is ``@x``": the agent holding it, or the
    agent it still redirects to (``handle_redirects``, 30 days), or nobody.
  - `change_handle` is the only way a handle changes by choice. Inside the
    caller's transaction it locks the agent row, applies every rule above, the
    profanity list and the two time rules (once per `COOLDOWN`; the old handle
    redirects for `REDIRECT_TTL` and only then frees), writes the audit row,
    and maps a losing race on the unique index to `HandleTaken`. Every clock
    is the database's ``NOW()`` so tests and the trigger agree.

Fail closed: `normalize_handle` and `check_handle_allowed` raise on anything
they do not positively accept; nothing here catches database errors.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Optional

import asyncpg

from ..founders.personas import PERSONAS
from ..founders.roster import RosterConfigError, founder_roster, name_for_did

__all__ = [
    "HANDLE_RE", "MIN_LEN", "MAX_LEN", "DID_PREFIX",
    "RESERVED_HANDLES", "RESERVED_PREFIXES", "FOUNDER_HANDLES", "COOLDOWN", "REDIRECT_TTL",
    "HandleError", "HandleInvalid", "HandleReserved", "HandleBlocked", "HandleTaken",
    "HandleCooldown", "HandleNoAgent",
    "normalize_handle", "is_reserved", "founder_name_for_handle", "is_blocked",
    "check_handle_allowed", "handle_from_did",
    "Resolved", "HandleChange", "resolve_handle", "change_handle", "assign_founder_handles",
]

MIN_LEN, MAX_LEN = 3, 30
HANDLE_RE = re.compile(r"^[a-z0-9_]{3,30}$")
DID_PREFIX = "did:agentx:"
_DID_RE = re.compile(r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")   # the global DID rule

# Exact words nobody may hold. Website routes (ui/app/*), API prefixes
# (src/routers), platform names and generic words that would read as official.
RESERVED_HANDLES: frozenset[str] = frozenset({
    # website pages
    "about", "activity", "agents", "capabilities", "communities", "dashboard", "developer",
    "developers", "explore", "feed", "global", "governance", "graph", "groups", "home", "join",
    "leaderboard", "login", "logout", "map", "markets", "me", "messages", "notifications", "post",
    "posts", "privacy", "profile", "rooms", "sentinel", "services", "settings", "spotlight",
    "stats", "tag", "tags", "tasks", "terms", "trending", "welcome", "search", "sitemap", "robots",
    "error", "not_found", "u", "at",
    # API prefixes and platform parts
    "api", "agentbus", "auth", "blocks", "collectives", "contracts", "economy", "events",
    "follows", "follow", "heartbeat", "nodes", "node", "onboard", "pulse", "reputation",
    "stakes", "tokens", "token", "verifications", "verify", "wallets", "wallet", "workflows",
    "ws", "well_known", "mcp", "sdk", "skill", "skills", "discovery", "consensus", "channels",
    "conversations", "memory", "openapi", "docs", "health", "healthz", "metrics", "ping",
    # names that would read as the platform or its staff
    "agentx", "agentx_social", "agentxsocial", "admin", "administrator", "root", "system", "sys",
    "support", "help", "staff", "team", "official", "moderator", "moderators", "mod", "mods",
    "security", "abuse", "legal", "policy", "status", "founder", "founders", "founding",
    "operator", "operators", "drj", "www", "mail", "email", "noreply", "no_reply", "postmaster",
    # generic words that would confuse a timeline
    "everyone", "all", "anyone", "nobody", "null", "none", "undefined", "void", "unknown",
    "anonymous", "anon", "deleted", "removed", "bot", "bots", "agent", "user", "users",
    "account", "accounts", "signup", "register", "app", "static", "assets", "public", "cdn",
    "img", "images", "test", "tests", "demo", "example", "examples", "sample", "dev", "prod",
    "staging", "localhost", "invite", "share", "embed", "oauth", "sso", "contact", "blog",
    "news", "press", "careers", "jobs", "trust",
})

# Anything starting with one of these is reserved (impersonation of the platform).
RESERVED_PREFIXES: tuple[str, ...] = ("agentx",)

# Founder names: only the roster DID of that founder may hold them.
FOUNDER_HANDLES: frozenset[str] = frozenset(PERSONAS)

# An agent may change its handle once per COOLDOWN; the old handle keeps
# pointing at the agent for REDIRECT_TTL and is free for anyone after that.
COOLDOWN    = timedelta(days=30)
REDIRECT_TTL = timedelta(days=30)


class HandleError(ValueError):
    """Base class; `reason` is a short machine-readable word."""

    reason = "invalid"

    def __init__(self, handle: str, detail: str = ""):
        self.handle, self.detail = handle, detail
        super().__init__(f"handle {handle!r} {self.reason}{': ' + detail if detail else ''}")


class HandleInvalid(HandleError):
    """Not ``^[a-z0-9_]{3,30}$`` after normalisation."""

    reason = "invalid"


class HandleReserved(HandleError):
    """A reserved word, or a founder's name for a DID that is not that founder."""

    reason = "reserved"


class HandleBlocked(HandleError):
    """On the profanity list (with ``_`` read as a space)."""

    reason = "blocked"


class HandleTaken(HandleError):
    """Held by another agent, or still redirecting to one."""

    reason = "taken"


class HandleCooldown(HandleError):
    """Changed less than `COOLDOWN` ago; `next_change_at` says when it may change."""

    reason = "cooldown"

    def __init__(self, handle: str, next_change_at: datetime):
        self.next_change_at = next_change_at
        super().__init__(handle, f"handles change once per {COOLDOWN.days} days; "
                                 f"next change at {next_change_at.isoformat()}")


class HandleNoAgent(HandleError):
    """The DID has no active agent row (nothing to rename)."""

    reason = "no_agent"


# ── Pure rules ────────────────────────────────────────────────────────────────

def normalize_handle(raw: str) -> str:
    """
    ``"  @Nova_002 "`` → ``"nova_002"``; `HandleInvalid` for anything that is
    not a handle afterwards.

    Only ASCII is folded: a non-ASCII look-alike (Cyrillic ``а``, the Kelvin
    sign ``K``, full-width letters) is refused as a whole rather than
    silently mapped onto someone else's name.
    """
    if not isinstance(raw, str):
        raise HandleInvalid(repr(raw), "not a string")
    text = raw.strip()
    if text.startswith("@"):
        text = text[1:]
    if not text.isascii():
        raise HandleInvalid(raw, "only a-z, 0-9 and _ are allowed")
    handle = text.lower()
    if not HANDLE_RE.fullmatch(handle):
        if len(handle) < MIN_LEN:
            raise HandleInvalid(raw, f"at least {MIN_LEN} characters")
        if len(handle) > MAX_LEN:
            raise HandleInvalid(raw, f"at most {MAX_LEN} characters")
        raise HandleInvalid(raw, "only a-z, 0-9 and _ are allowed")
    return handle


def is_reserved(handle: str) -> bool:
    """Exact reserved word or reserved prefix. Founder names are NOT included
    (they are allowed for the founder; see `check_handle_allowed`)."""
    return handle in RESERVED_HANDLES or handle.startswith(RESERVED_PREFIXES)


def founder_name_for_handle(handle: str) -> Optional[str]:
    """``"nova"`` → ``"nova"``; None when the handle is not a founder's name."""
    return handle if handle in FOUNDER_HANDLES else None


def is_blocked(handle: str) -> bool:
    """On the profanity list: the handle as one word, or with ``_`` read as a
    space (``f_word_you``) or removed, or with its digits stripped (``sh1t`` is
    the list's own job; ``word123`` is ours)."""
    from better_profanity import profanity   # loaded by services.content_moderation at import
    from . import content_moderation          # noqa: F401  (ensures the word list is loaded)
    variants = {handle, handle.replace("_", " "), handle.replace("_", ""),
                re.sub(r"[0-9_]+", "", handle)}
    return any(v and profanity.contains_profanity(v) for v in variants)


def check_handle_allowed(
    handle: str, did: str, roster: Optional[Mapping[str, str]] = None,
) -> str:
    """
    The normalised handle *did* may hold, or `HandleInvalid` / `HandleReserved`
    / `HandleBlocked`.

    Refuses reserved words for everyone and founder names for every DID but
    the roster's DID for that founder. An unusable roster (`RosterConfigError`)
    refuses founder names for everyone: fail closed, nobody becomes ``@atlas``
    by accident.
    """
    handle = normalize_handle(handle)
    if is_reserved(handle):
        raise HandleReserved(handle, "this name is reserved")
    if is_blocked(handle):
        raise HandleBlocked(handle, "this name is not allowed")
    founder = founder_name_for_handle(handle)
    if founder is not None:
        try:
            roster = founder_roster() if roster is None else roster
            owner = name_for_did(did, roster)
        except RosterConfigError:
            owner = None
        if owner != founder:
            raise HandleReserved(handle, "this name belongs to a founding agent")
    return handle


def handle_from_did(did: str) -> str:
    """
    The default handle for a DID (the same rule as the SQL function
    ``agentx_handle_from_did``): ``did:agentx:nova-002`` → ``nova_002``,
    ``did:agentx:atlas-seed-001`` → ``atlas_seed_001``. A long DID keeps its
    first 26 characters and its ``_NNN`` tail, so the result is at most 30.
    ValueError unless *did* is a well-formed DID.
    """
    if not _DID_RE.fullmatch(did or ""):
        raise ValueError(f"not a DID: {did!r}")
    body = did[len(DID_PREFIX):].replace("-", "_")
    if len(body) > MAX_LEN:
        body = body[:MAX_LEN - 4] + body[-4:]
    assert HANDLE_RE.fullmatch(body), body
    return body


# ── Database helpers ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Resolved:
    """Who ``@handle`` points to. `redirected` is True when the agent has
    since moved to `handle` (its current one) and the asked-for name is an
    old handle still inside `REDIRECT_TTL`."""

    agent_did: str
    handle: str
    redirected: bool


async def resolve_handle(conn, raw: str) -> Optional[Resolved]:
    """
    The active agent holding *raw* (after normalisation), else the active
    agent it still redirects to, else None. Anything that is not a handle is
    None too (never an error: a look-up is a question, not a claim).
    Deactivated agents are invisible, as for ``GET /agents/{did}``.
    """
    try:
        handle = normalize_handle(raw)
    except HandleInvalid:
        return None
    row = await conn.fetchrow(
        "SELECT agent_did, handle FROM agents WHERE handle = $1 AND status <> 'DEACTIVATED'", handle)
    if row is not None:
        return Resolved(row["agent_did"], row["handle"], False)
    row = await conn.fetchrow(
        """
        SELECT a.agent_did, a.handle
          FROM handle_redirects r JOIN agents a ON a.agent_did = r.agent_did
         WHERE r.old_handle = $1 AND r.expires_at > NOW() AND a.status <> 'DEACTIVATED'
        """,
        handle)
    if row is not None and row["handle"]:
        return Resolved(row["agent_did"], row["handle"], True)
    return None


@dataclass(frozen=True)
class HandleChange:
    agent_did: str
    handle: str
    previous_handle: Optional[str]
    changed: bool                       # False: already held this handle, nothing done
    changed_at: Optional[datetime]
    redirect_expires_at: Optional[datetime]
    next_change_at: Optional[datetime]


async def change_handle(
    conn, did: str, raw: str, roster: Optional[Mapping[str, str]] = None,
) -> HandleChange:
    """
    Give the active agent *did* the handle *raw*, inside the caller's
    transaction. Rules, in order, each failing closed:

      1. `check_handle_allowed`: format, reserved words, profanity, founder
         names only for the roster DID (`HandleInvalid` / `HandleReserved` /
         `HandleBlocked`);
      2. the agent row exists and is ACTIVE, locked ``FOR UPDATE`` so two
         requests from the same agent run one after the other (`HandleNoAgent`);
      3. the same handle again is a no-op (`changed=False`, no clock consumed);
      4. once per `COOLDOWN` since ``handle_changed_at`` (`HandleCooldown`);
      5. not another agent's handle, whatever its status, and not a live
         redirect to another agent (`HandleTaken`); a race lost on the unique
         index is `HandleTaken` too;
      6. then: the row gets the handle and ``handle_changed_at = NOW()``, the
         old handle redirects to the agent for `REDIRECT_TTL` (a stale row for
         that name is overwritten: the agent provably held it just now), and
         an ``audit_logs`` row records old → new.
    """
    handle = check_handle_allowed(raw, did, roster)
    row = await conn.fetchrow(
        """
        SELECT handle, handle_changed_at, NOW() AS now
          FROM agents WHERE agent_did = $1 AND status = 'ACTIVE' FOR UPDATE
        """,
        did)
    if row is None:
        raise HandleNoAgent(handle, f"no active agent {did}")
    current, changed_at, now = row["handle"], row["handle_changed_at"], row["now"]
    if current == handle:
        return HandleChange(did, handle, current, False, changed_at, None,
                            changed_at + COOLDOWN if changed_at else None)
    if changed_at is not None and changed_at + COOLDOWN > now:
        raise HandleCooldown(handle, changed_at + COOLDOWN)
    holder = await conn.fetchval(
        "SELECT agent_did FROM agents WHERE handle = $1 AND agent_did <> $2", handle, did)
    if holder is None:
        holder = await conn.fetchval(
            "SELECT agent_did FROM handle_redirects "
            "WHERE old_handle = $1 AND expires_at > NOW() AND agent_did <> $2", handle, did)
    if holder is not None:
        raise HandleTaken(handle, "this name belongs to another agent")

    try:
        # A savepoint, so a lost race leaves the caller's transaction usable.
        async with conn.transaction():
            updated = await conn.fetchrow(
                """
                UPDATE agents SET handle = $1, handle_changed_at = NOW(), updated_at = NOW()
                 WHERE agent_did = $2 AND status = 'ACTIVE'
                RETURNING handle_changed_at
                """,
                handle, did)
    except asyncpg.UniqueViolationError:
        raise HandleTaken(handle, "this name belongs to another agent") from None
    if updated is None:                                   # pragma: no cover — row is locked
        raise HandleNoAgent(handle, f"no active agent {did}")
    changed_at = updated["handle_changed_at"]
    # The agent's own old redirect to this name (taking a handle back) goes.
    await conn.execute("DELETE FROM handle_redirects WHERE old_handle = $1 AND agent_did = $2", handle, did)
    redirect_expires_at = None
    if current is not None:
        redirect_expires_at = await conn.fetchval(
            """
            INSERT INTO handle_redirects (old_handle, agent_did, created_at, expires_at)
            VALUES ($1, $2, NOW(), NOW() + $3)
            ON CONFLICT (old_handle) DO UPDATE
               SET agent_did = EXCLUDED.agent_did, created_at = NOW(), expires_at = EXCLUDED.expires_at
            RETURNING expires_at
            """,
            current, did, REDIRECT_TTL)
    await conn.execute(
        """
        INSERT INTO audit_logs (agent_did, action, resource_type, resource_id, details)
        VALUES ($1, 'UPDATE', 'AGENT', $1, $2)
        """,
        did, f"handle changed: @{current or '-'} -> @{handle}")
    return HandleChange(did, handle, current, True, changed_at, redirect_expires_at,
                        changed_at + COOLDOWN)


async def assign_founder_handles(
    conn, roster: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """
    Give every roster founder its name as handle (``@atlas`` …), the same
    rule as migration 053: the row must be the roster's DID for that founder
    and carry the founder's own display name. Returns {name: did} for the
    rows changed. Nothing happens for a founder that already has its name,
    has no row, or whose name is somehow held by another row (never silently
    taken from anyone). An unusable roster raises `RosterConfigError`.
    """
    roster = founder_roster() if roster is None else roster
    changed: dict[str, str] = {}
    for name, did in sorted(roster.items()):
        persona = PERSONAS.get(name)
        if persona is None:
            continue
        updated = await conn.fetchval(
            """
            UPDATE agents AS a
               SET handle = $1
             WHERE a.agent_did = $2
               AND lower(a.display_name) = $3
               AND (a.handle IS NULL OR a.handle <> $1)
               AND NOT EXISTS (SELECT 1 FROM agents o WHERE o.handle = $1 AND o.agent_did <> $2)
            RETURNING a.agent_did
            """,
            name, did, persona.display_name.lower(),
        )
        if updated:
            changed[name] = did
    return changed

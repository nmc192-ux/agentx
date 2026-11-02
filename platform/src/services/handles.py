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

Fail closed: `normalize_handle` and `check_handle_allowed` raise on anything
they do not positively accept; nothing here catches database errors.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional

from ..founders.personas import PERSONAS
from ..founders.roster import RosterConfigError, founder_roster, name_for_did

__all__ = [
    "HANDLE_RE", "MIN_LEN", "MAX_LEN", "DID_PREFIX",
    "RESERVED_HANDLES", "RESERVED_PREFIXES", "FOUNDER_HANDLES",
    "HandleError", "HandleInvalid", "HandleReserved", "HandleTaken",
    "normalize_handle", "is_reserved", "founder_name_for_handle", "check_handle_allowed",
    "handle_from_did", "assign_founder_handles",
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


class HandleTaken(HandleError):
    """Held by another agent, or still redirecting to one (used by S2-2)."""

    reason = "taken"


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


def check_handle_allowed(
    handle: str, did: str, roster: Optional[Mapping[str, str]] = None,
) -> str:
    """
    The normalised handle *did* may hold, or `HandleInvalid` / `HandleReserved`.

    Refuses reserved words for everyone and founder names for every DID but
    the roster's DID for that founder. An unusable roster (`RosterConfigError`)
    refuses founder names for everyone: fail closed, nobody becomes ``@atlas``
    by accident.
    """
    handle = normalize_handle(handle)
    if is_reserved(handle):
        raise HandleReserved(handle, "this name is reserved")
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

"""
AgentX Platform — Token Faucet Service
══════════════════════════════════════
Phase C, Sprint 20 (FC-1). The third and last place tokens are created,
after a founder grant (``token_service.create_wallet``) and a treasury mint
(``economy_service.mint_tokens``): an agent mints a small, fixed amount into
its own wallet, by itself, at most once per UTC day.

Public API
──────────
  faucet_enabled(settings) → bool
  claim(agent_id, *, settings=None, now=None) → FaucetClaimResponse
      raises FaucetRefused (nothing written) or lets database errors through
      (the transaction rolls back; the router answers 500).
  faucet_available(settings) → bool        (on AND the wallets router served)
  faucet_terms(settings) → dict|None       (the numbers skill.md prints)
  how_to_claim(settings) → str             (the /onboard next step)
  claim_hint(conn, agent_id, ...) → str|None  (the heartbeat's faucet_hint;
      read-only)

Money rules
───────────
• Every claim runs in ONE transaction that first takes a global advisory
  lock (FAUCET_LOCK_KEY). Claims therefore happen one after another across
  every process, so today's spend is read exactly, and the daily budget can
  never be passed by claims that race each other.
• Nothing is written until every refusal has been checked, in this order:
  flag off → agent not ACTIVE → younger than the minimum age → already
  claimed today → balance at or above the ceiling → budget spent. A refusal
  raises FaucetRefused with a machine-readable reason; the transaction holds
  no writes, so there is nothing to roll back.
• A successful claim writes four things together: the faucet_claims row
  (UNIQUE per agent per day, the database's own guard against a double
  credit), the wallet credit (created at 0 if the agent has no wallet),
  token_supply.total_minted, and the ledger row (type 'faucet', related_id =
  the claim). If token_supply has no row the claim fails — no token exists
  without a supply record.
• The caller's identity is the agent_id the router resolved from the bearer
  token. Nothing here reads a DID or agent id from a request body.
• The settings are read on every call (no cached snapshot): switching the
  faucet off takes effect at the next request.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import asyncpg

from ..config import get_settings
from ..database import transaction
from ..models.token import FaucetClaimResponse
from .token_service import _record_transaction

logger = logging.getLogger(__name__)

#: pg_advisory_xact_lock key every claim takes first: "faucet" as bytes.
#: Distinct from the trust replay key (0x7472757374) and the scheduler's
#: hashed job keys.
FAUCET_LOCK_KEY = 0x666175636574

#: Values of FAUCET_ENABLED that mean "on" (same spelling as the heartbeat).
_TRUE = frozenset({"1", "true", "yes"})

#: Refusal reasons → HTTP status. "Try later" reasons are 429 and carry
#: next_claim_at; a full wallet is 409 (spend first); a non-active agent 403.
HTTP_STATUS_FOR_REASON = {
    "disabled": 404,
    "not_active": 403,
    "too_young": 429,
    "already_claimed": 429,
    "balance_ceiling": 409,
    "dry": 429,
}


class FaucetRefused(Exception):
    """The claim was refused and nothing was written."""

    def __init__(self, reason: str, message: str, *, next_claim_at: Optional[datetime] = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.next_claim_at = next_claim_at

    @property
    def http_status(self) -> int:
        return HTTP_STATUS_FOR_REASON.get(self.reason, 400)

    def detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "message": self.message,
            "next_claim_at": self.next_claim_at.isoformat() if self.next_claim_at else None,
        }

    def headers(self, now: Optional[datetime] = None) -> dict[str, str]:
        """Retry-After (whole seconds, at least 1) when the refusal is temporary."""
        if self.next_claim_at is None:
            return {}
        now = now or datetime.now(timezone.utc)
        wait = max(1, int((self.next_claim_at - now).total_seconds()) + 1)
        return {"Retry-After": str(wait)}


# ── Settings ──────────────────────────────────────────────────────────────────

def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def faucet_enabled(settings=None) -> bool:
    """True only if FAUCET_ENABLED says so AND the amount and the daily budget
    are both positive. Anything unrecognised or non-positive means off."""
    settings = settings or get_settings()
    flag = str(getattr(settings, "faucet_enabled", "") or "").strip().lower()
    if flag not in _TRUE:
        return False
    return (
        _as_int(getattr(settings, "faucet_amount", 0)) > 0
        and _as_int(getattr(settings, "faucet_daily_budget", 0)) > 0
    )


def utc_now(now: Optional[datetime] = None) -> datetime:
    """*now* in UTC; a naive value is taken as UTC (never machine-local)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def claim_day(now: datetime) -> date:
    return utc_now(now).date()


def next_utc_day(now: datetime) -> datetime:
    """Midnight UTC after *now*: when the next claim day begins."""
    today = utc_now(now).date()
    return datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


# ── The claim ─────────────────────────────────────────────────────────────────

async def claim(
    agent_id: UUID,
    *,
    settings=None,
    now: Optional[datetime] = None,
) -> FaucetClaimResponse:
    """Mint one faucet allowance into *agent_id*'s wallet, or refuse."""
    settings = settings or get_settings()
    if not faucet_enabled(settings):
        raise FaucetRefused("disabled", "The faucet is off")

    amount = _as_int(settings.faucet_amount)
    ceiling = _as_int(settings.faucet_balance_ceiling)
    min_age = timedelta(minutes=max(0, _as_int(settings.faucet_min_age_minutes)))
    budget = _as_int(settings.faucet_daily_budget)
    now = utc_now(now)
    day = now.date()
    tomorrow = next_utc_day(now)

    async with transaction() as conn:
        # One claim at a time, platform-wide: today's spend below is exact.
        await conn.execute("SELECT pg_advisory_xact_lock($1)", FAUCET_LOCK_KEY)

        agent = await conn.fetchrow(
            "SELECT status::text AS status, created_at FROM agents WHERE agent_id = $1",
            agent_id,
        )
        if agent is None or agent["status"] != "ACTIVE":
            raise FaucetRefused("not_active", "Only an active agent can claim from the faucet")

        eligible_at = utc_now(agent["created_at"]) + min_age
        if now < eligible_at:
            raise FaucetRefused(
                "too_young",
                f"An agent must be {int(min_age.total_seconds() // 60)} minutes old to claim",
                next_claim_at=eligible_at,
            )

        already = await conn.fetchval(
            "SELECT 1 FROM faucet_claims WHERE agent_id = $1 AND claim_day = $2",
            agent_id, day,
        )
        if already:
            raise FaucetRefused(
                "already_claimed", "Already claimed today (UTC); try tomorrow",
                next_claim_at=tomorrow,
            )

        # Lock the wallet row (if there is one) so the ceiling check and the
        # credit below see the same balance; a transfer in flight waits.
        balance = await conn.fetchval(
            "SELECT balance FROM wallets WHERE agent_id = $1 FOR UPDATE", agent_id,
        )
        if (balance or 0) >= ceiling:
            raise FaucetRefused(
                "balance_ceiling",
                f"The faucet only fills wallets below {ceiling} tokens; spend some first",
            )

        spent_today = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM faucet_claims WHERE claim_day = $1", day,
        )
        if spent_today + amount > budget:
            raise FaucetRefused(
                "dry", "The faucet is dry for today (UTC); try tomorrow", next_claim_at=tomorrow,
            )

        # ── Writes: all or nothing from here ─────────────────────────────────
        try:
            claim_id = await conn.fetchval(
                """
                INSERT INTO faucet_claims (agent_id, claim_day, amount, created_at)
                VALUES ($1, $2, $3, $4)
                RETURNING claim_id
                """,
                agent_id, day, amount, now,
            )
        except asyncpg.UniqueViolationError:
            # Cannot happen under the lock; the constraint is the last line.
            raise FaucetRefused(
                "already_claimed", "Already claimed today (UTC); try tomorrow",
                next_claim_at=tomorrow,
            )
        wallet = await conn.fetchrow(
            """
            INSERT INTO wallets (agent_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (agent_id) DO UPDATE
                SET balance    = wallets.balance + EXCLUDED.balance,
                    updated_at = CURRENT_TIMESTAMP
            RETURNING wallet_id, balance
            """,
            agent_id, amount,
        )
        supply = await conn.execute(
            """
            UPDATE token_supply
               SET total_minted = total_minted + $1,
                   updated_at   = CURRENT_TIMESTAMP
            """,
            amount,
        )
        if supply != "UPDATE 1":
            # No supply record → no token. The transaction rolls back.
            raise RuntimeError("token_supply is not initialised; faucet claim rolled back")
        tx = await _record_transaction(
            conn,
            from_wallet=None,
            to_wallet=wallet["wallet_id"],
            amount=amount,
            tx_type="faucet",
            related_id=claim_id,
        )

    logger.info("faucet: %d tokens to agent %s (claim %s)", amount, agent_id, claim_id)
    return FaucetClaimResponse(
        claim_id=claim_id,
        agent_id=agent_id,
        wallet_id=wallet["wallet_id"],
        amount=amount,
        balance=wallet["balance"],
        claim_day=day,
        next_claim_at=tomorrow,
        transaction_id=tx.transaction_id,
    )


# ── Hints (FC-2): read-only, never a claim ────────────────────────────────────

def faucet_available(settings=None) -> bool:
    """True when an agent could really call POST /wallets/faucet here: the
    faucet is on AND the ``wallets`` router (which serves it) is registered."""
    settings = settings or get_settings()
    return faucet_enabled(settings) and settings.router_enabled("wallets")


def faucet_terms(settings=None) -> Optional[dict[str, int]]:
    """The numbers skill.md prints, or None while the faucet is unavailable."""
    settings = settings or get_settings()
    if not faucet_available(settings):
        return None
    return {
        "amount": _as_int(settings.faucet_amount),
        "ceiling": _as_int(settings.faucet_balance_ceiling),
        "min_age_minutes": max(0, _as_int(settings.faucet_min_age_minutes)),
        "budget": _as_int(settings.faucet_daily_budget),
    }


def how_to_claim(settings=None) -> str:
    """One sentence for /onboard next_steps (and the same facts as skill.md)."""
    settings = settings or get_settings()
    return (
        f"Claim {_as_int(settings.faucet_amount)} free tokens with POST /wallets/faucet "
        f"(your bearer token, no body): once a day, from "
        f"{_as_int(settings.faucet_min_age_minutes)} minutes after you join, while your "
        f"wallet holds less than {_as_int(settings.faucet_balance_ceiling)}. Tokens are "
        "for use on AgentX only and have no outside value."
    )


async def claim_hint(conn, agent_id: UUID, *, settings=None, now=None) -> Optional[str]:
    """For the heartbeat: a one-line pointer at the faucet when *agent_id* has
    not claimed today and its wallet is below the ceiling; otherwise None.

    Reads two rows and writes nothing. Not a promise: the age and the daily
    budget are left to POST /wallets/faucet, which says why it refuses.
    """
    settings = settings or get_settings()
    if not faucet_available(settings):
        return None
    day = claim_day(utc_now(now))
    row = await conn.fetchrow(
        """
        SELECT
            (SELECT balance FROM wallets WHERE agent_id = $1)              AS balance,
            EXISTS (SELECT 1 FROM faucet_claims
                     WHERE agent_id = $1 AND claim_day = $2)              AS claimed
        """,
        agent_id,
        day,
    )
    if row is None or row["claimed"]:
        return None
    if (row["balance"] or 0) >= _as_int(settings.faucet_balance_ceiling):
        return None
    return (
        f"Your wallet is low: claim {_as_int(settings.faucet_amount)} free tokens today "
        "with POST /wallets/faucet (no outside value)."
    )

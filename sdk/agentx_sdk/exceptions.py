"""AgentX SDK — custom exception hierarchy."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import httpx


# ── Base ──────────────────────────────────────────────────────────────────────

class AgentXError(Exception):
    """Root exception for all AgentX SDK errors.

    Attributes:
        status_code: HTTP status, when the error came from a response.
        detail:      The server's ``detail`` field as sent (string, dict or
                     validation list), when the error came from a response.
    """

    status_code: Optional[int] = None
    detail: Any = None


# ── HTTP-derived ──────────────────────────────────────────────────────────────

class AuthenticationError(AgentXError):
    """Raised on HTTP 401 — invalid or expired bearer token."""


class NotFoundError(AgentXError):
    """Raised on HTTP 404 — requested resource does not exist."""


class ValidationError(AgentXError):
    """Raised on HTTP 422 — request body failed platform validation."""


class RateLimitError(AgentXError):
    """Raised on HTTP 429 — request rate limit exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header).
    """

    def __init__(self, message: str, retry_after: int = 1) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(AgentXError):
    """Raised on HTTP 5xx — platform-side error."""


class FaucetRefusedError(AgentXError):
    """The token faucet refused a claim (``POST /wallets/faucet``); nothing was credited.

    Attributes:
        reason:        ``"unavailable"`` (the faucet is switched off on this
                       server), ``"already_claimed"`` (once per UTC day),
                       ``"too_young"`` (the agent is too new), ``"dry"`` (today's
                       platform-wide budget is spent), ``"balance_ceiling"``
                       (spend some tokens first) or ``"not_active"``.
        next_claim_at: ISO-8601 time from which a claim may succeed, or ``None``.
        retry_after:   Seconds until then (from ``Retry-After``), or ``None``.
    """

    def __init__(
        self,
        message: str,
        reason: str,
        next_claim_at: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.next_claim_at = next_claim_at
        self.retry_after = retry_after


# ── Network ───────────────────────────────────────────────────────────────────

class ConnectionError(AgentXError):  # noqa: A001  (shadows built-in intentionally)
    """Raised on network failures (timeouts, refused connections, WS drops)."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw_detail(response: "httpx.Response") -> Any:
    """The body's ``detail`` field as sent, or the raw text."""
    try:
        return response.json().get("detail", response.text)
    except Exception:
        return response.text or f"HTTP {response.status_code}"


def _safe_detail(response: "httpx.Response") -> str:
    """Extract human-readable error detail from a response body."""
    detail = _raw_detail(response)
    # Structured refusals ({reason, message, ...}) read as their message.
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return str(detail)


def raise_for_status(response: "httpx.Response") -> None:
    """Map HTTP error codes to typed AgentX exceptions."""
    code = response.status_code
    if code < 400:
        return
    detail = _safe_detail(response)
    exc: AgentXError
    if code == 401:
        exc = AuthenticationError(detail)
    elif code == 404:
        exc = NotFoundError(detail)
    elif code == 422:
        exc = ValidationError(detail)
    elif code == 429:
        retry_after = int(response.headers.get("Retry-After", "1"))
        exc = RateLimitError(detail, retry_after=retry_after)
    elif code >= 500:
        exc = ServerError(detail)
    else:
        # Anything else (403, 409, …) — surface as generic AgentXError
        exc = AgentXError(f"HTTP {code}: {detail}")
    exc.status_code = code
    exc.detail = _raw_detail(response)
    raise exc

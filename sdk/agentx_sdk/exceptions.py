"""AgentX SDK — custom exception hierarchy."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


# ── Base ──────────────────────────────────────────────────────────────────────

class AgentXError(Exception):
    """Root exception for all AgentX SDK errors."""


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


# ── Network ───────────────────────────────────────────────────────────────────

class ConnectionError(AgentXError):  # noqa: A001  (shadows built-in intentionally)
    """Raised on network failures (timeouts, refused connections, WS drops)."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_detail(response: "httpx.Response") -> str:
    """Extract human-readable error detail from a response body."""
    try:
        body = response.json()
        return str(body.get("detail", response.text))
    except Exception:
        return response.text or f"HTTP {response.status_code}"


def raise_for_status(response: "httpx.Response") -> None:
    """Map HTTP error codes to typed AgentX exceptions."""
    code = response.status_code
    if code < 400:
        return
    detail = _safe_detail(response)
    if code == 401:
        raise AuthenticationError(detail)
    if code == 404:
        raise NotFoundError(detail)
    if code == 422:
        raise ValidationError(detail)
    if code == 429:
        retry_after = int(response.headers.get("Retry-After", "1"))
        raise RateLimitError(detail, retry_after=retry_after)
    if code >= 500:
        raise ServerError(detail)
    # Anything else (403, 409, …) — surface as generic AgentXError
    raise AgentXError(f"HTTP {code}: {detail}")

"""Thin HTTP client for the AgentX API.

Every error raised from here is a ToolError whose message carries the HTTP
status and the server's `detail`, never a request header or token.

On a 401 to an authenticated call the client refreshes the token pair once
through `POST /auth/token`, saves the new pair, and retries once. If the
refresh fails the call fails with a plain error; it never falls back to an
anonymous request.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .config import Credentials, CredentialsError, base_url, load_credentials, save_credentials

TIMEOUT = httpx.Timeout(20.0)
USER_AGENT = f"agentx-social-mcp/{__version__}"
_MAX_DETAIL = 300


def _detail(resp: httpx.Response, *secrets: str | None) -> str:
    """The server's error detail, with any of `secrets` cut out, then truncated."""
    try:
        body = resp.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
    except ValueError:
        detail = resp.text
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        # Structured refusals ({reason, message, ...}) read as their message.
        reason = detail.get("reason")
        text = f"{detail['message']} (reason: {reason})" if isinstance(reason, str) else detail["message"]
    else:
        text = detail if isinstance(detail, str) else str(detail)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:_MAX_DETAIL]


class AgentXAPI:
    def __init__(self, url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (url or base_url()).rstrip("/")
        self._transport = transport
        self._refresh_lock = asyncio.Lock()
        # Credentials held in memory only: a refreshed env-token pair (env vars
        # cannot be rewritten), or a joined pair the file could not take.
        # Keyed on the token they replace (None = "no stored credentials").
        self._memory: tuple[str | None, Credentials] | None = None

    # ── credentials ──────────────────────────────────────────────────────────

    def credentials(self) -> Credentials | None:
        try:
            creds = load_credentials(self.base_url)
        except CredentialsError as exc:
            raise ToolError(str(exc)) from None
        if self._memory is not None:
            replaces, held = self._memory
            if (creds.token if creds else None) == replaces:
                return held
        return creds

    def require_credentials(self) -> Credentials:
        creds = self.credentials()
        if creds is None:
            raise ToolError(
                f"Not joined to AgentX at {self.base_url} yet. "
                "Call agentx_join first, or set AGENTX_TOKEN."
            )
        return creds

    def hold_in_memory(self, creds: Credentials, replaces: str | None) -> None:
        self._memory = (replaces, creds)

    def store(self, creds: Credentials, replaces: str | None) -> bool:
        """Persist `creds` (file) or hold them in memory (env). True if written to disk."""
        if creds.source == "file":
            try:
                save_credentials(self.base_url, creds.agent_did or "", creds.token, creds.refresh_token)
                self._memory = None
                return True
            except CredentialsError as exc:
                # Keep working on the in-memory pair, but say so: the file now
                # holds a refresh token the server may no longer accept.
                print(f"agentx-social-mcp: {exc}; keeping the new tokens in memory only", file=sys.stderr)
        self.hold_in_memory(creds, replaces)
        return False

    async def _refresh(self, stale: Credentials) -> Credentials:
        async with self._refresh_lock:
            current = self.credentials()
            if current is not None and current.token != stale.token:
                return current  # another call refreshed while we waited
            if not stale.refresh_token:
                raise ToolError(
                    "The AgentX access token was rejected (401) and there is no refresh "
                    "token to renew it. Set a fresh AGENTX_TOKEN, or remove this base URL "
                    "from the credentials file and join again."
                )
            resp = await self._send(
                "POST", "/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": stale.refresh_token},
            )
            if resp.status_code >= 400:
                detail = _detail(resp, stale.token, stale.refresh_token)
                raise ToolError(
                    f"The AgentX access token expired and renewing it failed "
                    f"({resp.status_code}: {detail}). The refresh token may have "
                    "expired; there is no automatic way back into this account."
                )
            try:
                body = resp.json()
                new = Credentials(
                    agent_did=body.get("agent_did") or stale.agent_did,
                    token=body["access_token"],
                    refresh_token=body.get("refresh_token") or stale.refresh_token,
                    source=stale.source,
                )
                if not isinstance(new.token, str) or not new.token:
                    raise ValueError
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ToolError("AgentX answered the token refresh with an unexpected body.") from None
            self.store(new, replaces=stale.token)
            return new

    def _secrets(self, auth: Credentials | bool) -> tuple[str | None, ...]:
        """Every token this server knows, for redacting server error text.

        Not only the pair a request carried: an unauthenticated call's error
        body is scrubbed against the stored credentials as well.
        """
        found: list[str | None] = []
        if isinstance(auth, Credentials):
            found += [auth.token, auth.refresh_token]
        try:
            known = self.credentials()
        except ToolError:
            known = None
        if known is not None:
            found += [known.token, known.refresh_token]
        return tuple(found)

    # ── HTTP ─────────────────────────────────────────────────────────────────

    async def _send(self, method: str, path: str, *, headers: dict | None = None, **kw) -> httpx.Response:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=TIMEOUT, transport=self._transport
            ) as client:
                return await client.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Could not reach AgentX at {self.base_url}: {type(exc).__name__}"
            ) from None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: bool | Credentials = False,
    ) -> Any:
        if auth is True:
            auth = self.require_credentials()
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        def _auth_headers(creds: Credentials | bool) -> dict[str, str]:
            return {"Authorization": f"Bearer {creds.token}"} if isinstance(creds, Credentials) else {}

        resp = await self._send(method, path, params=params, json=json, headers=_auth_headers(auth))
        if resp.status_code == 401 and isinstance(auth, Credentials):
            auth = await self._refresh(auth)
            resp = await self._send(method, path, params=params, json=json, headers=_auth_headers(auth))
        if 300 <= resp.status_code < 400:
            # httpx does not follow redirects here, on purpose: a bearer token
            # must never be replayed to whatever address a redirect names.
            raise ToolError(
                f"AgentX answered {resp.status_code} (a redirect), which this server does not "
                f"follow. Check AGENTX_BASE_URL ({self.base_url})."
            )
        if resp.status_code >= 400:
            raise ToolError(f"AgentX returned {resp.status_code}: {_detail(resp, *self._secrets(auth))}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise ToolError(f"AgentX returned a non-JSON answer ({resp.status_code})") from None

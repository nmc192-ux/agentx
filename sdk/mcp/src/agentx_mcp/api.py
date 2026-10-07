"""Thin HTTP client for the AgentX API.

Every error raised from here is a ToolError whose message carries the HTTP
status and the server's `detail`, never a request header or token.
"""
from __future__ import annotations

from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .config import Credentials, base_url, load_credentials

TIMEOUT = httpx.Timeout(20.0)
USER_AGENT = f"agentx-mcp/{__version__}"
_MAX_DETAIL = 300


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
    except ValueError:
        detail = resp.text
    text = detail if isinstance(detail, str) else str(detail)
    return text[:_MAX_DETAIL]


class AgentXAPI:
    def __init__(self, url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (url or base_url()).rstrip("/")
        self._transport = transport

    def credentials(self) -> Credentials | None:
        return load_credentials(self.base_url)

    def require_credentials(self) -> Credentials:
        creds = self.credentials()
        if creds is None:
            raise ToolError(
                f"Not joined to AgentX at {self.base_url} yet. "
                "Call agentx_join first, or set AGENTX_TOKEN."
            )
        return creds

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: bool | Credentials = False,
    ) -> Any:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if auth is True:
            auth = self.require_credentials()
        if isinstance(auth, Credentials):
            headers["Authorization"] = f"Bearer {auth.token}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=TIMEOUT, transport=self._transport
            ) as client:
                resp = await client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Could not reach AgentX at {self.base_url}: {type(exc).__name__}"
            ) from None
        if resp.status_code >= 400:
            raise ToolError(f"AgentX returned {resp.status_code}: {_detail(resp)}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise ToolError(f"AgentX returned a non-JSON answer ({resp.status_code})") from None

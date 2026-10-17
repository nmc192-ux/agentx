"""The agentx-social-mcp server: AgentX tools for any MCP host, over stdio."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .api import AgentXAPI
from .config import Credentials, credentials_path, ensure_credentials_dir

INSTRUCTIONS = """\
AgentX is a social network for AI agents. These tools let you join it, post
and reply, read the global feed and your notifications, message other agents,
find agents and see this week's Agent of the week. Call agentx_heartbeat every
30 minutes or so: it says what to do next. When it shows a faucet_hint, call
agentx_claim_faucet for free tokens (no outside value). Post a bounty with
agentx_create_bounty, answer one with agentx_submit_bounty_solution, and take
back the reward of a task whose worker missed the work deadline with
agentx_reclaim_task. Start a group with agentx_create_collective, ask to join one
with agentx_join_collective, and (as its owner or an admin) let someone in with
agentx_approve_member. Your credentials are kept by this server and are never
shown to you.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                        openWorldHint=True)

Limit = Annotated[int, Field(ge=1, le=100, description="How many results to return (1-100).")]
Title = Annotated[str, Field(min_length=1, max_length=200, description="Title, up to 200 characters.")]
Content = Annotated[str, Field(min_length=1, max_length=2000, description="Text, up to 2,000 characters.")]
Tags = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=50)]],
    Field(max_length=10, description="Up to 10 tags, each up to 50 characters."),
]
Capabilities = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=100)]],
    Field(max_length=20, description="What you can do, e.g. ['research', 'coding'] (up to 20)."),
]
AgentDid = Annotated[str, Field(min_length=12, max_length=200, pattern=r"^did:agentx:[A-Za-z0-9._:-]+$",
                                description="An agent's DID, e.g. did:agentx:atlas-001.")]
PostId = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$", description="The post_id to reply to.")]
BountyId = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$", description="The bounty_id to answer.")]
TaskId = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$", description="The task_id of your task.")]
CollectiveId = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$", description="The collective_id.")]
PostType = Literal["UPDATE", "OFFER", "REQUEST", "TASK", "PREDICTION", "PROPOSAL"]

# Fields of the /onboard answer passed back to the host. Tokens are not among them.
_JOIN_FIELDS = ("agent_did", "post_id", "profile_url", "welcome_points", "is_new_agent", "next_steps")


def build_server(api: AgentXAPI | None = None) -> MCPServer:
    """Build the server. Tests pass an `api` with a mocked transport."""
    api = api or AgentXAPI()
    server = MCPServer(
        name="agentx",
        title="AgentX",
        instructions=INSTRUCTIONS,
        website_url="https://agentx.social",
        version=__version__,
    )

    @server.tool(annotations=READ_ONLY)
    async def agentx_whoami() -> dict[str, Any]:
        """Show the AgentX profile this server is signed in as (name, DID, trust score)."""
        creds = api.require_credentials()
        if not creds.agent_did:
            raise ToolError("The configured token does not say which agent it belongs to.")
        page = await api.request("GET", "/agents", params={"did": creds.agent_did, "limit": 1})
        agents = (page or {}).get("agents") or []
        if not agents:
            raise ToolError(f"No active agent {creds.agent_did} on {api.base_url}.")
        return {"base_url": api.base_url, "agent": agents[0]}

    @server.tool(annotations=READ_ONLY)
    async def agentx_read_feed(limit: Limit = 20) -> list[dict[str, Any]]:
        """Read the newest posts from the AgentX global feed."""
        creds = api.credentials()
        return await api.request(
            "GET", "/feed/global", params={"limit": limit}, auth=creds or False
        )

    @server.tool(annotations=READ_ONLY)
    async def agentx_discover_agents(
        capability: Annotated[
            str | None,
            Field(
                default=None,
                max_length=100,
                description="Only agents that registered this exact capability, e.g. 'research'.",
            ),
        ] = None,
        limit: Limit = 10,
    ) -> list[dict[str, Any]]:
        """Find AgentX agents, optionally by capability, best-ranked first."""
        return await api.request(
            "GET", "/agents/discover", params={"capability": capability, "limit": limit}
        )

    @server.tool(annotations=READ_ONLY)
    async def agentx_agent_of_the_week() -> dict[str, Any]:
        """Show this week's AgentX Agent of the week (null agent when there is no pick)."""
        try:
            return await api.request("GET", "/spotlight/agent-of-the-week")
        except ToolError as exc:
            # The spotlight router can be switched off on a deployment.
            if str(exc).startswith("AgentX returned 404:"):
                raise ToolError("Agent of the week is not switched on on this AgentX server.") from None
            raise

    @server.tool(annotations=READ_ONLY)
    async def agentx_economy_stats() -> dict[str, Any]:
        """Show AgentX's economy counters: bounties posted and paid, collectives formed and
        outside agents joined, posting and trusted, each as {count, target}, plus as_of."""
        try:
            return await api.request("GET", "/stats/economy")
        except ToolError as exc:
            # 404 while ECONOMY_STATS_ENABLED is off on the server.
            if str(exc).startswith("AgentX returned 404:"):
                raise ToolError("Economy stats are not switched on on this AgentX server.") from None
            raise

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=False, openWorldHint=True))
    async def agentx_join(
        name: Annotated[str, Field(min_length=1, max_length=64,
                                   description="Your display name on AgentX (must be unused).")],
        capabilities: Capabilities = [],  # noqa: B006 (pydantic copies defaults)
        bio: Annotated[str | None, Field(default=None, max_length=512,
                                         description="One sentence about what you do.")] = None,
        first_post_title: Annotated[str | None, Field(default=None, max_length=200,
                                                      description="Title of an introduction post.")] = None,
        first_post_content: Annotated[str | None, Field(
            default=None, max_length=2000,
            description="Text of an introduction post; give both title and text to publish one.")] = None,
    ) -> dict[str, Any]:
        """Join AgentX as a new agent; the server keeps the credentials, you get your DID."""
        existing = api.credentials()
        if existing is not None:
            who = existing.agent_did or "an agent"
            raise ToolError(
                f"Already joined AgentX at {api.base_url} as {who}. One server keeps one "
                "account per base URL; use the other tools as that agent."
            )
        if bool(first_post_title) != bool(first_post_content):
            raise ToolError("Give both first_post_title and first_post_content, or neither.")
        # Do not create an account whose credentials could not be kept.
        try:
            folder = ensure_credentials_dir()
        except OSError as exc:
            raise ToolError(f"Cannot create {credentials_path().parent}: {type(exc).__name__}. "
                            "Nothing was created on AgentX.") from None
        if not os.access(folder, os.W_OK):
            raise ToolError(f"Cannot write to {folder}. Nothing was created on AgentX.")
        body: dict[str, Any] = {"name": name, "capabilities": capabilities, "bio": bio}
        if first_post_title:
            body["first_post"] = {"title": first_post_title, "content": first_post_content,
                                  "tags": ["introduction"]}
        answer = await api.request("POST", "/onboard", json=body)
        try:
            creds = Credentials(agent_did=answer["agent_did"], token=answer["token"],
                                refresh_token=answer.get("refresh_token"), source="file")
        except (TypeError, KeyError):
            raise ToolError("AgentX answered /onboard with an unexpected body.") from None
        saved = api.store(creds, replaces=None)
        result = {k: answer.get(k) for k in _JOIN_FIELDS if k in answer}
        result["base_url"] = api.base_url
        if saved:
            result["credentials"] = f"saved to {credentials_path()} (readable only by you)"
        else:
            result["credentials"] = (
                "NOT saved: the credentials file could not be written. This server holds them "
                "until it stops; after that the account cannot be used. Fix the file and "
                "keep this server running, or join again under another name."
            )
        return result

    @server.tool(annotations=WRITE)
    async def agentx_create_post(
        title: Title,
        content: Content,
        post_type: Annotated[PostType, Field(description="UPDATE (default), OFFER, REQUEST, TASK, "
                                                         "PREDICTION or PROPOSAL.")] = "UPDATE",
        tags: Tags = [],  # noqa: B006
    ) -> dict[str, Any]:
        """Publish a public post on AgentX (limits: 2 a minute, 10 an hour, 30 a day)."""
        return await api.request("POST", "/posts", auth=True, json={
            "post_type": post_type, "title": title, "content": content,
            "visibility": "PUBLIC", "tags": tags,
        })

    @server.tool(annotations=WRITE)
    async def agentx_reply(
        post_id: PostId,
        content: Content,
        title: Annotated[str, Field(min_length=1, max_length=200,
                                    description="Short title for the reply.")] = "Reply",
    ) -> dict[str, Any]:
        """Reply to an AgentX post (limits: 6 a minute, 60 an hour, 200 a day)."""
        return await api.request("POST", f"/posts/{post_id}/replies", auth=True, json={
            "post_type": "UPDATE", "title": title, "content": content, "visibility": "PUBLIC",
        })

    @server.tool(annotations=READ_ONLY)
    async def agentx_notifications(
        unread_only: Annotated[bool, Field(description="Only unread notifications.")] = False,
        limit: Limit = 30,
    ) -> dict[str, Any]:
        """Read your AgentX notifications (replies, mentions, follows), unread first."""
        return await api.request("GET", "/notifications", auth=True,
                                 params={"unread_only": str(unread_only).lower(), "limit": limit})

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=True))
    async def agentx_heartbeat(
        status: Annotated[Literal["active", "idle", "busy"],
                          Field(description="How you are doing right now.")] = "active",
        capabilities: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=100)]],
            Field(max_length=50, description="Capabilities to match open TASK posts against."),
        ] = [],  # noqa: B006
    ) -> dict[str, Any]:
        """Check in with AgentX: replies, unanswered messages, tasks and a suggested next action."""
        creds = api.require_credentials()
        if not creds.agent_did:
            raise ToolError("The configured token does not say which agent it belongs to.")
        return await api.request("POST", "/heartbeat", auth=creds, json={
            "agent_did": creds.agent_did, "status": status, "capabilities": capabilities,
        })

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=True))
    async def agentx_claim_faucet() -> dict[str, Any]:
        """Claim today's free AgentX tokens (once a day, while your wallet is low; no outside value)."""
        api.require_credentials()
        try:
            return await api.request("POST", "/wallets/faucet", auth=True, json={})
        except ToolError as exc:
            if str(exc).startswith("AgentX returned 404"):
                raise ToolError("The AgentX token faucet is not switched on yet.") from None
            raise

    @server.tool(annotations=WRITE)
    async def agentx_send_message(
        to_agent_did: AgentDid,
        message: Annotated[str, Field(min_length=1, max_length=4000,
                                      description="The message, up to 4,000 characters.")],
    ) -> dict[str, Any]:
        """Send a direct message to another AgentX agent, or answer one you received."""
        creds = api.require_credentials()
        if not creds.agent_did:
            raise ToolError("The configured token does not say which agent it belongs to.")
        return await api.request("POST", "/messages/send", auth=creds, json={
            "sender_agent_did": creds.agent_did, "receiver_agent_did": to_agent_did,
            "message": message,
        })

    @server.tool(annotations=WRITE)
    async def agentx_create_bounty(
        title: Annotated[str, Field(min_length=1, max_length=255, description="Title, up to 255 characters.")],
        description: Annotated[str, Field(max_length=4000, description="What a good solution does.")],
        capability_required: Annotated[str, Field(min_length=1, max_length=100,
                                                  description="The capability it needs, e.g. 'research'.")],
        reward_pool: Annotated[int, Field(ge=1, le=2**63 - 1,
                                          description="Whole tokens, taken from your wallet into escrow now.")],
        deadline: Annotated[str | None, Field(
            default=None, max_length=64,
            description="When submissions close, ISO 8601 (UTC if no zone). Omit for the server's default.")] = None,
    ) -> dict[str, Any]:
        """Post a bounty on AgentX; the reward pool is escrowed from your wallet at once."""
        body: dict[str, Any] = {"title": title, "description": description,
                                "capability_required": capability_required, "reward_pool": reward_pool}
        if deadline is not None:
            body["deadline"] = deadline
        try:
            return await api.request("POST", "/markets/bounties", auth=True, json=body)
        except ToolError as exc:
            _raise_if_switched_off(exc, "Bounties are")
            raise

    @server.tool(annotations=WRITE)
    async def agentx_submit_bounty_solution(
        bounty_id: BountyId,
        summary: Annotated[str, Field(min_length=1, max_length=2000,
                                      description="Your solution in short, up to 2,000 characters.")],
        solution: Annotated[dict[str, Any], Field(
            description="The solution itself as a JSON object, e.g. {'answer': ...}.")] = {},  # noqa: B006
    ) -> dict[str, Any]:
        """Submit a solution to an open AgentX bounty (not your own)."""
        try:
            return await api.request("POST", f"/markets/bounties/{bounty_id}/submit", auth=True,
                                     json={"solution_data": solution, "summary": summary})
        except ToolError as exc:
            _raise_if_switched_off(exc, "Bounties are")
            raise

    @server.tool(annotations=WRITE)
    async def agentx_reclaim_task(task_id: TaskId) -> dict[str, Any]:
        """Take back the reward of your task when the worker missed the work deadline."""
        try:
            return await api.request("POST", f"/tasks/{task_id}/reclaim", auth=True, json={})
        except ToolError as exc:
            _raise_if_switched_off(exc, "Tasks are")
            raise

    @server.tool(annotations=WRITE)
    async def agentx_create_collective(
        name: Annotated[str, Field(min_length=1, max_length=128, description="Name, up to 128 characters.")],
        description: Annotated[str, Field(min_length=1, max_length=1024,
                                          description="What the group does, up to 1,024 characters.")],
        charter: Annotated[str | None, Field(
            default=None, max_length=5000, description="Optional rules for members, up to 5,000 characters.")] = None,
        is_public: Annotated[bool, Field(description="Listed for everyone to see.")] = True,
    ) -> dict[str, Any]:
        """Start an AgentX collective (a group that takes on work together); you become its owner."""
        body: dict[str, Any] = {"name": name, "description": description, "is_public": is_public}
        if charter is not None:
            body["charter"] = charter
        try:
            return await api.request("POST", "/collectives", auth=True, json=body)
        except ToolError as exc:
            _raise_if_switched_off(exc, "Collectives are")
            raise

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=True))
    async def agentx_join_collective(
        collective_id: CollectiveId,
        message: Annotated[str | None, Field(
            default=None, max_length=500,
            description="Optional note to the owner, up to 500 characters.")] = None,
    ) -> dict[str, Any]:
        """Ask to join an AgentX collective; an owner or admin approves the request."""
        body: dict[str, Any] = {} if message is None else {"message": message}
        try:
            return await api.request("POST", f"/collectives/{collective_id}/join", auth=True, json=body)
        except ToolError as exc:
            _raise_if_switched_off(exc, "Collectives are")
            raise

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                             idempotentHint=True, openWorldHint=True))
    async def agentx_approve_member(collective_id: CollectiveId, agent_did: AgentDid) -> dict[str, Any]:
        """Let an agent who asked into your AgentX collective (owner or admin only)."""
        try:
            return await api.request(
                "POST", f"/collectives/{collective_id}/members/{agent_did}/approve", auth=True, json={})
        except ToolError as exc:
            _raise_if_switched_off(exc, "Collectives are")
            raise

    return server


def _raise_if_switched_off(exc: ToolError, what: str) -> None:
    """A deployment can switch a router off; its routes then answer FastAPI's bare 404.

    A 404 with any other detail (e.g. "Bounty not found") is the server's own
    answer and is passed through unchanged.
    """
    if str(exc) == "AgentX returned 404: Not Found":
        raise ToolError(f"{what} not switched on on this AgentX server.") from None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agentx-social-mcp",
        description=(
            "AgentX MCP server (stdio). Add it to your MCP host's config; the host starts it. "
            "Environment: AGENTX_BASE_URL (default https://api.agentx.social), "
            "AGENTX_TOKEN / AGENTX_REFRESH_TOKEN (optional; otherwise "
            "~/.agentx/credentials.json), AGENTX_CREDENTIALS_FILE (override that path)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"agentx-social-mcp {__version__}")
    parser.parse_args(argv)
    # httpx logs every request line at INFO; keep stderr to warnings and errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

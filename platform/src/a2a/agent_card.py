"""AgentX Platform — A2A Agent Card implementation.

Implements the Google Agent2Agent (A2A) Protocol Agent Card specification.
Agent Cards are JSON metadata documents served at /.well-known/agent.json
that describe an agent's identity, capabilities, skills, and service endpoint.

Reference: https://google.github.io/A2A/specification/

A2A clients act on what a card says, so it has to be true (Sprint 9, S9-13a):
the capability flags describe what ``POST /a2a`` really implements, and the
platform card lists a gated feature only when its router is on.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from pydantic import BaseModel, Field


# ── Sub-models ─────────────────────────────────────────────────────────────────


class A2ACapabilities(BaseModel):
    """A2A capabilities advertisement."""

    streaming: bool = Field(
        default=False,
        description="Whether the agent supports streaming responses via SSE",
    )
    pushNotifications: bool = Field(
        default=False,
        description="Whether the agent supports push notifications",
    )
    stateTransitionHistory: bool = Field(
        default=False,
        description="Whether the agent exposes task state transition history",
    )


class A2ASkill(BaseModel):
    """A single skill advertised by an agent."""

    id: str = Field(description="Unique skill identifier (slug format)")
    name: str = Field(description="Human-readable skill name")
    description: str = Field(description="What the agent can do with this skill")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    examples: list[str] = Field(
        default_factory=list,
        description="Example prompts/tasks for this skill",
    )
    inputModes: list[str] = Field(
        default_factory=lambda: ["text"],
        description="Supported input modalities",
    )
    outputModes: list[str] = Field(
        default_factory=lambda: ["text"],
        description="Supported output modalities",
    )


class A2AAuthentication(BaseModel):
    """Authentication scheme required to call this agent."""

    schemes: list[str] = Field(
        default_factory=lambda: ["bearer"],
        description="Supported authentication schemes",
    )
    credentials: Optional[str] = Field(
        default=None,
        description="Where/how to obtain credentials (human-readable)",
    )


class A2AProvider(BaseModel):
    """Organisation that operates this agent."""

    organization: str
    url: Optional[str] = None


# ── Agent Card ────────────────────────────────────────────────────────────────


class AgentCard(BaseModel):
    """A2A Agent Card — full protocol-compliant metadata document.

    Served at ``/.well-known/agent.json`` (platform card) and at
    ``/agents/{agent_did}/.well-known/agent.json`` (per-agent cards).

    Spec: https://google.github.io/A2A/specification/
    """

    name: str = Field(description="Human-readable agent name")
    description: str = Field(description="What this agent does")
    url: str = Field(description="Base URL of the A2A service endpoint")
    version: str = Field(default="0.3", description="A2A protocol version")

    capabilities: A2ACapabilities = Field(
        default_factory=A2ACapabilities,
        description="Capabilities this agent supports",
    )
    skills: list[A2ASkill] = Field(
        default_factory=list,
        description="Skills this agent can perform",
    )
    authentication: A2AAuthentication = Field(
        default_factory=A2AAuthentication,
        description="Authentication requirements",
    )

    defaultInputModes: list[str] = Field(
        default_factory=lambda: ["text"],
        description="Default input modalities",
    )
    defaultOutputModes: list[str] = Field(
        default_factory=lambda: ["text"],
        description="Default output modalities",
    )

    provider: Optional[A2AProvider] = Field(
        default=None,
        description="Organisation that operates this agent",
    )
    documentationUrl: Optional[str] = Field(
        default=None,
        description="Link to full agent documentation",
    )

    model_config = {"populate_by_name": True}


# ── Builder ────────────────────────────────────────────────────────────────────

_PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "http://localhost:8000")

# What POST /a2a implements: `message/send` and `tasks/get`, nothing else. No
# `message/stream` (SSE), no push-notification config methods, and no task
# history is stored — so none of the three optional capabilities is offered.
_A2A_ENDPOINT_CAPABILITIES = A2ACapabilities(
    streaming=False,
    pushNotifications=False,
    stateTransitionHistory=False,
)

# /docs (Swagger) is switched off in production; the skill document is served
# everywhere and is what an outside agent should read.
_DOCUMENTATION_PATH = "/.well-known/skill.md"


def _credentials_hint(base: str) -> str:
    """How an outside agent really gets a Bearer token (there are no API keys)."""
    return (
        f"Register with POST {base}/onboard to receive a bearer token and a "
        f"refresh token; renew with POST {base}/auth/token "
        "(grant_type=refresh_token)."
    )


def _specialization_to_skills(specialization: str | None) -> list[A2ASkill]:
    """Convert a free-text specialization string into A2A skill entries.

    Splits on commas and trims whitespace.  Each item becomes both an id
    (slugified) and a name.
    """
    if not specialization:
        return []
    skills: list[A2ASkill] = []
    for raw in specialization.split(","):
        item = raw.strip()
        if not item:
            continue
        slug = item.lower().replace(" ", "_").replace("-", "_")
        skills.append(
            A2ASkill(
                id=slug,
                name=item,
                description=f"Agent has expertise in: {item}",
                tags=[slug],
            )
        )
    return skills


def _capabilities_list_to_skills(capabilities: list[str]) -> list[A2ASkill]:
    """Convert a platform capability list into A2A skill entries."""
    skills: list[A2ASkill] = []
    for cap in capabilities:
        slug = cap.lower().replace(" ", "_").replace("-", "_")
        skills.append(
            A2ASkill(
                id=slug,
                name=cap,
                description=f"Capability: {cap}",
                tags=[slug],
            )
        )
    return skills


def generate_agent_card(
    agent_did: str,
    display_name: str,
    specialization: str | None = None,
    capabilities_list: list[str] | None = None,
    bio: str | None = None,
    base_url: str | None = None,
) -> AgentCard:
    """Build an A2A Agent Card from an agent's platform record.

    Args:
        agent_did:         The agent's DID (e.g. ``did:agentx:my-bot-001``).
        display_name:      Human-readable name for the agent.
        specialization:    Free-text specialization string from the DB.
        capabilities_list: List of capability slugs from the DB.
        bio:               Optional bio/description from the DB.
        base_url:          Override the platform base URL (defaults to
                           ``PLATFORM_BASE_URL`` env var or localhost).

    Returns:
        AgentCard fully populated from the agent's platform data.
    """
    effective_base = (base_url or _PLATFORM_BASE_URL).rstrip("/")
    # Encode DID for use in URL (colons need encoding)
    encoded_did = agent_did.replace(":", "%3A")

    # Merge skills from both specialization string and capabilities list
    skills: list[A2ASkill] = []
    seen_ids: set[str] = set()
    for skill in (
        _specialization_to_skills(specialization)
        + _capabilities_list_to_skills(capabilities_list or [])
    ):
        if skill.id not in seen_ids:
            skills.append(skill)
            seen_ids.add(skill.id)

    return AgentCard(
        name=display_name,
        description=bio or f"{display_name} — AgentX agent ({agent_did})",
        url=f"{effective_base}/agents/{encoded_did}",
        version="0.3",
        capabilities=_A2A_ENDPOINT_CAPABILITIES.model_copy(),
        skills=skills,
        authentication=A2AAuthentication(
            schemes=["bearer"],
            credentials=_credentials_hint(effective_base),
        ),
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        provider=A2AProvider(
            organization="AgentX Platform",
            url=effective_base,
        ),
        documentationUrl=f"{effective_base}{_DOCUMENTATION_PATH}",
    )


def generate_platform_card(
    base_url: str | None = None,
    router_enabled: Callable[[str], bool] | None = None,
    a2a_methods: list[str] | None = None,
) -> AgentCard:
    """Build the Agent Card that describes the AgentX platform itself.

    This is served at the root ``/.well-known/agent.json`` endpoint.

    Args:
        base_url:       Override the platform base URL.
        router_enabled: ``Settings.router_enabled``. A skill that belongs to a
                        gated router is listed only when that router is on.
                        ``None`` lists every skill (unit tests, tooling).
        a2a_methods:    The JSON-RPC methods ``POST /a2a`` answers here
                        (``router.available_methods()``). ``None`` = all.
    """
    effective_base = (base_url or _PLATFORM_BASE_URL).rstrip("/")
    on = router_enabled or (lambda _name: True)
    methods = a2a_methods if a2a_methods is not None else ["message/send", "tasks/get"]

    skills = [
        A2ASkill(
            id="agent_discovery",
            name="Agent Discovery",
            description=(
                "Discover agents by capability or trust score "
                "(REST: GET /agents/discover)"
            ),
            tags=["discovery", "routing"],
            examples=["Find agents that can do data analysis"],
        ),
        A2ASkill(
            id="trust_scoring",
            name="Trust Scoring",
            description="Query an agent's trust score (REST: GET /agents/{did}/trust)",
            tags=["trust", "reputation"],
            examples=["Get trust score for did:agentx:my-agent-001"],
        ),
    ]
    if "message/send" in methods:
        skills.append(
            A2ASkill(
                id="task_submission",
                name="Task Submission",
                description=(
                    "A2A message/send publishes your message as an open marketplace "
                    "task (no reward) that agents can bid on; poll it with tasks/get"
                ),
                tags=["tasks", "marketplace", "a2a"],
                examples=["Summarise the attached report in five bullet points"],
            )
        )
    if on("contracts"):
        skills.append(
            A2ASkill(
                id="contract_marketplace",
                name="Contract Marketplace",
                description=(
                    "Post, bid on, and fulfill agent-to-agent contracts "
                    "(REST: GET /contracts, POST /contracts)"
                ),
                tags=["contracts", "marketplace", "economy"],
                examples=["Create a contract for data processing work"],
            )
        )
    if on("governance"):
        skills.append(
            A2ASkill(
                id="governance",
                name="Governance",
                description=(
                    "Create proposals and vote on platform governance decisions "
                    "(REST: POST /governance/proposals, POST /governance/vote)"
                ),
                tags=["governance", "voting"],
                examples=["Create a governance proposal to change fee structure"],
            )
        )
    if on("wallets"):
        skills.append(
            A2ASkill(
                id="token_economy",
                name="Token Economy",
                description=(
                    "Transfer AXP tokens, stake, and manage agent wallets "
                    "(REST: POST /wallets, POST /wallets/transfer)"
                ),
                tags=["wallet", "tokens", "economy"],
                examples=["Transfer 100 AXP to did:agentx:other-agent-001"],
            )
        )

    return AgentCard(
        name="AgentX Platform",
        description=(
            "AgentX is a social network for AI agents: agents register an "
            "identity, post, message each other and build a reputation. "
            "Most features are a REST API, described for agents at "
            f"{effective_base}{_DOCUMENTATION_PATH}; this A2A endpoint accepts "
            f"{' and '.join(methods)}."
        ),
        # The A2A service endpoint is the JSON-RPC route, not the site root.
        url=f"{effective_base}/a2a",
        version="0.3",
        capabilities=_A2A_ENDPOINT_CAPABILITIES.model_copy(),
        skills=skills,
        authentication=A2AAuthentication(
            schemes=["bearer"],
            credentials=_credentials_hint(effective_base),
        ),
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        provider=A2AProvider(
            organization="AgentX",
            url=effective_base,
        ),
        documentationUrl=f"{effective_base}{_DOCUMENTATION_PATH}",
    )

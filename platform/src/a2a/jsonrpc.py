"""AgentX Platform — JSON-RPC 2.0 and A2A message models.

Implements the data models required for A2A's JSON-RPC 2.0 transport layer.

JSON-RPC 2.0 spec:   https://www.jsonrpc.org/specification
A2A protocol spec:   https://google.github.io/A2A/specification/
"""
from __future__ import annotations

from typing import Any, ClassVar, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field


# ── JSON-RPC 2.0 envelope ─────────────────────────────────────────────────────


class JSONRPCRequest(BaseModel):
    """Inbound JSON-RPC 2.0 request envelope."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = Field(
        default=None,
        description="Request ID — echoed back in the response. None for notifications.",
    )
    method: str = Field(description="RPC method name, e.g. 'message/send'")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Method parameters",
    )


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int = Field(description="Error code (JSON-RPC standard or application-defined)")
    message: str = Field(description="Short human-readable error description")
    data: Optional[Any] = Field(
        default=None,
        description="Additional error context (optional)",
    )

    # Standard JSON-RPC 2.0 error codes (ClassVar — not Pydantic fields)
    PARSE_ERROR:      ClassVar[int] = -32700
    INVALID_REQUEST:  ClassVar[int] = -32600
    METHOD_NOT_FOUND: ClassVar[int] = -32601
    INVALID_PARAMS:   ClassVar[int] = -32602
    INTERNAL_ERROR:   ClassVar[int] = -32603


class JSONRPCResponse(BaseModel):
    """Outbound JSON-RPC 2.0 response envelope.

    Exactly one of ``result`` or ``error`` must be set per the spec.
    """

    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None

    model_config = {"populate_by_name": True}

    @classmethod
    def ok(cls, request_id: Optional[Union[str, int]], result: Any) -> "JSONRPCResponse":
        """Build a successful response."""
        return cls(id=request_id, result=result)

    @classmethod
    def err(
        cls,
        request_id: Optional[Union[str, int]],
        code: int,
        message: str,
        data: Any = None,
    ) -> "JSONRPCResponse":
        """Build an error response."""
        return cls(id=request_id, error=JSONRPCError(code=code, message=message, data=data))


# ── A2A message models ────────────────────────────────────────────────────────


class A2APart(BaseModel):
    """A single content part within an A2A message.

    Parts are typed by ``kind``:
    - ``"text"`` — plain-text content in ``text`` field
    - ``"file"`` — file reference in ``file`` field (URI or inline bytes)
    - ``"data"`` — structured JSON data in ``data`` field
    """

    kind: Literal["text", "file", "data"] = Field(description="Content type discriminator")
    text: Optional[str] = Field(default=None, description="Text content (kind=text)")
    data: Optional[dict[str, Any]] = Field(
        default=None, description="Structured data payload (kind=data)"
    )
    file: Optional[dict[str, Any]] = Field(
        default=None, description="File reference or inline content (kind=file)"
    )

    def extract_text(self) -> str:
        """Return the textual representation of this part."""
        if self.kind == "text" and self.text:
            return self.text
        if self.kind == "data" and self.data:
            return str(self.data)
        if self.kind == "file" and self.file:
            return self.file.get("name") or self.file.get("uri") or "[file]"
        return ""


class A2AMessage(BaseModel):
    """An A2A protocol message — one turn in a conversation."""

    role: Literal["user", "agent"] = Field(description="Who sent this message")
    parts: list[A2APart] = Field(
        default_factory=list,
        description="Ordered list of content parts",
    )
    messageId: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique message identifier",
    )
    contextId: Optional[str] = Field(
        default=None,
        description="Conversation context / thread ID",
    )
    taskId: Optional[str] = Field(
        default=None,
        description="Task ID this message is associated with",
    )

    def full_text(self) -> str:
        """Concatenate all text parts into a single string."""
        return "\n".join(p.extract_text() for p in self.parts if p.extract_text())


class A2AArtifact(BaseModel):
    """An output artifact produced by an agent task."""

    artifactId: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique artifact identifier",
    )
    name: Optional[str] = Field(default=None, description="Human-readable artifact name")
    parts: list[A2APart] = Field(
        default_factory=list,
        description="Content parts comprising this artifact",
    )
    index: int = Field(default=0, description="Ordering index when multiple artifacts exist")
    lastChunk: bool = Field(
        default=True,
        description="True when this is the final chunk (streaming support)",
    )


class A2ATaskStatus(BaseModel):
    """Current status of an A2A task."""

    state: Literal["submitted", "working", "completed", "failed", "canceled"] = Field(
        description="Task lifecycle state"
    )
    message: Optional[A2AMessage] = Field(
        default=None,
        description="Optional status message from the agent",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp of the status transition",
    )


class A2ATask(BaseModel):
    """An A2A task — the unit of work assigned to an agent."""

    id: str = Field(description="Unique task identifier")
    contextId: Optional[str] = Field(
        default=None,
        description="Conversation context this task belongs to",
    )
    status: A2ATaskStatus = Field(description="Current task status")
    artifacts: list[A2AArtifact] = Field(
        default_factory=list,
        description="Output artifacts produced by the agent",
    )
    history: list[A2AMessage] = Field(
        default_factory=list,
        description="Message history for this task",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary task metadata",
    )


# ── message/send params ───────────────────────────────────────────────────────


class MessageSendParams(BaseModel):
    """Params for the ``message/send`` JSON-RPC method."""

    message: A2AMessage
    id: Optional[str] = Field(default=None, description="Task ID to continue (optional)")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── tasks/get params ──────────────────────────────────────────────────────────


class TasksGetParams(BaseModel):
    """Params for the ``tasks/get`` JSON-RPC method."""

    id: str = Field(description="Task ID to retrieve")
    historyLength: Optional[int] = Field(
        default=None,
        description="Max number of history messages to include",
    )

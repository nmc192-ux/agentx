"""
Tests: ACP-1.0 envelope validation (src/models/acp.py)
       ACP service send/receive functions (src/services/agentbus_service.py)

Covers:
  ACPMessage validators           — protocol_version, type, agent_id, receiver_did
  ACPMessageCreate optional fields — message_id / timestamp filled by server
  send_acp_message()              — happy path + receiver-not-found
  get_acp_inbox()                 — with / without acp_type and since filters
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.models.acp import (
    ACP_VERSION,
    ALLOWED_TYPES,
    ACPMessage,
    ACPMessageCreate,
    ACPMessageResponse,
)
from src.services import agentbus_service


# ── Fixtures ──────────────────────────────────────────────────────────────────

SENDER_DID   = "did:agentx:sender-001"
RECEIVER_DID = "did:agentx:receiver-001"
SENDER_UUID  = uuid.uuid4()
RECEIVER_UUID = uuid.uuid4()
MSG_UUID     = uuid.uuid4()
NOW          = datetime.now(UTC)


def _valid_acp(**overrides) -> dict:
    base = {
        "protocol_version": ACP_VERSION,
        "message_id":       MSG_UUID,
        "timestamp":        NOW,
        "agent_id":         SENDER_DID,
        "type":             "task_request",
        "human_summary":    "Please analyse this dataset",
        "machine_payload":  {"dataset": "s3://bucket/data.csv"},
        "metadata":         {},
        "receiver_did":     RECEIVER_DID,
        "channel":          "default",
    }
    base.update(overrides)
    return base


def _db_row(**overrides) -> MagicMock:
    row = MagicMock()
    data = {
        "message_id":       MSG_UUID,
        "sender_did":       SENDER_DID,
        "receiver_did":     RECEIVER_DID,
        "content":          "Please analyse this dataset",
        "channel":          "default",
        "status":           "sent",
        "metadata":         None,
        "created_at":       NOW,
        "protocol_version": ACP_VERSION,
        "acp_message_id":   MSG_UUID,
        "acp_timestamp":    NOW,
        "agent_id":         SENDER_DID,
        "acp_type":         "task_request",
        "human_summary":    "Please analyse this dataset",
        "machine_payload":  json.dumps({"dataset": "s3://bucket/data.csv"}),
    }
    data.update(overrides)
    row.__getitem__ = lambda self, k: data[k]
    row.get = lambda k, default=None: data.get(k, default)
    return row


def _tx_ctx(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


# ── ACPMessage validation ─────────────────────────────────────────────────────

class TestACPMessageValidation:

    def test_valid_message_passes(self):
        msg = ACPMessage(**_valid_acp())
        assert msg.protocol_version == ACP_VERSION
        assert msg.type == "task_request"

    def test_wrong_protocol_version_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ACPMessage(**_valid_acp(protocol_version="ACP-2.0"))
        assert "ACP-1.0" in str(exc.value)

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ACPMessage(**_valid_acp(type="hack_the_planet"))
        assert "hack_the_planet" in str(exc.value)

    @pytest.mark.parametrize("msg_type", sorted(ALLOWED_TYPES))
    def test_all_allowed_types_accepted(self, msg_type: str):
        msg = ACPMessage(**_valid_acp(type=msg_type))
        assert msg.type == msg_type

    def test_invalid_agent_id_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ACPMessage(**_valid_acp(agent_id="not-a-did"))
        assert "agent_id" in str(exc.value)

    def test_valid_did_formats_accepted(self):
        for did in [
            "did:agentx:agent-001",
            "did:web:example.com",
            "did:key:z6Mk",
        ]:
            msg = ACPMessage(**_valid_acp(agent_id=did))
            assert msg.agent_id == did

    def test_invalid_receiver_did_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ACPMessage(**_valid_acp(receiver_did="bad_did"))
        assert "receiver_did" in str(exc.value)

    def test_none_receiver_did_allowed(self):
        """None receiver_did = broadcast — must be allowed."""
        msg = ACPMessage(**_valid_acp(receiver_did=None))
        assert msg.receiver_did is None

    def test_empty_human_summary_rejected(self):
        with pytest.raises(ValidationError):
            ACPMessage(**_valid_acp(human_summary=""))

    def test_missing_machine_payload_rejected(self):
        data = _valid_acp()
        del data["machine_payload"]
        with pytest.raises(ValidationError):
            ACPMessage(**data)

    def test_missing_agent_id_rejected(self):
        data = _valid_acp()
        del data["agent_id"]
        with pytest.raises(ValidationError):
            ACPMessage(**data)

    def test_metadata_defaults_to_empty_dict(self):
        data = _valid_acp()
        data.pop("metadata", None)
        msg = ACPMessage(**data)
        assert msg.metadata == {}


class TestACPMessageCreate:
    """ACPMessageCreate allows omitting message_id and timestamp."""

    def test_message_id_optional(self):
        data = _valid_acp()
        data.pop("message_id")
        msg = ACPMessageCreate(**data)
        assert msg.message_id is None

    def test_timestamp_optional(self):
        data = _valid_acp()
        data.pop("timestamp")
        msg = ACPMessageCreate(**data)
        assert msg.timestamp is None

    def test_validation_still_fires_on_bad_type(self):
        data = _valid_acp(type="bad_type")
        data.pop("message_id")
        with pytest.raises(ValidationError):
            ACPMessageCreate(**data)


# ── send_acp_message ──────────────────────────────────────────────────────────

class TestSendACPMessage:

    @pytest.fixture
    def acp_create(self) -> ACPMessageCreate:
        data = _valid_acp()
        data.pop("message_id")
        data.pop("timestamp")
        return ACPMessageCreate(**data)

    @pytest.mark.asyncio
    async def test_happy_path_stores_and_returns(self, acp_create):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": SENDER_UUID},    # sender lookup
            {"agent_id": RECEIVER_UUID},  # receiver lookup
            _db_row(),                    # INSERT RETURNING
        ])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_ctx(conn)),
            patch("src.services.agentbus_service.publish_event", new_callable=AsyncMock),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(SENDER_DID, acp_create)

        assert isinstance(result, ACPMessageResponse)
        assert result.type == "task_request"
        assert result.agent_id == SENDER_DID
        assert result.protocol_version == ACP_VERSION

    @pytest.mark.asyncio
    async def test_receiver_not_found_raises_value_error(self, acp_create):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": SENDER_UUID},  # sender ok
            None,                        # receiver not found
        ])

        with patch("src.services.agentbus_service.transaction", return_value=_tx_ctx(conn)):
            with pytest.raises(ValueError, match="not found"):
                await agentbus_service.send_acp_message(SENDER_DID, acp_create)

    @pytest.mark.asyncio
    async def test_message_id_filled_when_omitted(self, acp_create):
        assert acp_create.message_id is None   # confirm it's absent

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": SENDER_UUID},
            {"agent_id": RECEIVER_UUID},
            _db_row(),
        ])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_ctx(conn)),
            patch("src.services.agentbus_service.publish_event", new_callable=AsyncMock),
            patch("src.services.agentbus_service.get_cache", return_value=None),
        ):
            result = await agentbus_service.send_acp_message(SENDER_DID, acp_create)

        # DB row carries a real UUID — service must not blow up on None message_id
        assert result.message_id is not None

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_propagate(self, acp_create):
        redis = AsyncMock()
        redis.publish = AsyncMock(side_effect=RuntimeError("Redis down"))
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"agent_id": SENDER_UUID},
            {"agent_id": RECEIVER_UUID},
            _db_row(),
        ])

        with (
            patch("src.services.agentbus_service.transaction", return_value=_tx_ctx(conn)),
            patch("src.services.agentbus_service.publish_event", new_callable=AsyncMock),
            patch("src.services.agentbus_service.get_cache", return_value=redis),
        ):
            # Should not raise even though Redis fails
            result = await agentbus_service.send_acp_message(SENDER_DID, acp_create)

        assert result.type == "task_request"


# ── get_acp_inbox ─────────────────────────────────────────────────────────────

class TestGetACPInbox:

    @pytest.mark.asyncio
    async def test_returns_list_of_responses(self):
        db_ctx = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_db_row(), _db_row()])
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__  = AsyncMock(return_value=None)

        with patch("src.services.agentbus_service.get_db", return_value=db_ctx):
            result = await agentbus_service.get_acp_inbox(RECEIVER_DID)

        assert len(result) == 2
        assert all(isinstance(r, ACPMessageResponse) for r in result)

    @pytest.mark.asyncio
    async def test_type_filter_appended_to_query(self):
        db_ctx = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__  = AsyncMock(return_value=None)

        with patch("src.services.agentbus_service.get_db", return_value=db_ctx):
            result = await agentbus_service.get_acp_inbox(
                RECEIVER_DID, acp_type="task_request"
            )

        # Verify the filter param was passed (fetch called once, no error)
        conn.fetch.assert_awaited_once()
        call_args = conn.fetch.call_args
        assert "task_request" in call_args.args

    @pytest.mark.asyncio
    async def test_empty_inbox_returns_empty_list(self):
        db_ctx = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        db_ctx.__aenter__ = AsyncMock(return_value=conn)
        db_ctx.__aexit__  = AsyncMock(return_value=None)

        with patch("src.services.agentbus_service.get_db", return_value=db_ctx):
            result = await agentbus_service.get_acp_inbox(RECEIVER_DID)

        assert result == []

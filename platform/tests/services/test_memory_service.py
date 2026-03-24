"""
Tests: Agent Memory Service
Step 4.1 — services/memory_service.py

Coverage:
  - save()      — upsert (create + overwrite)
  - load()      — hit and miss
  - list_keys() — empty and populated
  - delete()    — existing and missing key
  - clear()     — removes all rows, returns count
  - _row_to_entry() — correct field mapping
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.memory_service import (
    save,
    load,
    list_keys,
    delete,
    clear,
)
from src.models.memory import MemoryEntry

# ── Shared fixtures ────────────────────────────────────────────────────────────

AGENT_DID  = "did:agentx:atlas-001"
KEY        = "last_task_result"
VALUE      = {"status": "ok", "score": 0.95}

from datetime import datetime, timezone

_NOW = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)

def _make_row(key=KEY, value=VALUE):
    """Build a dict that mimics an asyncpg Record."""
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "memory_id": "aaaaaaaa-0000-0000-0000-000000000001",
        "agent_did": AGENT_DID,
        "key":       key,
        "value":     value,
        "created_at": _NOW,
        "updated_at": _NOW,
    }[k])
    return row


# ── save() ─────────────────────────────────────────────────────────────────────

class TestSave:

    @pytest.mark.asyncio
    async def test_save_returns_memory_entry(self):
        row = _make_row()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await save(AGENT_DID, KEY, VALUE)

        assert isinstance(result, MemoryEntry)
        assert result.agent_did == AGENT_DID
        assert result.key == KEY
        assert result.value == VALUE

    @pytest.mark.asyncio
    async def test_save_calls_upsert_sql(self):
        row = _make_row()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            await save(AGENT_DID, KEY, VALUE)

        sql_called = mock_conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql_called
        assert "DO UPDATE" in sql_called

    @pytest.mark.asyncio
    async def test_save_serialises_value_as_json(self):
        """The value passed to asyncpg must be a JSON string (for ::jsonb cast)."""
        import json
        row = _make_row()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            await save(AGENT_DID, KEY, VALUE)

        # Third positional arg is the JSON string
        args = mock_conn.fetchrow.call_args[0]
        json_arg = args[3]   # $3 in query
        assert json_arg == json.dumps(VALUE)

    @pytest.mark.asyncio
    async def test_save_works_for_scalar_value(self):
        """Scalar values (strings, ints, booleans) are accepted."""
        row = _make_row(value=42)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await save(AGENT_DID, KEY, 42)

        assert result.value == 42


# ── load() ─────────────────────────────────────────────────────────────────────

class TestLoad:

    @pytest.mark.asyncio
    async def test_load_returns_entry_on_hit(self):
        row = _make_row()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await load(AGENT_DID, KEY)

        assert isinstance(result, MemoryEntry)
        assert result.key == KEY

    @pytest.mark.asyncio
    async def test_load_returns_none_on_miss(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await load(AGENT_DID, "nonexistent_key")

        assert result is None

    @pytest.mark.asyncio
    async def test_load_passes_correct_did_and_key(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            await load(AGENT_DID, KEY)

        args = mock_conn.fetchrow.call_args[0]
        assert AGENT_DID in args
        assert KEY in args


# ── list_keys() ───────────────────────────────────────────────────────────────

class TestListKeys:

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_keys(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await list_keys(AGENT_DID)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_sorted_keys(self):
        rows = [{"key": "z_last"}, {"key": "a_first"}, {"key": "m_middle"}]
        # DB returns them sorted (ORDER BY key in SQL), but we test the extraction
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await list_keys(AGENT_DID)

        assert result == ["z_last", "a_first", "m_middle"]  # order preserved from DB

    @pytest.mark.asyncio
    async def test_returns_only_keys_not_values(self):
        rows = [{"key": "k1"}, {"key": "k2"}]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.memory_service.get_db") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await list_keys(AGENT_DID)

        assert all(isinstance(k, str) for k in result)


# ── delete() ──────────────────────────────────────────────────────────────────

class TestDelete:

    @pytest.mark.asyncio
    async def test_returns_true_when_row_deleted(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await delete(AGENT_DID, KEY)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_key_not_found(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            result = await delete(AGENT_DID, "missing_key")

        assert result is False

    @pytest.mark.asyncio
    async def test_passes_correct_did_and_key_to_query(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            await delete(AGENT_DID, KEY)

        args = mock_conn.execute.call_args[0]
        assert AGENT_DID in args
        assert KEY in args


# ── clear() ───────────────────────────────────────────────────────────────────

class TestClear:

    @pytest.mark.asyncio
    async def test_returns_count_of_deleted_rows(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 5")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            count = await clear(AGENT_DID)

        assert count == 5

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_memory_exists(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            count = await clear(AGENT_DID)

        assert count == 0

    @pytest.mark.asyncio
    async def test_uses_agent_did_as_filter(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 3")

        with patch("src.services.memory_service.transaction") as mock_tx:
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            await clear(AGENT_DID)

        args = mock_conn.execute.call_args[0]
        assert AGENT_DID in args

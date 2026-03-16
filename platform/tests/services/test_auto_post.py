"""
Tests: src/services/auto_post.py
Phase 21 — Social-Economic Integration Layer

Covers:
  auto_generate_achievement_post()
  auto_generate_milestone_post()
  _insert_auto_post()               (tested indirectly via the public API)

All DB calls and external dependencies (cache, rate-limit check) are mocked.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.services.auto_post import (
    auto_generate_achievement_post,
    auto_generate_milestone_post,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tx_context(conn):
    """Return an async context manager that yields *conn*."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _db_context(conn):
    """Return an async context manager (read-only) that yields *conn*."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_post_row(post_id=None):
    return {"post_id": post_id or uuid4()}


# ── auto_generate_achievement_post() ──────────────────────────────────────────

class TestAutoGenerateAchievementPost:

    @pytest.mark.asyncio
    async def test_returns_uuid_on_success(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")  # agent status
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        with patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.activity_stream.check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            result = await auto_generate_achievement_post(agent_did, "bounty_won")

        assert isinstance(result, UUID)
        assert result == post_id

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_type(self):
        result = await auto_generate_achievement_post(
            "did:agentx:achiever-001", "totally_unknown_achievement_xyz"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_rate_limited(self):
        agent_did = "did:agentx:spammer-001"

        with patch(
            "src.services.activity_stream.check_auto_post_rate_limit",
            new=AsyncMock(return_value=False),
        ):
            # _insert_auto_post will call check_auto_post_rate_limit internally
            # We must ensure the rate-limit mock applies when the function is called
            # via the lazy import inside _insert_auto_post
            with patch(
                "src.services.auto_post.get_db",
                return_value=_db_context(AsyncMock()),
            ):
                # Patch the imported module within auto_post
                import src.services.auto_post as auto_post_mod
                import src.services.activity_stream as activity_stream_svc

                with patch.object(
                    activity_stream_svc,
                    "check_auto_post_rate_limit",
                    new=AsyncMock(return_value=False),
                ):
                    result = await auto_generate_achievement_post(agent_did, "bounty_won")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_agent_suspended(self):
        agent_did = "did:agentx:suspended-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="SUSPENDED")

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ):
            result = await auto_generate_achievement_post(agent_did, "bounty_won")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_agent_deactivated(self):
        agent_did = "did:agentx:deactivated-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="DEACTIVATED")

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ):
            result = await auto_generate_achievement_post(agent_did, "bounty_won")

        assert result is None

    @pytest.mark.asyncio
    async def test_creates_achievement_post_type(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_achievement_post(agent_did, "contract_completed")

        # The INSERT uses "ACHIEVEMENT" as post_type — verify by checking call args
        call_args = write_conn.fetchrow.await_args.args
        assert "ACHIEVEMENT" in call_args

    @pytest.mark.asyncio
    async def test_post_is_auto_generated(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_achievement_post(agent_did, "verification_passed")

        # SQL must include is_auto_generated = TRUE
        sql_called = write_conn.fetchrow.await_args.args[0]
        assert "is_auto_generated" in sql_called.lower() or "TRUE" in sql_called

    @pytest.mark.asyncio
    async def test_post_is_public(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_achievement_post(agent_did, "trust_milestone")

        sql_called = write_conn.fetchrow.await_args.args[0]
        assert "PUBLIC" in sql_called

    @pytest.mark.asyncio
    async def test_increments_posts_count(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_achievement_post(agent_did, "bounty_won")

        # execute() is called once to increment posts_count
        write_conn.execute.assert_awaited_once()
        execute_sql = write_conn.execute.await_args.args[0]
        assert "posts_count" in execute_sql

    @pytest.mark.asyncio
    async def test_invalidates_cache(self):
        post_id = uuid4()
        agent_did = "did:agentx:achiever-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()
        mock_cache_delete = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=mock_cache_delete,
        ):
            await auto_generate_achievement_post(agent_did, "bounty_won")

        mock_cache_delete.assert_awaited_once()


# ── auto_generate_milestone_post() ────────────────────────────────────────────

class TestAutoGenerateMilestonePost:

    @pytest.mark.asyncio
    async def test_returns_uuid_on_success(self):
        post_id = uuid4()
        agent_did = "did:agentx:milestone-agent-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            result = await auto_generate_milestone_post(agent_did, "first_contract")

        assert isinstance(result, UUID)
        assert result == post_id

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_type(self):
        result = await auto_generate_milestone_post(
            "did:agentx:milestone-agent-001", "totally_unknown_milestone_xyz"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_milestone_post_type(self):
        post_id = uuid4()
        agent_did = "did:agentx:milestone-agent-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_milestone_post(agent_did, "10th_task")

        call_args = write_conn.fetchrow.await_args.args
        assert "MILESTONE" in call_args

    @pytest.mark.asyncio
    async def test_post_is_auto_generated(self):
        post_id = uuid4()
        agent_did = "did:agentx:milestone-agent-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_milestone_post(agent_did, "collective_formed")

        sql_called = write_conn.fetchrow.await_args.args[0]
        # The INSERT includes is_auto_generated = TRUE
        assert "is_auto_generated" in sql_called.lower() or "TRUE" in sql_called

    @pytest.mark.asyncio
    async def test_post_is_public(self):
        post_id = uuid4()
        agent_did = "did:agentx:milestone-agent-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_milestone_post(agent_did, "trust_score_0.9")

        sql_called = write_conn.fetchrow.await_args.args[0]
        assert "PUBLIC" in sql_called


# ── _insert_auto_post() — tested indirectly ───────────────────────────────────

class TestInsertAutoPost:

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        """Any DB exception inside _insert_auto_post must yield None (never raise)."""
        agent_did = "did:agentx:error-prone-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(side_effect=Exception("PG connection lost"))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            result = await auto_generate_achievement_post(agent_did, "bounty_won")

        assert result is None

    @pytest.mark.asyncio
    async def test_checks_agent_status_before_insert(self):
        """Agent status must be checked (via get_db) before attempting INSERT."""
        agent_did = "did:agentx:status-check-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="SUSPENDED")

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ) as mock_get_db:
            result = await auto_generate_achievement_post(agent_did, "bounty_won")

        # Should have checked status
        assert result is None
        read_conn.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_checked_first(self):
        """Rate-limit check must happen BEFORE the DB status query."""
        agent_did = "did:agentx:rate-limited-001"
        call_order: list[str] = []

        import src.services.activity_stream as activity_stream_svc

        async def _fake_rate_limit(did, **kwargs):
            call_order.append("rate_limit")
            return False

        read_conn = AsyncMock()
        async def _fake_fetchval(*args, **kwargs):
            call_order.append("db_status")
            return "ACTIVE"
        read_conn.fetchval = _fake_fetchval

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=_fake_rate_limit,
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ):
            await auto_generate_achievement_post(agent_did, "bounty_won")

        # rate_limit must have been called (and returned False → early exit,
        # so "db_status" should NOT appear)
        assert "rate_limit" in call_order
        assert "db_status" not in call_order

    @pytest.mark.asyncio
    async def test_cache_deleted_after_insert(self):
        """cache_delete must be called once after a successful INSERT."""
        post_id = uuid4()
        agent_did = "did:agentx:cache-test-001"
        mock_cache_delete = AsyncMock()

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=mock_cache_delete,
        ):
            await auto_generate_achievement_post(agent_did, "bounty_won")

        mock_cache_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_posts_count_incremented(self):
        """The agents.posts_count column must be incremented after INSERT."""
        post_id = uuid4()
        agent_did = "did:agentx:count-test-001"

        read_conn = AsyncMock()
        read_conn.fetchval = AsyncMock(return_value="ACTIVE")
        write_conn = AsyncMock()
        write_conn.fetchrow = AsyncMock(return_value=_make_post_row(post_id=post_id))
        write_conn.execute = AsyncMock()

        import src.services.activity_stream as activity_stream_svc

        with patch.object(
            activity_stream_svc,
            "check_auto_post_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "src.services.auto_post.get_db",
            return_value=_db_context(read_conn),
        ), patch(
            "src.services.auto_post.transaction",
            return_value=_tx_context(write_conn),
        ), patch(
            "src.services.auto_post.cache_delete",
            new=AsyncMock(),
        ):
            await auto_generate_milestone_post(agent_did, "first_contract")

        write_conn.execute.assert_awaited_once()
        update_sql = write_conn.execute.await_args.args[0]
        assert "posts_count" in update_sql

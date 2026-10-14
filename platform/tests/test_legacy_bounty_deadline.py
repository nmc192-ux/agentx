"""
Unit tests: bounties stored with no deadline (Phase C, Sprint 21, BT-2).

No database here (tests/integration/test_legacy_bounty_db.py has the money
paths). What is proven:
  • the shipped settings: DEFAULT_BOUNTY_DAYS 30, LEGACY_BOUNTY_DAYS 0 (off)
  • both settings fail closed: anything under 1 (or unreadable) means the
    built-in 30 for the creation default and "off" for the legacy rule
  • the job passes the legacy setting to the bounty query only, None while off
  • with the rule off, release_overdue_bounty refuses a bounty stored with no
    deadline before touching anything else
  • responses report the effective deadline when the query computed one
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.config import Settings, get_settings
from src.jobs import auto_release
from src.services.auto_release import AUTO_RELEASE_DAYS
from src.services.markets import bounty_service
from src.services.markets.bounty_service import DEFAULT_BOUNTY_DAYS, BountyConflictError


class TestShippedDefaults:

    def test_default_bounty_days_is_30(self):
        assert Settings.model_fields["default_bounty_days"].default == DEFAULT_BOUNTY_DAYS == 30

    def test_the_legacy_rule_ships_off(self):
        assert Settings.model_fields["legacy_bounty_days"].default == 0


class TestSettingsFailClosed:

    @pytest.mark.parametrize("value", [0, -1, None, "x", ""])
    def test_an_unusable_default_means_the_built_in_30(self, monkeypatch, value):
        monkeypatch.setattr(get_settings(), "default_bounty_days", value)
        assert bounty_service.default_bounty_days() == DEFAULT_BOUNTY_DAYS

    @pytest.mark.parametrize("value, expected", [(12, 12), ("45", 45), (1, 1)])
    def test_a_usable_default_is_used(self, monkeypatch, value, expected):
        monkeypatch.setattr(get_settings(), "default_bounty_days", value)
        assert bounty_service.default_bounty_days() == expected

    @pytest.mark.parametrize("value", [0, -1, None, "x", "", -30])
    def test_an_unusable_legacy_value_means_off(self, monkeypatch, value):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", value)
        assert bounty_service.legacy_bounty_days() is None

    @pytest.mark.parametrize("value, expected", [(30, 30), ("10", 10), (1, 1)])
    def test_a_usable_legacy_value_is_used(self, monkeypatch, value, expected):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", value)
        assert bounty_service.legacy_bounty_days() == expected


class TestJobParameters:

    @pytest.mark.parametrize("query", [auto_release._DUE_TASKS, auto_release._DUE_CONTRACTS])
    def test_tasks_and_contracts_take_three_parameters(self, monkeypatch, query):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", 30)
        assert auto_release._query_params(query, 7) == [
            AUTO_RELEASE_DAYS, auto_release.BATCH_LIMIT, 7]

    def test_bounties_take_the_legacy_setting_none_while_off(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", 0)
        assert auto_release._query_params(auto_release._DUE_BOUNTIES, 0) == [
            AUTO_RELEASE_DAYS, auto_release.BATCH_LIMIT, 0, None]
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", 30)
        assert auto_release._query_params(auto_release._DUE_BOUNTIES, 0)[3] == 30

    @pytest.mark.asyncio
    async def test_due_ids_sends_exactly_those_parameters(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", 30)
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(auto_release, "get_db", lambda: ctx)

        await auto_release._due_ids(auto_release._DUE_BOUNTIES, 3)
        assert conn.fetch.await_args.args == (
            auto_release._DUE_BOUNTIES, AUTO_RELEASE_DAYS, auto_release.BATCH_LIMIT, 3, 30)
        await auto_release._due_ids(auto_release._DUE_TASKS, 0)
        assert conn.fetch.await_args.args == (
            auto_release._DUE_TASKS, AUTO_RELEASE_DAYS, auto_release.BATCH_LIMIT, 0)

    def test_the_bounty_query_reads_the_effective_deadline(self):
        q = auto_release._DUE_BOUNTIES
        assert "COALESCE(deadline, created_at + make_interval(days => $4))" in q
        assert "$1" in q and "$2" in q and "$3" in q


class _Row(dict):
    """Enough of an asyncpg Record for the service: mapping + .get + .keys."""


class TestReleaseRefusesWithoutADeadline:

    @pytest.mark.asyncio
    async def test_no_deadline_and_the_rule_off_moves_nothing(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "legacy_bounty_days", 0)
        row = _Row(
            bounty_id=uuid4(), creator_did="did:x", creator_id=uuid4(), title="t",
            description="", capability_required="c", reward_pool=100, status="open",
            deadline=None, winner_submission_id=None,
            created_at=datetime.now(timezone.utc) - timedelta(days=4000), closed_at=None,
            effective_deadline=None, due=None,
        )
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.fetchval = AsyncMock()
        conn.fetch = AsyncMock()
        conn.execute = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr(bounty_service, "transaction", lambda: ctx)

        with pytest.raises(BountyConflictError, match="no deadline"):
            await bounty_service.release_overdue_bounty(row["bounty_id"])
        # One locked read, then the refusal: no winner lookup, no update, no payout.
        assert conn.fetchrow.await_count == 1
        assert conn.fetchrow.await_args.args[2:] == (AUTO_RELEASE_DAYS, None)
        conn.fetchval.assert_not_awaited()
        conn.fetch.assert_not_awaited()
        conn.execute.assert_not_awaited()


class TestResponseDeadline:

    def _row(self, **over):
        base = dict(
            bounty_id=uuid4(), creator_did="did:x", creator_id=None, title="t",
            description="", capability_required="c", reward_pool=1, status="open",
            deadline=None, winner_submission_id=None,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc), closed_at=None,
        )
        base.update(over)
        return _Row(base)

    def test_a_stored_deadline_is_reported_as_is(self):
        stored = datetime(2025, 2, 1, tzinfo=timezone.utc)
        other = datetime(2025, 3, 1, tzinfo=timezone.utc)
        row = self._row(deadline=stored, effective_deadline=other)
        assert bounty_service._row_to_bounty(row).deadline == stored

    def test_the_effective_deadline_fills_a_missing_one(self):
        eff = datetime(2025, 1, 31, tzinfo=timezone.utc)
        assert bounty_service._row_to_bounty(self._row(effective_deadline=eff)).deadline == eff

    def test_none_stays_none_when_the_rule_is_off_or_not_computed(self):
        assert bounty_service._row_to_bounty(self._row(effective_deadline=None)).deadline is None
        assert bounty_service._row_to_bounty(self._row()).deadline is None

"""Unit tests: week arithmetic of services/spotlight_service.py (S17-2)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.services import spotlight_service as spot


@pytest.mark.parametrize("day", [date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 11)])
def test_week_start_is_the_monday(day):
    assert spot.week_start_of(day) == date(2026, 10, 5)
    assert spot.week_bounds(day) == (date(2026, 10, 5), date(2026, 10, 12))


def test_week_start_uses_utc_for_aware_datetimes():
    # Monday 02:41 in Karachi is still Sunday in UTC.
    karachi = timezone(timedelta(hours=5))
    assert spot.week_start_of(datetime(2026, 10, 5, 2, 41, tzinfo=karachi)) == date(2026, 9, 28)


def test_scoring_window_is_the_previous_week_in_utc():
    lo, hi = spot.scoring_window(date(2026, 10, 12))
    assert lo == datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert hi == datetime(2026, 10, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", [date(2026, 10, 13), datetime(2026, 10, 12), "2026-10-12"])
def test_scoring_window_refuses_non_mondays(bad):
    with pytest.raises((ValueError, TypeError)):
        spot.scoring_window(bad)

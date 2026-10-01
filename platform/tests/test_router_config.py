"""
Tests: src/router_config.py — repo-default router gating.

Pins the Sprint 9 dispositions for `nodes` (S9-2) and `consensus` (S9-3):
both stay disabled by default until the reasons recorded next to them in
router_config.py are resolved. Removing either from the default list should
be a deliberate change that also updates this test.
"""
from __future__ import annotations

import pytest

from src.config import Settings
from src.router_config import (
    BROKEN_OR_INSECURE_ROUTERS,
    DEFAULT_DISABLED_ROUTERS,
    default_disabled_routers_csv,
)


@pytest.mark.parametrize("name", ["nodes", "consensus"])
def test_kept_off_routers_are_disabled_by_default(name):
    assert name in BROKEN_OR_INSECURE_ROUTERS
    assert name in DEFAULT_DISABLED_ROUTERS


def test_default_list_has_no_duplicates():
    assert len(DEFAULT_DISABLED_ROUTERS) == len(set(DEFAULT_DISABLED_ROUTERS))


@pytest.mark.parametrize("name", ["nodes", "consensus"])
def test_settings_default_disables_kept_off_routers(name, monkeypatch):
    """With no DISABLED_ROUTERS env override, the repo default applies."""
    monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.disabled_routers == default_disabled_routers_csv()
    assert name in settings.disabled_router_set

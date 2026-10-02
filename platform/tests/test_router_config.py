"""
Tests: src/router_config.py — repo-default router gating.

Pins the Sprint 9 dispositions for `nodes` (S9-2) and `consensus` (S9-3):
both stay disabled by default until the reasons recorded next to them in
router_config.py are resolved. Removing either from the default list should
be a deliberate change that also updates this test.

Also pins the Tier A lock (S9-4a): the DISABLED_ROUTERS env override cannot
switch a broken/insecure router on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.config import Settings
from src.router_config import (
    BROKEN_OR_INSECURE_ROUTERS,
    DEFAULT_DISABLED_ROUTERS,
    ENABLED_IN_SPRINT_9,
    default_disabled_routers_csv,
    effective_disabled_routers,
)

PLATFORM_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["nodes", "consensus"])
def test_kept_off_routers_are_disabled_by_default(name):
    assert name in BROKEN_OR_INSECURE_ROUTERS
    assert name in DEFAULT_DISABLED_ROUTERS


def test_default_list_has_no_duplicates():
    assert len(DEFAULT_DISABLED_ROUTERS) == len(set(DEFAULT_DISABLED_ROUTERS))


# ── S9-5: cohort 1 (social) is on in the repo default ─────────────────────────

SOCIAL_COHORT = ["memory", "graph", "rooms", "communities", "conversations", "channels", "pulse"]


@pytest.mark.parametrize("name", SOCIAL_COHORT)
def test_social_cohort_enabled_by_default(name, monkeypatch):
    assert name in ENABLED_IN_SPRINT_9
    assert name not in DEFAULT_DISABLED_ROUTERS
    monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    assert Settings(_env_file=None).router_enabled(name)


def test_enabled_routers_are_not_also_listed_as_disabled():
    assert not set(ENABLED_IN_SPRINT_9) & set(DEFAULT_DISABLED_ROUTERS)


def test_full_production_env_value_still_disables_the_social_cohort(monkeypatch):
    """Production keeps its Fly override until H3, so nothing changes there on merge."""
    prod = ("agent_economy,nodes,governance,consensus,graph,tasks,collectives,communities,"
            "contracts,wallets,stakes,economy,agentbus,verifications,markets,conversations,"
            "channels,rooms,pulse,memory")
    monkeypatch.setenv("DISABLED_ROUTERS", prod)
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    settings = Settings(_env_file=None)
    assert not any(
        settings.router_enabled(n)
        for n in SOCIAL_COHORT + WORK_COHORT_ENABLED + MONEY_COHORT_ENABLED
    )


# ── S9-6: cohort 2 (work) — only the routers whose writes passed review ───────

# tasks: S9-6a; contracts + verifications: S9-6b; markets: S9-6c
WORK_COHORT_ENABLED = ["collectives", "agentbus", "tasks", "contracts", "verifications", "markets"]


@pytest.mark.parametrize("name", WORK_COHORT_ENABLED)
def test_work_cohort_enabled_by_default(name, monkeypatch):
    assert name in ENABLED_IN_SPRINT_9
    assert name not in DEFAULT_DISABLED_ROUTERS
    monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    assert Settings(_env_file=None).router_enabled(name)


def test_fixed_work_routers_can_still_be_switched_off_by_the_kill_switch(monkeypatch):
    """Leaving Tier A does not take a router out of reach of the emergency brake."""
    monkeypatch.setenv("DISABLED_ROUTERS", "tasks,contracts,verifications,markets")
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    settings = Settings(_env_file=None)
    assert not any(
        settings.router_enabled(n) for n in ["tasks", "contracts", "verifications", "markets"]
    )


# ── S9-7a: cohort 3 (money) — the token stack, after its fixes ────────────────

# wallets, stakes, economy: S9-7a; agent_economy (was Tier A): S9-7c
MONEY_COHORT_ENABLED = ["wallets", "stakes", "economy", "agent_economy"]


@pytest.mark.parametrize("name", MONEY_COHORT_ENABLED)
def test_money_cohort_enabled_by_default(name, monkeypatch):
    assert name in ENABLED_IN_SPRINT_9
    assert name not in DEFAULT_DISABLED_ROUTERS
    monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    assert Settings(_env_file=None).router_enabled(name)


def test_money_routers_can_still_be_switched_off_by_the_kill_switch(monkeypatch):
    monkeypatch.setenv("DISABLED_ROUTERS", "wallets,stakes,economy,agent_economy")
    monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    settings = Settings(_env_file=None)
    assert not any(settings.router_enabled(n) for n in MONEY_COHORT_ENABLED)


def test_repo_default_now_disables_tier_a_only(monkeypatch):
    """Tier B and Tier C are empty: everything still off is off for a reason
    written next to it in router_config.py."""
    assert set(DEFAULT_DISABLED_ROUTERS) == set(BROKEN_OR_INSECURE_ROUTERS)
    assert set(BROKEN_OR_INSECURE_ROUTERS) == {"nodes", "governance", "consensus"}


@pytest.mark.parametrize("name", ["nodes", "consensus"])
def test_settings_default_disables_kept_off_routers(name, monkeypatch):
    """With no DISABLED_ROUTERS env override, the repo default applies."""
    monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.disabled_routers == default_disabled_routers_csv()
    assert name in settings.disabled_router_set


# ── S9-4a: the env kill-switch can switch routers OFF, never Tier A ON ────────
#
# DISABLED_ROUTERS replaces the repo list, so a short emergency value used to
# enable every router it left out — including the broken/insecure ones.

TIER_A = sorted(BROKEN_OR_INSECURE_ROUTERS)


def _settings(monkeypatch, disabled, allow_unsafe=None, **kwargs):
    """Settings built from the environment, as the app builds them."""
    if disabled is None:
        monkeypatch.delenv("DISABLED_ROUTERS", raising=False)
    else:
        monkeypatch.setenv("DISABLED_ROUTERS", disabled)
    if allow_unsafe is None:
        monkeypatch.delenv("ALLOW_UNSAFE_ROUTERS", raising=False)
    else:
        monkeypatch.setenv("ALLOW_UNSAFE_ROUTERS", allow_unsafe)
    return Settings(_env_file=None, **kwargs)


def test_tier_a_is_what_the_plan_says_it_protects():
    assert {"nodes", "consensus"} <= set(BROKEN_OR_INSECURE_ROUTERS)
    # S9-6: token holes found in review. tasks left in S9-6a, contracts in
    # S9-6b and markets in S9-6c (all fixed).
    assert "tasks" not in BROKEN_OR_INSECURE_ROUTERS
    assert "contracts" not in BROKEN_OR_INSECURE_ROUTERS
    assert "markets" not in BROKEN_OR_INSECURE_ROUTERS
    # /markets/bounties/auto lives in agent_economy: reviewed and cleared in
    # S9-7c (tests/integration/test_agent_economy_db.py).
    assert "agent_economy" not in BROKEN_OR_INSECURE_ROUTERS


@pytest.mark.parametrize("env_value", ["posts", "contracts,rooms,governance", "", " , "])
@pytest.mark.parametrize("name", TIER_A)
def test_short_env_override_cannot_enable_tier_a(name, env_value, monkeypatch):
    settings = _settings(monkeypatch, env_value)
    assert name in settings.disabled_router_set
    assert not settings.router_enabled(name)
    assert not settings.router_enabled(f"  {name.upper()} ")


def test_env_override_still_switches_routers_off(monkeypatch):
    """The kill-switch itself keeps working: a named router goes off."""
    settings = _settings(monkeypatch, "posts")
    assert not settings.router_enabled("posts")


def test_env_override_still_replaces_the_non_tier_a_part(monkeypatch):
    """Only Tier A is locked. Tier B/C routers left out of the env value are
    enabled, as before — that is how H3 / an env-driven rollout works."""
    settings = _settings(monkeypatch, "posts")
    assert settings.router_enabled("wallets")
    assert settings.router_enabled("memory")
    assert settings.disabled_router_set == {"posts"} | set(BROKEN_OR_INSECURE_ROUTERS)


def test_lock_reports_which_routers_it_forced_off(monkeypatch):
    settings = _settings(monkeypatch, "posts,nodes")
    assert settings.tier_a_locked_routers == set(BROKEN_OR_INSECURE_ROUTERS) - {"nodes"}
    # Normal path: the repo default already names every Tier A router.
    assert _settings(monkeypatch, None).tier_a_locked_routers == set()


def test_repo_default_is_unchanged_by_the_lock(monkeypatch):
    settings = _settings(monkeypatch, None)
    assert settings.disabled_router_set == set(DEFAULT_DISABLED_ROUTERS)


@pytest.mark.parametrize("name", TIER_A)
def test_dev_opt_out_lifts_the_lock_in_development(name, monkeypatch):
    """What conftest.py and the smoke harness rely on."""
    settings = _settings(monkeypatch, "", allow_unsafe="1", app_env="development")
    assert settings.unsafe_routers_unlocked
    assert settings.router_enabled(name)


@pytest.mark.parametrize("app_env", ["production", "staging"])
@pytest.mark.parametrize("name", TIER_A)
def test_opt_out_is_ignored_outside_development(name, app_env, monkeypatch):
    """Fail closed: the opt-out flag does nothing in staging or production."""
    settings = _settings(monkeypatch, "posts", allow_unsafe="1", app_env=app_env)
    assert settings.unsafe_routers_requested
    assert not settings.unsafe_routers_unlocked
    assert not settings.router_enabled(name)


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "2", "enable"])
def test_unrecognised_opt_out_values_keep_the_lock(value, monkeypatch):
    """Only 1/true/yes lift the lock; a typo must neither unlock nor crash."""
    settings = _settings(monkeypatch, "posts", allow_unsafe=value, app_env="development")
    assert not settings.unsafe_routers_unlocked
    assert set(BROKEN_OR_INSECURE_ROUTERS) <= settings.disabled_router_set


def test_effective_disabled_routers_helper():
    assert effective_disabled_routers({"posts"}) == {"posts"} | set(BROKEN_OR_INSECURE_ROUTERS)
    assert effective_disabled_routers(set()) == set(BROKEN_OR_INSECURE_ROUTERS)
    assert effective_disabled_routers({"posts"}, unlock_tier_a=True) == {"posts"}


def _mounted_routes(env_overrides: dict[str, str], unset: tuple[str, ...] = ()) -> set[tuple[str, str]]:
    """Import the real app in a fresh process and return its (METHOD, path) set."""
    env = {k: v for k, v in os.environ.items() if k not in unset}
    env.update(env_overrides)
    code = (
        "import json, src.main as m\n"
        "print('ROUTES=' + json.dumps(sorted("
        "[meth, r.path] for r in m.app.routes for meth in (getattr(r, 'methods', None) or []))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PLATFORM_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(ln for ln in reversed(result.stdout.splitlines()) if ln.startswith("ROUTES="))
    return {(meth, path) for meth, path in json.loads(line[len("ROUTES="):])}


def _own_routes(router) -> set[tuple[str, str]]:
    return {(meth, r.path) for r in router.routes for meth in (r.methods or [])}


def test_app_does_not_mount_tier_a_under_a_short_env_override():
    """End to end: boot the real app with DISABLED_ROUTERS=posts and no opt-out.
    No Tier A route may be mounted; an unlocked router (wallets) still is."""
    from src.routers.agent_economy import agent_economy_router
    from src.routers.consensus import consensus_router
    from src.routers.contracts import contracts_router
    from src.routers.governance import governance_router
    from src.routers.markets import markets_router
    from src.routers.node_router import nodes_router
    from src.routers.tasks import router as tasks_router
    from src.routers.tokens import wallets_router

    routers = {
        "agent_economy": agent_economy_router,
        "nodes": nodes_router,
        "governance": governance_router,
        "consensus": consensus_router,
        "tasks": tasks_router,
        "contracts": contracts_router,
        "markets": markets_router,
    }
    mounted = _mounted_routes({"DISABLED_ROUTERS": "posts"}, unset=("ALLOW_UNSAFE_ROUTERS",))
    for name in BROKEN_OR_INSECURE_ROUTERS:
        own = _own_routes(routers[name])
        assert own, name
        assert not (own & mounted), f"Tier A router {name!r} is mounted: {sorted(own & mounted)}"
    assert _own_routes(wallets_router) <= mounted
    # Left Tier A in S9-7c: mounted like any other unlocked router.
    assert _own_routes(agent_economy_router) <= mounted

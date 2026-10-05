"""
Guard: Fly runs database migrations on deploy only if `release_command` sits
under `[deploy]` in the Fly config. At the top level Fly ignores it without an
error, which is how production stayed on alembic_version 001 through the
4 Oct 2026 deploy (v137) while every check stayed green.

The engine may not edit the Fly config files (standing rule 6). DrJ fixed both
files (HUMAN_ACTIONS H18, PR 13, 5 Oct 2026), so this test is now a hard guard:
it fails CI (and so blocks the deploy) if the command ever moves out of
[deploy] again.
"""
import tomllib
from pathlib import Path

import pytest

_PLATFORM = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["fly.toml", "fly.staging.toml"])
def test_release_command_runs_migrations_on_deploy(name):
    config = tomllib.loads((_PLATFORM / name).read_text())
    assert "release_command" not in config, "top-level release_command is ignored by Fly"
    assert config.get("deploy", {}).get("release_command") == "alembic upgrade head"

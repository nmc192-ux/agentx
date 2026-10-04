"""
Guard: Fly runs database migrations on deploy only if `release_command` sits
under `[deploy]` in the Fly config. At the top level Fly ignores it without an
error, which is how production stayed on alembic_version 001 through the
4 Oct 2026 deploy (v137) while every check stayed green.

The engine may not edit the Fly config files (standing rule 6). DrJ's fix is
HUMAN_ACTIONS H18. Once it is on this branch the engine deletes the xfail
marker below; from then on this test fails CI (and so blocks the deploy) if the
command ever moves out of [deploy] again.
"""
import tomllib
from pathlib import Path

import pytest

_PLATFORM = Path(__file__).resolve().parent.parent


@pytest.mark.xfail(reason="H18: release_command is still top-level in the Fly config", strict=False)
@pytest.mark.parametrize("name", ["fly.toml", "fly.staging.toml"])
def test_release_command_runs_migrations_on_deploy(name):
    config = tomllib.loads((_PLATFORM / name).read_text())
    assert "release_command" not in config, "top-level release_command is ignored by Fly"
    assert config.get("deploy", {}).get("release_command") == "alembic upgrade head"

"""The SDK's default address is the stable public API (DrJ, 4 Oct 2026).

Agents that never pass ``base_url`` must reach https://api.agentx.social, an
address we own, so the backend can move off Fly.io by repointing DNS. These
fail if a default ever names Fly, localhost or plain http again.
"""
import inspect
import re
from pathlib import Path

import pytest

from agentx_sdk import AgentClient, AgentXClient
from agentx_sdk.config import DEFAULT_BASE_URL, AgentXConfig

STABLE = "https://api.agentx.social"
FORBIDDEN = ("fly.dev", "localhost", "127.0.0.1", "http://")
SDK_ROOT = Path(__file__).resolve().parents[1]


def _assert_clean(value: str) -> None:
    for bad in FORBIDDEN:
        assert bad not in value, f"{value!r} contains {bad!r}"


def test_the_default_is_the_stable_address():
    assert DEFAULT_BASE_URL == STABLE
    assert AgentXConfig(api_key="k").base_url == STABLE


@pytest.mark.parametrize("func", [
    AgentClient.__init__, AgentXClient.__init__, AgentXClient.onboard,
])
def test_every_entry_point_defaults_to_the_stable_address(func):
    default = inspect.signature(func).parameters["base_url"].default
    assert default == STABLE
    _assert_clean(default)


def test_the_typescript_client_defaults_to_the_stable_address():
    ts = (SDK_ROOT / "ts" / "AgentXClient.ts").read_text()
    defaults = re.findall(r'options\.baseUrl \?\? "([^"]+)"', ts)
    assert defaults == [STABLE]


@pytest.mark.parametrize("path", [
    "examples/quickstart.py", "example_agent.py",
    "examples/economic_loop_demo.py", "examples/multi_agent_collab.py",
])
def test_sample_agents_default_to_the_stable_address(path):
    src = (SDK_ROOT / path).read_text()
    defaults = re.findall(r'os\.environ\.get\("AGENTX_BASE_URL", "([^"]+)"\)', src)
    assert defaults == [STABLE]

"""The SDK's default address is the stable public API.

Agents that never pass ``base_url`` must reach https://api.agentx.social, an
address we own, so the backend can move hosts by repointing DNS. These fail if
a default ever names a hosting provider's address, localhost or plain http.
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
    ts = "".join(p.read_text() for p in sorted((SDK_ROOT / "ts" / "src").glob("*.ts")))
    defaults = re.findall(r'options\.baseUrl \?\? "([^"]+)"', ts)
    assert defaults and set(defaults) == {STABLE}


@pytest.mark.parametrize("path", [
    "examples/quickstart.py", "example_agent.py",
    "examples/economic_loop_demo.py", "examples/multi_agent_collab.py",
])
def test_sample_agents_default_to_the_stable_address(path):
    src = (SDK_ROOT / path).read_text()
    defaults = re.findall(r'os\.environ\.get\("AGENTX_BASE_URL", "([^"]+)"\)', src)
    assert defaults == [STABLE]

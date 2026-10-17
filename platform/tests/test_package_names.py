"""
Tests: the package names AgentX publishes under (cycle 263, DrJ's note).

`agentx` and `agentx-sdk` on PyPI, `agentx-mcp` on PyPI and npm, and the npm organisation
`@agentx` belong to other owners. An install line that names one of them would hand a newcomer
someone else's code, so every live surface must use `agentx-social`, `agentx-social-mcp` and
`@agentx-social/sdk`. History (old briefings, retros, the old launch-day runbook, the engine log)
is left as it was and is not scanned.
"""
import re
import tomllib
import json
from pathlib import Path

from src.a2a import skill

REPO = Path(__file__).resolve().parents[2]

# Files a newcomer or DrJ follows today.
LIVE = [
    "README.md",
    "sdk/README.md",
    "sdk/mcp/README.md",
    "sdk/ts/README.md",
    "sdk/examples/quickstart.py",
    "agentx-examples/README.md",
    "agentx-examples/requirements.txt",
    "agentx-examples/ts/README.md",
    "agentx-examples/ts/package.json",
    "packaging/agentx-client/README.md",
    "packaging/agentx-client/pyproject.toml",
    "platform/docs/quickstart.md",
    "platform/docs/execution/early_launch_runbook.md",
    "skills/agentx/README.md",
    "skills/agentx/SKILL.md",
    "ui/app/join/page.tsx",
    "ui/app/welcome/page.tsx",
    "ui/components/layout/Footer.tsx",
]

# An install or import of a name we do not own.
FOREIGN = [
    re.compile(r"pip install\s+[\"']?agentx(-py|-sdk|-mcp)?[\"'\s>=<]"),
    re.compile(r"pip install\s+[\"']?agentx(-py|-sdk|-mcp)?$", re.M),
    re.compile(r"uvx\s+agentx-mcp\b"),
    re.compile(r"[\"']agentx-mcp(@[\d.]+)?[\"']"),
    re.compile(r"npm install\s+agentx-mcp\b"),
    re.compile(r"@agentx/(sdk|mcp)\b"),
    re.compile(r"pypi\.org/project/agentx(-py|-sdk|-mcp)?/"),
    re.compile(r"npmjs\.com/(org/agentx(?![\w-])|package/@agentx/)"),
]


def _hits(text: str) -> list[str]:
    return [m.group(0) for rx in FOREIGN for m in rx.finditer(text)]


def test_patterns_catch_the_old_names():
    for bad in ("pip install agentx-py", 'pip install "agentx-py>=0.4.0"', "pip install agentx",
                "uvx agentx-mcp@0.1.0", '"args": ["agentx-mcp"]', "npm install @agentx/sdk",
                "https://pypi.org/project/agentx-py/", "https://www.npmjs.com/org/agentx "):
        assert _hits(bad), bad
    for good in ("pip install agentx-social", 'pip install "agentx-social>=0.4.0"',
                 "uvx agentx-social-mcp@0.1.0", "npm install @agentx-social/sdk",
                 "https://pypi.org/project/agentx-social/", "https://www.npmjs.com/org/agentx-social"):
        assert not _hits(good), good


def test_live_files_name_only_our_packages():
    found = {}
    for rel in LIVE:
        path = REPO / rel
        if path.exists():
            hits = _hits(path.read_text())
            if hits:
                found[rel] = hits
    assert not found, found


def test_skill_md_and_constants_use_our_names():
    assert skill.PYTHON_SDK[0] == "agentx-social"
    assert skill.TS_SDK[0] == "@agentx-social/sdk"
    assert skill.MCP_SERVER[0] == "agentx-social-mcp"


def test_package_files_carry_the_new_names_and_old_imports():
    sdk = tomllib.loads((REPO / "sdk" / "pyproject.toml").read_text())
    assert sdk["project"]["name"] == "agentx-social"
    # Import names unchanged.
    assert sdk["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["agentx_sdk", "agentx"]
    mcp = tomllib.loads((REPO / "sdk" / "mcp" / "pyproject.toml").read_text())
    assert mcp["project"]["name"] == "agentx-social-mcp"
    # The command matches the package, so `uvx agentx-social-mcp` runs it; no `agentx-mcp`
    # command that could be confused with the other project's.
    assert mcp["project"]["scripts"] == {"agentx-social-mcp": "agentx_mcp.server:main"}
    ts = json.loads((REPO / "sdk" / "ts" / "package.json").read_text())
    assert ts["name"] == "@agentx-social/sdk"
    shim = tomllib.loads((REPO / "packaging" / "agentx-client" / "pyproject.toml").read_text())
    assert shim["project"]["dependencies"] == ["agentx-social>=0.4.0"]


def test_runbook_states_the_publish_secrets():
    text = (REPO / "platform" / "docs" / "execution" / "early_launch_runbook.md").read_text()
    assert "GitHub secrets the publish steps need: none." in text
    assert "pending publisher" in text and "`publish-sdk.yml`" in text
    assert "docker network connect agentx_edge pinkpopcorn-feed-caddy-1" in text

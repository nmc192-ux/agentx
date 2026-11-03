"""OSS-2: every published package points to the public repo, never the private one."""
import json
import re
import tomllib
from pathlib import Path

SDK = Path(__file__).resolve().parents[2] / "sdk"
PUBLIC = "https://github.com/nmc192-ux/agentx-sdk"
PRIVATE = re.compile(r"nmc192-ux/agentx(?!-sdk)\b")


def _urls(pyproject: Path) -> dict[str, str]:
    return tomllib.loads(pyproject.read_text())["project"]["urls"]


def test_python_packages_link_the_public_repo():
    for pyproject in (SDK / "pyproject.toml", SDK / "mcp" / "pyproject.toml"):
        urls = _urls(pyproject)
        assert urls["Homepage"] == "https://agentx.social"
        assert urls["Documentation"] == "https://agentx.social/developer"
        assert urls["Repository"] == PUBLIC
        assert urls["Issues"] == f"{PUBLIC}/issues"
        assert urls["Changelog"].startswith(f"{PUBLIC}/blob/main/sdk/")


def test_ts_package_links_the_public_repo():
    pkg = json.loads((SDK / "ts" / "package.json").read_text())
    assert pkg["homepage"] == "https://agentx.social"
    assert pkg["repository"] == {"type": "git", "url": f"git+{PUBLIC}.git", "directory": "sdk/ts"}
    assert pkg["bugs"] == {"url": f"{PUBLIC}/issues"}


def test_patch_versions_agree():
    assert tomllib.loads((SDK / "pyproject.toml").read_text())["project"]["version"] == "0.5.0"
    assert tomllib.loads((SDK / "mcp" / "pyproject.toml").read_text())["project"]["version"] == "0.2.0"
    assert '__version__ = "0.2.0"' in (SDK / "mcp" / "src" / "agentx_mcp" / "__init__.py").read_text()
    ts = SDK / "ts"
    assert json.loads((ts / "package.json").read_text())["version"] == "0.2.0"
    assert json.loads((ts / "package-lock.json").read_text())["version"] == "0.2.0"
    assert 'export const VERSION = "0.2.0";' in (ts / "src" / "index.ts").read_text()


def test_no_package_file_names_the_private_repo():
    files = [SDK / "pyproject.toml", SDK / "README.md", SDK / "CHANGELOG.md"]
    for sub in ("mcp", "ts"):
        files += [SDK / sub / n for n in ("README.md", "CHANGELOG.md", "LICENSE")]
    files += [SDK / "mcp" / "pyproject.toml", SDK / "ts" / "package.json"]
    for f in files:
        assert not PRIVATE.search(f.read_text()), f

"""OSS-1: the public SDK export (scripts/export_public_sdk.sh) is clean and repeatable.

Runs the export into a temp folder twice, checks the two trees are identical, that nothing
outside the allow-list or on the deny-list got in, and that the internal-details scan
(scripts/scan_public_sdk.py) finds nothing.
"""
import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / "scripts" / "export_public_sdk.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(), reason="needs a git checkout"
)


def _export(out: Path) -> None:
    subprocess.run(["bash", str(EXPORT), str(out)], check=True, capture_output=True, text=True)


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _scanner():
    spec = importlib.util.spec_from_file_location("scan_public_sdk", REPO / "scripts" / "scan_public_sdk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    out = tmp_path_factory.mktemp("export") / "agentx-sdk"
    _export(out)
    return out


def test_export_is_repeatable(export, tmp_path):
    again = tmp_path / "again"
    _export(again)
    assert _tree(export) == _tree(again)


def test_only_allowed_folders_and_root_files(export):
    files = _tree(export)
    top = {f for f in files if "/" not in f}
    assert top == {"README.md", "LICENSE", ".gitignore"}
    assert all(f.startswith(("sdk/", "skills/agentx/", ".github/workflows/")) for f in files if "/" in f)
    assert sorted(f for f in files if f.startswith(".github/")) == [
        ".github/workflows/publish-mcp.yml",
        ".github/workflows/publish-python-sdk.yml",
        ".github/workflows/publish-ts-sdk.yml",
    ]
    assert "Apache License" in (export / "LICENSE").read_text()
    for pkg in ("sdk", "sdk/ts", "sdk/mcp"):
        assert "MIT License" in (export / pkg / "LICENSE").read_text(), pkg


def test_nothing_private_or_built_got_in(export):
    for f in _tree(export):
        parts = f.split("/")
        assert not any(p.startswith(".env") for p in parts), f
        assert not {"node_modules", "dist", "__pycache__", ".venv"} & set(parts), f
        assert not f.endswith((".pyc", ".whl", ".tgz")), f
    assert not (export / "sdk/tests/test_agentx_client_shim.py").exists()


def test_internal_details_scan_is_clean(export):
    bad, _ok = _scanner().scan(export)
    assert bad == []


def test_scanner_catches_planted_details(tmp_path):
    (tmp_path / "a.md").write_text(
        "see ../platform/docs/x.md and host agentx-api.fly.dev at 10.0.0.7\n"
        "ask DrJ at someone@gmail.com; key AKIAABCDEFGHIJKLMNOP\n"
        "[runner](../runners/sdk_agent_runner.py) postgres://u:pw@db/x\n"
    )
    rules = {line.split(": ")[1] for line in _scanner().scan(tmp_path)[0]}
    assert {
        "internal/platform-path", "internal/fly.dev", "internal/ipv4", "internal/internal-name",
        "internal/email", "secret/aws-key", "internal/link-out-of-package", "internal/private-folder",
        "secret/db-url-with-password",
    } <= rules


def test_refuses_to_export_into_the_repo():
    r = subprocess.run(["bash", str(EXPORT), str(REPO / "tmp-export")], capture_output=True, text=True)
    assert r.returncode == 2
    assert not (REPO / "tmp-export").exists()


def test_publish_workflows_are_valid_and_tag_gated(export):
    import yaml
    for f in (export / ".github/workflows").glob("*.yml"):
        doc = yaml.safe_load(f.read_text())
        tags = doc[True]["push"]["tags"]  # YAML reads the key `on` as True
        assert len(tags) == 1 and tags[0].endswith("-v*"), f.name
        assert "branches" not in doc[True]["push"], f.name

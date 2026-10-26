"""Pack check for the TypeScript SDK (Sprint 14, S14-8).

Packs `sdk/ts` into a tarball, checks it holds only the allowed files, installs it into a
scratch project and proves that `import`, `require` and the types all resolve. The
TypeScript examples in `sdk/ts/README.md` are type-checked under `--strict` against the
installed package. Skipped when node/npm (Node >= 22.18) are unavailable or the dev
dependencies are not installed (`npm ci` in sdk/ts).
"""

import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

TS_DIR = Path(__file__).resolve().parents[1] / "ts"
TSC = TS_DIR / "node_modules" / ".bin" / "tsc"
ALLOWED_TOP = {"package.json", "README.md", "LICENSE", "CHANGELOG.md"}


def _tool(name: str) -> str | None:
    return shutil.which(name) or shutil.which(f"/opt/homebrew/bin/{name}")


@pytest.fixture(scope="module")
def packed(tmp_path_factory):
    node, npm = _tool("node"), _tool("npm")
    if not node or not npm or not TSC.exists():
        pytest.skip("node/npm or sdk/ts devDependencies not available")
    dest = tmp_path_factory.mktemp("pack")
    proc = subprocess.run(
        [npm, "pack", "--json", "--pack-destination", str(dest)],
        capture_output=True, text=True, timeout=300, cwd=TS_DIR,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    info = json.loads(proc.stdout)[0]
    return node, npm, dest / info["filename"], dest


def test_tarball_contains_only_allowed_files(packed):
    _, _, tarball, _ = packed
    with tarfile.open(tarball) as tar:
        names = [m.name.removeprefix("package/") for m in tar.getmembers() if m.isfile()]
    assert names
    for name in names:
        assert name.startswith("dist/") or name in ALLOWED_TOP, f"unexpected file in package: {name}"
    for required in ("package.json", "README.md", "LICENSE", "CHANGELOG.md", "dist/esm/index.js",
                     "dist/esm/index.d.ts", "dist/cjs/index.js", "dist/cjs/index.d.ts",
                     "dist/cjs/package.json"):
        assert required in names, f"missing from package: {required}"
    assert not any(n.startswith(("src/", "test/", "node_modules/")) for n in names)
    assert not any(n.endswith(".map") and "secret" in n for n in names)


@pytest.fixture(scope="module")
def scratch(packed, tmp_path_factory):
    node, npm, tarball, _ = packed
    d = tmp_path_factory.mktemp("scratch")
    (d / "package.json").write_text(json.dumps({"name": "scratch", "private": True, "type": "module"}))
    proc = subprocess.run(
        [npm, "install", str(tarball), "--no-audit", "--no-fund", "--offline"],
        capture_output=True, text=True, timeout=300, cwd=d,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (d / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "target": "ES2022", "module": "NodeNext", "moduleResolution": "NodeNext",
            "strict": True, "noEmit": True, "skipLibCheck": False,
            "typeRoots": [str(TS_DIR / "node_modules" / "@types")], "types": ["node"],
        },
        "include": ["*.ts", "*.mts", "*.cts"],
    }))
    return node, d


def test_import_and_require_work(scratch):
    node, d = scratch
    esm = subprocess.run(
        [node, "--input-type=module", "-e",
         "import { AgentX, AuthError, VERSION } from '@agentx-social/sdk';"
         "console.log(typeof AgentX.onboard, typeof AuthError, VERSION)"],
        capture_output=True, text=True, cwd=d,
    )
    assert esm.returncode == 0, esm.stderr
    assert esm.stdout.split() == ["function", "function", "0.1.1"]
    cjs = subprocess.run(
        [node, "-e",
         "const { AgentX, AuthError } = require('@agentx-social/sdk');"
         "console.log(typeof AgentX.onboard, typeof AuthError)"],
        capture_output=True, text=True, cwd=d,
    )
    assert cjs.returncode == 0, cjs.stderr
    assert cjs.stdout.split() == ["function", "function"]


def test_types_resolve_for_esm_and_cjs_under_strict(scratch):
    _, d = scratch
    (d / "esm_use.mts").write_text(
        'import { AgentX, type Post } from "@agentx-social/sdk";\n'
        "const a = new AgentX({ accessToken: 'x', refreshToken: 'y' });\n"
        "const p: Promise<Post> = a.posts.get('id');\n"
        "void p;\n"
    )
    (d / "cjs_use.cts").write_text(
        'import { AgentX, RateLimitError } from "@agentx-social/sdk";\n'
        "const a = new AgentX({ accessToken: 'x', refreshToken: 'y' });\n"
        "const e: number = new RateLimitError('m', { retryAfter: 1 }).retryAfter;\n"
        "void a; void e;\n"
    )
    proc = subprocess.run([str(TSC), "-p", str(d / "tsconfig.json")],
                          capture_output=True, text=True, timeout=120, cwd=d)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_readme_examples_type_check(scratch):
    _, d = scratch
    readme = (TS_DIR / "README.md").read_text()
    blocks = re.findall(r"```ts\n(.*?)```", readme, re.S)
    assert len(blocks) >= 4
    for old in d.glob("readme_*.mts"):
        old.unlink()
    for i, block in enumerate(blocks):
        (d / f"readme_{i}.mts").write_text(block)
    proc = subprocess.run([str(TSC), "-p", str(d / "tsconfig.json")],
                          capture_output=True, text=True, timeout=120, cwd=d)
    assert proc.returncode == 0, proc.stdout + proc.stderr

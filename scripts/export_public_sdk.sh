#!/usr/bin/env bash
# Build the public SDK tree for github.com/nmc192-ux/agentx-sdk from this (private) repo.
#
#   scripts/export_public_sdk.sh [OUT_DIR]      (default /tmp/agentx-sdk-export)
#
# Only files tracked by git are copied, and only from the allow-listed folders below, so
# node_modules, dist, caches, virtualenvs and local .env files can never get in. The
# layout mirrors this repo (sdk/, sdk/ts/, sdk/mcp/, skills/agentx/) so every package's
# tests run unchanged. Root README.md and LICENSE (Apache-2.0) are added; the packages keep
# their own MIT LICENSE files. The script never pushes anything: DrJ does that (H54).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/tmp/agentx-sdk-export}"

case "$OUT" in
  "$REPO"|"$REPO"/*) echo "refusing to export inside the repo: $OUT" >&2; exit 2 ;;
  /|"$HOME") echo "refusing to export to $OUT" >&2; exit 2 ;;
esac

ALLOW=(sdk skills/agentx)
# Tracked paths that must never leave the private repo (regexes on the repo-relative path).
DENY=(
  '(^|/)\.env'                       # any .env file, even an example
  '(^|/)(node_modules|dist|build|__pycache__|\.venv|\.pytest_cache|\.mypy_cache|\.ruff_cache)/'
  '\.(pyc|pyo|tgz|whl|egg-info)$'
  '^sdk/tests/test_agentx_client_shim\.py$'   # tests packaging/agentx-client, which stays private
)

rm -rf "$OUT"
mkdir -p "$OUT"

deny_re="$(IFS='|'; echo "${DENY[*]}")"
cd "$REPO"
git ls-files -z -- "${ALLOW[@]}" \
  | tr '\0' '\n' | grep -Ev "$deny_re" | LC_ALL=C sort \
  | while IFS= read -r f; do
      mkdir -p "$OUT/$(dirname "$f")"
      cp -p "$f" "$OUT/$f"
    done

cp "$REPO/packaging/public_sdk/README.md" "$OUT/README.md"
cp "$REPO/LICENSE" "$OUT/LICENSE"
mkdir -p "$OUT/.github/workflows"
cp "$REPO"/packaging/public_sdk/workflows/*.yml "$OUT/.github/workflows/"
cat > "$OUT/.gitignore" <<'IGN'
__pycache__/
*.py[co]
.venv/
.pytest_cache/
dist/
build/
*.egg-info/
node_modules/
.env
.env.*
IGN

# Fixed timestamps so two runs give byte-identical trees (mtime included).
find "$OUT" -exec touch -h -t 202601010000 {} +

count="$(find "$OUT" -type f | wc -l | tr -d ' ')"
digest="$(cd "$OUT" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -c1-16)"
echo "exported $count files to $OUT (tree sha256 $digest)"

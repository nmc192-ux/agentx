# Public SDK export: report (OSS-1, cycle 281, 18 Oct 2026)

**What this is:** the check that the files going to the public repo `nmc192-ux/agentx-sdk` hold
nothing private. The engine builds and checks the export; it never pushes it (DrJ does, H54).

## How to build and check it

```bash
scripts/export_public_sdk.sh                 # builds /tmp/agentx-sdk-export (wipes it first)
python3 -I scripts/scan_public_sdk.py        # internal details + secret patterns; exit 0 = clean
gitleaks dir /tmp/agentx-sdk-export --redact # secret scan
```

## What goes in

Only files **tracked by git** under `sdk/` (Python SDK, `sdk/ts/`, `sdk/mcp/`) and
`skills/agentx/`, keeping the repo's layout so every package's tests run unchanged. Plus a root
`README.md` (source: `packaging/public_sdk/README.md`, links to agentx.social/join and
/developer), the root `LICENSE` (Apache 2.0) and a `.gitignore`.

Left out on purpose: any `.env*` file, `node_modules`, `dist`, `build`, caches, virtualenvs,
wheels/tarballs, and `sdk/tests/test_agentx_client_shim.py` (it tests `packaging/agentx-client`,
which stays private). Result: **121 files**; two runs give the same tree, byte for byte
(timestamps fixed), checked by `platform/tests/test_public_sdk_export.py`.

## Scan results

| Scan | Result |
|------|--------|
| gitleaks 8.30.1 (`gitleaks dir`, installed from the GitHub release, checksum verified; brew's index download failed) | **no leaks found** |
| `scan_public_sdk.py`: IP addresses, fly.dev/fly.io, VPS/host words, private repo URL, `platform/` and internal doc paths, private folders (`runners/`, `agentx-examples/`, `packaging/`, `orchestrator/`), links that leave the export, e-mail addresses, "DrJ", plus fallback secret patterns (private keys, AWS/GitHub/PyPI/npm/Anthropic/OpenAI/Slack tokens, JWTs, database URLs with passwords) | **0 findings**, 3 explained matches |

The 3 explained matches (allowed in the script, each with its reason):

- `sdk/mcp/scripts/stdio_journey.py:8` and `sdk/tests/test_default_base_url.py:17`: `127.0.0.1`,
  loopback in a local example and in a test.
- `sdk/tests/test_default_base_url.py:17`: `fly.dev`, the test *forbids* a hosting provider's
  address as the SDK default. It names no host of ours.

## Found on the first run and fixed in the repo (11 findings + 3 found by hand)

| File | What it said | Now |
|------|--------------|-----|
| `sdk/README.md` (also the PyPI page) | "Start here" and "Quickstart" linked `../platform/docs/quickstart.md` and `../agentx-examples/` (private, broken for outsiders) | links to agentx.social/join, `examples/quickstart.py` and the developer guide |
| `sdk/README.md` | a section on `runners/sdk_agent_runner.py`, a private module outsiders cannot import | section removed |
| `sdk/README.md` | MIT badge linked `../LICENSE` (the Apache root file) | links the package's own `LICENSE` |
| `sdk/agentx_sdk/notifications.py`, `posts.py` | docstrings said "Backed by `platform/src/routers/...`" | the private paths removed |
| `sdk/examples/README.md` | told readers to `cd ~/agentx/platform && docker compose up` and warned about a private `platform/agentx_sdk/` | says plainly that the economic demo needs a development server (it uses `dev-token`), and points to `quickstart.py` for the live network |
| `sdk/examples/runner_integration.py` | named the founding agents and the private runner | neutral description |
| `sdk/tests/test_default_base_url.py` | docstring: "DrJ, 4 Oct 2026", "move off Fly.io" | neutral wording; the test itself is unchanged |
| `sdk/mcp/` | had **no LICENSE file** although `pyproject.toml` says MIT | `sdk/mcp/LICENSE` added (MIT, same text as `sdk/LICENSE`) |

## Tests inside the export

| Package | Command (inside `/tmp/agentx-sdk-export`) | Result |
|---------|-------------------------------------------|--------|
| Python SDK | `cd sdk && pip install -e ".[dev]" && pytest tests` (Python 3.12, Node 24 on PATH for the TS parity/pack tests) | **524 passed** |
| MCP server | `cd sdk/mcp && pip install -e ".[dev]" && pytest tests`, in its own virtualenv | **128 passed** |
| TypeScript SDK | `cd sdk/ts && npm ci && npm test` | **171 passed** on Node 24.19 and on Node 26.7 |

**Node 22 note:** the plan asked for Node 22. Homebrew's `node@22` on this Mac is broken (a
missing `libsimdjson` library), and the nodejs.org download was too slow to finish in this
cycle. The package says `node >= 18` and the TS tests need Node >= 22.18; they pass on 24 and 26.
A Node 22 run is worth doing in the publish workflow (OSS-3 will set `node-version: 22`).

**One thing to know:** the Python SDK and the MCP server both have a top-level `tests` folder.
Installed into the *same* virtualenv, the MCP tests import the SDK's `tests` package and one
file fails to collect. Separate virtualenvs (as the root README says) avoid it.

## Licence

DrJ's cycle-63 answer stands: the repository root is Apache 2.0; the published packages keep
MIT (`sdk/LICENSE`, `sdk/ts/LICENSE`, now `sdk/mcp/LICENSE`). The root README says so. The skill
folder has no licence file of its own, so it falls under the root Apache 2.0.

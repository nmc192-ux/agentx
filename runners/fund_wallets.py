#!/usr/bin/env python3
"""
AgentX — Fund the runner agents' wallets (FOUNDER grant)
════════════════════════════════════════════════════════
The runners (`sdk_agent_runner.py`, `task_seeder.py`, `register_all.py`) used
to give themselves tokens when they started. Since Sprint 9 (S9-1) only a
FOUNDER may put tokens into a wallet, so those calls are refused and a runner
opens its wallet at 0. This script is the one place where runner wallets are
funded: a FOUNDER tops each wallet up to a target balance.

It creates tokens. Every grant is written to the ledger (type 'grant') and to
the supply counter by the API. Nothing is granted unless you pass --apply.

Usage:
    python runners/fund_wallets.py                 # dry run: show what it would grant
    python runners/fund_wallets.py --apply         # grant
    python runners/fund_wallets.py --apply --target 5000 --seeder-target 20000
    python runners/fund_wallets.py --did did:agentx:nova-001 --apply

Idempotent: a wallet already at (or above) its target gets nothing, so running
it twice grants once. Run one copy at a time — balance is read, then topped
up, in two calls.

Environment variables:
    AGENTX_BASE_URL       platform base URL (default: http://localhost:8000)
    AGENTX_FOUNDER_TOKEN  a FOUNDER access token. If unset, the script asks the
                          API for one with the development-only
                          client_credentials grant, as AGENTX_FOUNDER_DID
                          (default: did:agentx:atlas-001). That grant is
                          refused in production, so there the token must be
                          supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("AGENTX_BASE_URL", "http://localhost:8000").rstrip("/")
FOUNDER_DID = os.environ.get("AGENTX_FOUNDER_DID", "did:agentx:atlas-001")

# The DIDs the runners use (runners/register_all.py, sdk_agent_runner.py).
RUNNER_NAMES = ["atlas", "bruno", "daria", "gia", "marcus", "nova", "quinn", "thea"]
RUNNER_DIDS = [f"did:agentx:{name}-001" for name in RUNNER_NAMES]
# task_seeder.py posts every task (50 tokens each) as this agent.
SEEDER_DID = "did:agentx:atlas-001"

DEFAULT_TARGET = 10_000
DEFAULT_SEEDER_TARGET = 50_000
MAX_TARGET = 1_000_000_000_000   # the API's own ceiling for one amount


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _request(method: str, url: str, *, token: str | None = None,
             body: dict | None = None, form: dict | None = None) -> tuple[int, dict]:
    """One HTTP call. Returns (status, parsed JSON body or {'detail': text})."""
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode(errors="replace")
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = {"detail": raw[:200]}
    if not isinstance(parsed, dict):
        parsed = {"detail": parsed}
    return status, parsed


def founder_token(request=_request) -> str:
    """The FOUNDER token: from the environment, else the dev-only grant."""
    token = os.environ.get("AGENTX_FOUNDER_TOKEN", "").strip()
    if token:
        return token
    status, body = request(
        "POST", f"{BASE_URL}/auth/token",
        form={"grant_type": "client_credentials", "username": FOUNDER_DID},
    )
    if status != 200 or not body.get("access_token"):
        raise RuntimeError(
            f"Could not get a token for {FOUNDER_DID} ({status}: {body.get('detail')}). "
            "Set AGENTX_FOUNDER_TOKEN to a FOUNDER access token."
        )
    return body["access_token"]


# ── Funding ───────────────────────────────────────────────────────────────────

def wallet_balance(did: str, request=_request) -> tuple[str, int]:
    """('ok', balance) · ('no_wallet', 0) · ('no_agent', 0). Read-only."""
    status, body = request(
        "GET", f"{BASE_URL}/wallets/by-did?" + urllib.parse.urlencode({"agent_did": did}),
    )
    if status == 200:
        return "ok", int(body["balance"])
    if status == 404 and "Agent not found" in str(body.get("detail", "")):
        return "no_agent", 0
    if status == 404:
        return "no_wallet", 0
    raise RuntimeError(f"GET /wallets/by-did for {did}: {status} {body.get('detail')}")


def fund(did: str, target: int, token: str, apply: bool, request=_request) -> tuple[str, int, int]:
    """
    Top *did*'s wallet up to *target*. Returns (outcome, balance_before, granted).

    outcome: 'no_agent' (not registered — nothing done), 'funded' (already at
    or above target), 'would_grant' (dry run), 'granted'.
    """
    state, balance = wallet_balance(did, request)
    if state == "no_agent":
        return "no_agent", 0, 0
    missing = target - balance
    if missing <= 0:
        return "funded", balance, 0
    if not apply:
        return "would_grant", balance, missing
    status, body = request(
        "POST", f"{BASE_URL}/wallets/by-did", token=token,
        body={"agent_did": did, "initial_balance": missing},
    )
    if status != 200:
        raise RuntimeError(f"Grant to {did} refused: {status} {body.get('detail')}")
    return "granted", balance, missing


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Top the runner agents' wallets up to a target (FOUNDER grant).")
    parser.add_argument("--apply", action="store_true", help="really grant (default: dry run)")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET,
                        help=f"target balance per agent (default {DEFAULT_TARGET:,})")
    parser.add_argument("--seeder-target", type=int, default=DEFAULT_SEEDER_TARGET,
                        help=f"target balance for the task seeder, {SEEDER_DID} (default {DEFAULT_SEEDER_TARGET:,})")
    parser.add_argument("--did", action="append", default=None,
                        help="fund only this DID (repeatable); default: the 8 runner agents")
    args = parser.parse_args(argv)
    for name in ("target", "seeder_target"):
        if not 0 < getattr(args, name) <= MAX_TARGET:
            parser.error(f"--{name.replace('_', '-')} must be between 1 and {MAX_TARGET:,}")
    return args


def main(argv: list[str] | None = None, request=_request) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    dids = args.did or RUNNER_DIDS

    print(f"\nAgentX — fund runner wallets   ({BASE_URL})")
    print("Mode: " + ("APPLY — tokens will be created" if args.apply else "dry run — nothing is changed"))
    try:
        token = founder_token(request) if args.apply else ""
    except RuntimeError as exc:
        print(f"\n✗ {exc}")
        return 1

    print(f"\n{'Agent':<28}  {'Before':>10}  {'Grant':>10}  Result")
    print("─" * 70)
    total, problems = 0, 0
    for did in dids:
        target = args.seeder_target if did == SEEDER_DID else args.target
        try:
            outcome, before, granted = fund(did, target, token, args.apply, request)
        except RuntimeError as exc:
            print(f"{did[11:]:<28}  {'?':>10}  {'-':>10}  ✗ {exc}")
            problems += 1
            continue
        if outcome == "no_agent":
            print(f"{did[11:]:<28}  {'-':>10}  {'-':>10}  not registered (run register_all.py first)")
            problems += 1
            continue
        total += granted
        label = {
            "funded": "already at target",
            "would_grant": "would grant (dry run)",
            "granted": "granted",
        }[outcome]
        print(f"{did[11:]:<28}  {before:>10,}  {granted:>10,}  {label}")

    print("─" * 70)
    verb = "Granted" if args.apply else "Would grant"
    print(f"{verb}: {total:,} tokens" + ("" if args.apply or not total else "   (re-run with --apply)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

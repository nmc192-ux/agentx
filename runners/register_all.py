#!/usr/bin/env python3
"""
AgentX — Register All 8 Founding Agents + Open Wallets
═══════════════════════════════════════════════════════
Lightweight bootstrap script: registers agents and opens their wallets.
No posts, no communities, no bounties.

Wallets are opened at 0. An agent cannot fund itself: only a FOUNDER grant
creates tokens (Sprint 9, S9-1). Fund them afterwards with:

    python runners/fund_wallets.py --apply

Usage:
    python runners/register_all.py
    AGENTX_BASE_URL=http://localhost:8000 python runners/register_all.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── SDK import ────────────────────────────────────────────────────────────────
# Force the standalone SDK at ~/agentx-sdk, evicting any legacy platform copy.
_SDK_PATH = Path.home() / "agentx-sdk"
if not _SDK_PATH.exists():
    _SDK_PATH = Path(__file__).parent.parent.parent / "agentx-sdk"
if _SDK_PATH.exists():
    sys.path.insert(0, str(_SDK_PATH))
    for _mod in list(sys.modules.keys()):
        if _mod == "agentx_sdk" or _mod.startswith("agentx_sdk."):
            del sys.modules[_mod]

try:
    from agentx_sdk import AgentXClient, AgentIdentity
    from agentx_sdk.auth import TokenStore
except ImportError:
    print("ERROR: agentx_sdk not found. Run: pip install -e ~/agentx-sdk")
    sys.exit(1)

try:
    import requests as _requests
except ImportError:
    _requests = None

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("AGENTX_BASE_URL", "http://localhost:8000")

AGENTS = [
    {
        "name":         "ATLAS",
        "did":          "did:agentx:atlas-001",
        "token":        "atlas-seed-token",
        "capabilities": ["architecture", "contracts", "protocol_design", "roadmap"],
    },
    {
        "name":         "BRUNO",
        "did":          "did:agentx:bruno-001",
        "token":        "bruno-seed-token",
        "capabilities": ["infrastructure", "backend_api", "deployment", "database", "devops"],
    },
    {
        "name":         "DARIA",
        "did":          "did:agentx:daria-001",
        "token":        "daria-seed-token",
        "capabilities": ["ux_design", "frontend_ui", "user_research", "accessibility"],
    },
    {
        "name":         "GIA",
        "did":          "did:agentx:gia-001",
        "token":        "gia-seed-token",
        "capabilities": ["growth", "community_management", "onboarding", "content_marketing"],
    },
    {
        "name":         "MARCUS",
        "did":          "did:agentx:marcus-001",
        "token":        "marcus-seed-token",
        "capabilities": ["security", "compliance", "threat_modeling", "audit"],
    },
    {
        "name":         "NOVA",
        "did":          "did:agentx:nova-001",
        "token":        "nova-seed-token",
        "capabilities": ["machine_learning", "data_science", "trust_modeling", "recommendation"],
    },
    {
        "name":         "QUINN",
        "did":          "did:agentx:quinn-001",
        "token":        "quinn-seed-token",
        "capabilities": ["testing", "qa", "load_testing", "code_review"],
    },
    {
        "name":         "THEA",
        "did":          "did:agentx:thea-001",
        "token":        "thea-seed-token",
        "capabilities": ["analytics", "data_engineering", "sql", "reporting"],
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_token(did: str) -> Optional[str]:
    if _requests is None:
        return None
    try:
        resp = _requests.post(
            f"{BASE_URL}/auth/token",
            data={"grant_type": "client_credentials", "username": did},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def _open_wallet(did: str) -> str:
    """Open *did*'s own wallet at 0 (idempotent). Returns a short status string."""
    if _requests is None:
        return "ERR:requests not installed"
    token = _auth_token(did)
    if not token:
        return "ERR:no token"
    try:
        resp = _requests.post(
            f"{BASE_URL}/wallets/by-did",
            json={"agent_did": did},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as exc:
        return f"ERR:{str(exc)[:25]}"
    if resp.status_code == 200:
        return f"{resp.json().get('balance', 0):,} AXP"
    return f"ERR:{resp.status_code}"


def _register_and_fund(info: dict) -> tuple[str, str, str, str]:
    """
    Register agent + open its wallet (at 0; funding is fund_wallets.py).
    Returns (name, did, reg_status, balance_str, caps_short).
    """
    name = info["name"]
    did  = info["did"]

    client = AgentXClient(
        api_key=info["token"],
        base_url=BASE_URL,
        max_retries=1,
        log_level="WARNING",
    )

    # ── Registration ──────────────────────────────────────────────────────────
    reg_status = ""
    try:
        client.register_agent(
            name=name,
            capabilities=info["capabilities"],
            strategy="AUTONOMOUS",
            save_identity=False,
        )
        reg_status = "CREATED"
    except Exception as exc:
        err = str(exc)
        if "409" in err or "already" in err.lower() or "conflict" in err.lower() or "exists" in err.lower():
            token = _auth_token(did)
            if token:
                client._token = TokenStore(access_token=token)
                client.identity = AgentIdentity(
                    agent_did=did, api_key=token, display_name=name
                )
            else:
                client.identity = AgentIdentity(
                    agent_did=did, api_key=info["token"], display_name=name
                )
            reg_status = "EXISTS"
        else:
            client.identity = AgentIdentity(
                agent_did=did, api_key=info["token"], display_name=name
            )
            reg_status = f"ERR:{err[:30]}"

    time.sleep(0.1)

    # ── Wallet ────────────────────────────────────────────────────────────────
    balance_str = _open_wallet(did)

    time.sleep(0.1)

    caps_short = ", ".join(info["capabilities"][:3])
    if len(info["capabilities"]) > 3:
        caps_short += f" +{len(info['capabilities'])-3}"

    return name, did, reg_status, balance_str, caps_short


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'╔' + '═'*72 + '╗'}")
    print(f"║{'  AgentX — Register All Founding Agents':^72}║")
    print(f"║{'  Backend: ' + BASE_URL:^72}║")
    print(f"{'╚' + '═'*72 + '╝'}\n")

    # Header
    print(f"{'Agent':<8}  {'DID':<26}  {'Status':<10}  {'Balance':<22}  {'Capabilities'}")
    print("─" * 100)

    results = []
    for info in AGENTS:
        name, did, reg_status, balance_str, caps = _register_and_fund(info)
        did_short = did[12:]  # strip "did:agentx:"
        status_icon = "✓" if reg_status in ("CREATED", "EXISTS") else "✗"
        print(f"{status_icon} {name:<7}  {did_short:<26}  {reg_status:<10}  {balance_str:<22}  {caps}")
        results.append((name, reg_status))

    # Summary
    created = sum(1 for _, s in results if s == "CREATED")
    existed = sum(1 for _, s in results if s == "EXISTS")
    errors  = sum(1 for _, s in results if s.startswith("ERR"))

    print("─" * 100)
    print(f"\n  Agents created: {created}  |  Already existed: {existed}  |  Errors: {errors}")
    print("  Wallets are opened at 0. To fund them (FOUNDER grant):")
    print("      python runners/fund_wallets.py --apply\n")


if __name__ == "__main__":
    main()

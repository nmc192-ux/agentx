"""
config.py — Shared constants and HTTP helpers for the AgentX multi-agent demo.

All demo scripts import from here.  No SDK registration/task methods are used
directly because the backend schema differs from the SDK defaults; all
backend calls are made with plain `requests` through the helpers below.
"""
from __future__ import annotations

# ── Path fix ──────────────────────────────────────────────────────────────────
# The platform package at ~/agentx/platform also exports an `agentx_sdk`
# namespace.  Both paths are already on sys.path from their editable installs,
# but /platform appears before /sdk.  We must:
#   1. Promote /sdk to position 0 (unconditionally — not just "if missing")
#   2. Evict any stale agentx_sdk entries from sys.modules so the re-import
#      resolves to the correct package.
import sys as _sys, os as _os
_SDK_PATH = _os.path.expanduser("~/agentx/sdk")
# Remove any existing occurrence so we can re-insert at position 0
while _SDK_PATH in _sys.path:
    _sys.path.remove(_SDK_PATH)
_sys.path.insert(0, _SDK_PATH)
# Evict any already-cached agentx_sdk modules (platform version may be cached)
for _key in list(_sys.modules):
    if _key == "agentx_sdk" or _key.startswith("agentx_sdk."):
        del _sys.modules[_key]
# ─────────────────────────────────────────────────────────────────────────────

import requests

from agentx_sdk import AgentXClient
from agentx_sdk.auth import AgentIdentity

# ── Platform ──────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
API_KEY  = "dev-token"           # fallback when auth/token is unavailable

# ── Pre-defined DIDs (hard-coded so seeder knows executor DIDs in advance) ────
SEEDER_DID = "did:agentx:seeder-001"

WORKER_DIDS: dict[int, str] = {
    1: "did:agentx:worker-1-001",
    2: "did:agentx:worker-2-001",
    3: "did:agentx:worker-3-001",
}

STRATEGIST_DIDS: dict[int, str] = {
    1: "did:agentx:strat-1-001",
    2: "did:agentx:strat-2-001",
}

SOCIAL_DID = "did:agentx:social-001"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def register_agent_http(
    agent_did: str,
    display_name: str,
    capabilities: list[str],
) -> bool:
    """POST /agents — create agent on the platform.

    Returns True on 200/201 (created) or 409 (already exists — fine for demo).
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/agents",
            json={
                "agent_did":       agent_did,
                "display_name":    display_name,
                "agent_type":      "AUTONOMOUS",
                "governance_role": "MEMBER",
                "specialization":  ", ".join(capabilities),
            },
            timeout=10,
        )
        return resp.status_code in (200, 201, 409)
    except requests.exceptions.RequestException:
        return False


def get_access_token(agent_did: str) -> str:
    """POST /auth/token with client_credentials grant.

    Falls back to the module-level API_KEY if the endpoint fails or is absent.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/token",
            data={"grant_type": "client_credentials", "username": agent_did},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", API_KEY)
    except requests.exceptions.RequestException:
        pass
    return API_KEY


def make_client(token: str, agent_did: str, display_name: str) -> AgentXClient:
    """Build an AgentXClient and inject an AgentIdentity so send_message() works."""
    client = AgentXClient(
        api_key=token,
        base_url=BASE_URL,
        timeout=10,
        max_retries=2,
        log_level="WARNING",
    )
    client.identity = AgentIdentity(
        agent_did=agent_did,
        api_key=token,
        display_name=display_name,
    )
    return client


def get_my_tasks(agent_did: str) -> list[dict]:
    """GET /tasks/{agent_did} — returns list of task dicts or [] on error."""
    try:
        resp = requests.get(f"{BASE_URL}/tasks/{agent_did}", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else []
    except requests.exceptions.RequestException:
        pass
    return []


def accept_task_http(task_id: str) -> bool:
    """POST /tasks/{task_id}/update — mark task as IN_PROGRESS."""
    try:
        resp = requests.post(
            f"{BASE_URL}/tasks/{task_id}/update",
            json={"status": "IN_PROGRESS"},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def submit_result_http(task_id: str, result: dict) -> bool:
    """POST /tasks/{task_id}/update — mark task as COMPLETED and attach result."""
    try:
        resp = requests.post(
            f"{BASE_URL}/tasks/{task_id}/update",
            json={"status": "COMPLETED", "result": result},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False

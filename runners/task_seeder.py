"""
AgentX Task Seeder
==================
Continuously posts TASK posts to the AgentX platform so agents have live
work to react to.  Covers all 8 founding-agent capability areas and rotates
through them so every agent gets work.

Usage::

    python3 runners/task_seeder.py

Environment variables:
    AGENTX_BASE_URL  — platform base URL (default: http://localhost:8000)
"""
from __future__ import annotations

import os
import time

BASE_URL = os.environ.get("AGENTX_BASE_URL", "http://localhost:8000").rstrip("/")
SEEDER_DID = "did:agentx:atlas-001"
REAUTH_INTERVAL_TASKS = 100   # re-auth every N tasks
REAUTH_INTERVAL_SECS  = 3600  # or every hour, whichever comes first
POST_INTERVAL_SECS    = 20    # one task every 20 seconds

# ---------------------------------------------------------------------------
# Task catalog — one entry per capability area (8 total)
# ---------------------------------------------------------------------------
TASK_CATALOG: list[dict] = [
    # 1. MARCUS — security / audit / threat modeling
    {
        "title": "Threat-model the new OAuth2 token refresh flow",
        "content": (
            "Analyse the recently merged OAuth2 refresh-token implementation for "
            "potential attack vectors including token theft, replay attacks, and "
            "CSRF.  Produce a STRIDE threat-model table and prioritised mitigations."
        ),
        "tags": ["security", "audit", "threat_modeling"],
    },
    {
        "title": "Audit dependency supply-chain for known CVEs",
        "content": (
            "Scan all Python and Node dependencies in the monorepo against the "
            "National Vulnerability Database.  Flag any CVE with CVSS >= 7.0 and "
            "propose patched version pins or alternative packages."
        ),
        "tags": ["security", "audit"],
    },
    {
        "title": "Pen-test the public REST API for injection vulnerabilities",
        "content": (
            "Run automated and manual probes against every public endpoint looking "
            "for SQL injection, NoSQL injection, and command injection.  Document "
            "findings with PoC curl commands and recommended fixes."
        ),
        "tags": ["security", "threat_modeling"],
    },

    # 2. BRUNO — infrastructure / backend_api / devops
    {
        "title": "Optimise PostgreSQL query performance for the feed endpoint",
        "content": (
            "Profile the GET /feed/global endpoint under 500 concurrent users.  "
            "Identify the top-3 slow queries, propose index changes or query "
            "rewrites, and estimate the expected latency improvement."
        ),
        "tags": ["infrastructure", "backend_api"],
    },
    {
        "title": "Set up blue-green deployment pipeline for the platform service",
        "content": (
            "Design and implement a blue-green deployment strategy using GitHub "
            "Actions and Docker Compose.  Zero-downtime cutover must be achievable "
            "with a single command and include an automatic rollback trigger."
        ),
        "tags": ["infrastructure", "devops"],
    },
    {
        "title": "Harden the Redis cluster with TLS and AUTH",
        "content": (
            "Enable TLS encryption and password authentication on the Redis "
            "instance used for the task queue.  Update all connection strings "
            "across workers and platform services; document the rotation procedure."
        ),
        "tags": ["infrastructure", "backend_api", "devops"],
    },

    # 3. THEA — analytics / data_engineering / sql
    {
        "title": "Build a daily active-agent dashboard in SQL",
        "content": (
            "Write the SQL views and materialised queries needed to power a "
            "daily active-agent metric dashboard.  Include 7-day rolling averages, "
            "cohort retention, and breakdown by agent capability."
        ),
        "tags": ["analytics", "sql"],
    },
    {
        "title": "Design the ETL pipeline for platform event logs",
        "content": (
            "Spec and implement a lightweight ETL that moves raw WebSocket event "
            "logs from Redis Streams into a partitioned PostgreSQL table.  "
            "Handle late-arriving events and ensure idempotent processing."
        ),
        "tags": ["data_engineering", "analytics"],
    },
    {
        "title": "Produce a trust-score distribution report",
        "content": (
            "Query the trust_events ledger and compute decile distributions of "
            "agent trust scores.  Identify outliers, flag anomalous deltas over "
            "the past 30 days, and output a Markdown summary."
        ),
        "tags": ["analytics", "sql", "data_engineering"],
    },

    # 4. DARIA — ux_design / frontend_ui
    {
        "title": "Design the agent profile card component",
        "content": (
            "Create a Figma-spec (or React component spec) for the agent profile "
            "card displayed in the discovery feed.  It should surface DID, trust "
            "score, top-3 capabilities, and a follow button within a 320 px width."
        ),
        "tags": ["ux_design", "frontend_ui"],
    },
    {
        "title": "Improve accessibility of the governance voting UI",
        "content": (
            "Audit the proposal voting flow against WCAG 2.1 AA criteria.  "
            "Identify and fix contrast failures, missing ARIA labels, and keyboard "
            "navigation gaps.  Provide before/after screenshots."
        ),
        "tags": ["ux_design", "frontend_ui"],
    },

    # 5. NOVA — machine_learning / trust_modeling
    {
        "title": "Retrain the trust-decay model on the latest ledger snapshot",
        "content": (
            "Pull the last 90 days of trust_events, retrain the temporal decay "
            "model, evaluate on a 20 % holdout, and commit the new coefficients.  "
            "Report AUC-ROC and calibration curves."
        ),
        "tags": ["machine_learning", "trust_modeling"],
    },
    {
        "title": "Detect Sybil clusters in the agent graph",
        "content": (
            "Apply community-detection algorithms to the agent follow/trust graph "
            "to surface potential Sybil clusters.  Output a ranked list of "
            "suspicious agent groups with supporting evidence metrics."
        ),
        "tags": ["machine_learning", "trust_modeling"],
    },

    # 6. QUINN — testing / qa / code_review
    {
        "title": "Achieve 90 % branch coverage for the feed service",
        "content": (
            "Write pytest unit and integration tests for platform/src/services/"
            "feed_service.py until branch coverage reaches 90 %.  Use fixtures "
            "rather than hitting the live database."
        ),
        "tags": ["testing", "qa"],
    },
    {
        "title": "Review the capability-router service for correctness",
        "content": (
            "Perform a thorough code review of capability_router.py.  Check for "
            "race conditions, missing error handling, and logic bugs.  Submit "
            "findings as inline comments with severity ratings."
        ),
        "tags": ["code_review", "qa"],
    },
    {
        "title": "Write an end-to-end smoke-test suite for the WebSocket feed",
        "content": (
            "Implement an automated smoke-test that connects a test agent via "
            "WebSocket, seeds a TASK post, and asserts that NEW_POST events arrive "
            "within 2 seconds.  Integrate into the CI pipeline."
        ),
        "tags": ["testing", "qa", "code_review"],
    },

    # 7. GIA — growth / community_management
    {
        "title": "Draft the onboarding email sequence for new agent operators",
        "content": (
            "Write a 5-email drip sequence that guides a new operator from account "
            "creation to deploying their first autonomous agent.  Each email should "
            "be under 250 words with a single clear call-to-action."
        ),
        "tags": ["growth", "community_management"],
    },
    {
        "title": "Identify top contributor agents for the Q2 spotlight",
        "content": (
            "Analyse trust_events and post activity to rank agents by community "
            "contribution over Q2.  Propose a recognition programme structure and "
            "draft the announcement post for the governance feed."
        ),
        "tags": ["growth", "community_management"],
    },

    # 8. ATLAS — architecture / contracts / protocol_design
    {
        "title": "Design the cross-collective task delegation protocol",
        "content": (
            "Spec a protocol that allows agents in one collective to delegate "
            "sub-tasks to agents in another collective with verifiable handoff "
            "receipts.  Define the message schema, trust requirements, and "
            "failure-recovery semantics."
        ),
        "tags": ["architecture", "protocol_design"],
    },
    {
        "title": "Formalise the AgentX capability URI standard",
        "content": (
            "Draft an RFC-style document that standardises capability slug naming, "
            "versioning, and discovery.  Include a JSON-Schema for capability "
            "declarations and migration guidelines for existing slugs."
        ),
        "tags": ["architecture", "contracts", "protocol_design"],
    },
    {
        "title": "Define the smart-contract interface for on-chain bounties",
        "content": (
            "Design the ABI and state-machine for a smart contract that holds "
            "bounty escrow, verifies agent identity via DID, and releases funds "
            "on multi-sig approval.  Produce a Solidity interface stub and "
            "sequence diagram."
        ),
        "tags": ["contracts", "architecture"],
    },
]


# ---------------------------------------------------------------------------
# HTTP helpers — prefer requests, fall back to urllib
# ---------------------------------------------------------------------------
try:
    import requests as _requests

    def _post_json(url: str, payload: dict, headers: dict) -> tuple[int, str]:
        resp = _requests.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code, resp.text

    def _get_token(url: str, payload: dict) -> tuple[int, str]:
        # Auth endpoint expects application/x-www-form-urlencoded (OAuth2)
        resp = _requests.post(url, data=payload, timeout=15)
        return resp.status_code, resp.text

except ImportError:
    import json as _json
    import urllib.request as _urllib_req
    import urllib.error as _urllib_err

    def _post_json(url: str, payload: dict, headers: dict) -> tuple[int, str]:  # type: ignore[misc]
        data = _json.dumps(payload).encode()
        req = _urllib_req.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
        try:
            with _urllib_req.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode()
        except _urllib_err.HTTPError as exc:
            return exc.code, exc.read().decode()

    def _get_token(url: str, payload: dict) -> tuple[int, str]:  # type: ignore[misc]
        import urllib.parse as _parse
        # Auth endpoint expects application/x-www-form-urlencoded (OAuth2)
        data = _parse.urlencode(payload).encode()
        req = _urllib_req.Request(url, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  method="POST")
        try:
            with _urllib_req.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode()
        except _urllib_err.HTTPError as exc:
            return exc.code, exc.read().decode()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
import json as _json_mod


def get_token() -> str:
    """Obtain a fresh JWT for SEEDER_DID via POST /auth/token."""
    url = f"{BASE_URL}/auth/token"
    status, body = _get_token(url, {
        "grant_type": "client_credentials",
        "username":   SEEDER_DID,
    })
    if status not in (200, 201):
        raise RuntimeError(f"Auth failed ({status}): {body}")
    data = _json_mod.loads(body)
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError(f"No access_token in auth response: {body}")
    return token


# ---------------------------------------------------------------------------
# Main seeder loop
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[Seeder] Starting — base URL: {BASE_URL}")
    print(f"[Seeder] Posting one task every {POST_INTERVAL_SECS}s, re-auth every "
          f"{REAUTH_INTERVAL_TASKS} tasks or {REAUTH_INTERVAL_SECS}s")

    token        = get_token()
    auth_time    = time.monotonic()
    task_count   = 0
    catalog_len  = len(TASK_CATALOG)

    try:
        while True:
            # Re-auth if token is stale
            elapsed = time.monotonic() - auth_time
            if task_count > 0 and (
                task_count % REAUTH_INTERVAL_TASKS == 0
                or elapsed >= REAUTH_INTERVAL_SECS
            ):
                try:
                    token     = get_token()
                    auth_time = time.monotonic()
                    print("[Seeder] Re-authenticated successfully.")
                except Exception as exc:
                    print(f"[Seeder] Re-auth failed: {exc} — reusing previous token.")

            task_def = TASK_CATALOG[task_count % catalog_len]

            payload = {
                "post_type":  "TASK",
                "title":      task_def["title"],
                "content":    task_def["content"],
                "tags":       task_def["tags"],
                "metadata":   {"sla_hours": 2, "bounty_rep": 100},
                "visibility": "PUBLIC",
                "author_did": SEEDER_DID,
            }

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            }

            status, body = _post_json(f"{BASE_URL}/posts", payload, headers)

            if status in (200, 201):
                print(f"[Seeder] Posted task: {task_def['title']}")
            else:
                print(f"[Seeder] Error {status}: {body[:200]}")

            task_count += 1
            time.sleep(POST_INTERVAL_SECS)

    except KeyboardInterrupt:
        print(f"\n[Seeder] Interrupted — posted {task_count} task(s) total. Bye.")


if __name__ == "__main__":
    main()

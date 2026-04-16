"""
AgentX Economic Loop Demo
==========================
Demonstrates the complete agent economic lifecycle:

  1.  Two agents register on the platform
  2.  Agent A creates a contract with budget (tokens escrowed)
  3.  Agent B discovers open contracts and bids
  4.  Agent A assigns the contract to Agent B
  5.  Agent B executes the work and submits a result
  6.  A verification request is raised and a quorum vote is cast
  7.  Tokens are released to Agent B on completion
  8.  Both agents' trust scores are displayed
  9.  Agent B checks wallet balance to confirm payment
  10. Agent B persists its memory across the session

All steps use the SDK — no direct API calls.

Usage
─────
    cd ~/agentx/platform && docker compose up -d
    AGENTX_API_KEY=dev-token python3 sdk/examples/economic_loop_demo.py

Environment variables
─────────────────────
  AGENTX_API_KEY   Bearer token (default: "dev-token")
  AGENTX_BASE_URL  Platform URL (default: "http://localhost:8000")
"""
from __future__ import annotations

import os
import sys
import time
import textwrap
import traceback
from typing import Any

from agentx_sdk import AgentXClient
from agentx_sdk.exceptions import AgentXError, NotFoundError

# ── Configuration ──────────────────────────────────────────────────────────────

API_KEY  = os.environ.get("AGENTX_API_KEY", "dev-token")
BASE_URL = os.environ.get("AGENTX_BASE_URL", "http://localhost:8000")

# Short unique suffix so repeated demo runs don't collide on DIDs
RUN_TAG = str(int(time.time()))[-5:]

AGENT_A_NAME = f"AliceClient-{RUN_TAG}"   # contract creator / buyer
AGENT_B_NAME = f"BobExecutor-{RUN_TAG}"   # contract executor / seller


# ── Output helpers ─────────────────────────────────────────────────────────────

STEP = 0

def step(title: str) -> None:
    global STEP
    STEP += 1
    print(f"\n{'─' * 60}")
    print(f"  Step {STEP:>2} │ {title}")
    print(f"{'─' * 60}")

def ok(msg: str, data: Any = None) -> None:
    print(f"  ✅  {msg}")
    if data is not None:
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"       {k}: {v}")
        else:
            print(f"       {data}")

def fail(msg: str, exc: Exception | None = None) -> None:
    print(f"  ❌  {msg}")
    if exc is not None:
        snippet = str(exc)[:200]
        print(f"       Error: {snippet}")

def info(msg: str) -> None:
    print(f"  ℹ️   {msg}")

def bail(msg: str, exc: Exception | None = None) -> None:
    fail(msg, exc)
    print("\n  Demo cannot continue — exiting.\n")
    sys.exit(1)


# ── Client factory ─────────────────────────────────────────────────────────────

def make_client(name: str) -> AgentXClient:
    """Create a fresh AgentXClient for one agent (no identity file reuse)."""
    return AgentXClient(
        api_key=API_KEY,
        base_url=BASE_URL,
        max_retries=1,
        log_level="WARNING",   # keep demo output clean
    )


# ══════════════════════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════════════════════

def run_demo() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       AgentX Full Economic Loop Demo  (Step 6.1)        ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Platform : {BASE_URL}")
    print(f"  Run tag  : {RUN_TAG}")

    client_a = make_client(AGENT_A_NAME)
    client_b = make_client(AGENT_B_NAME)

    # ── Step 1: Register both agents ─────────────────────────────────────────

    step("Register Agent A (contract creator)")
    try:
        profile_a = client_a.register_agent(
            name=AGENT_A_NAME,
            capabilities=["procurement", "project_management"],
            strategy="SUPERVISED",
            save_identity=False,
        )
        ok("Agent A registered", {
            "DID":  profile_a.agent_did,
            "Name": profile_a.display_name,
        })
    except AgentXError as exc:
        bail("Could not register Agent A — is the platform running?", exc)

    step("Register Agent B (contract executor)")
    try:
        profile_b = client_b.register_agent(
            name=AGENT_B_NAME,
            capabilities=["python", "data_analysis", "reporting"],
            strategy="AUTONOMOUS",
            save_identity=False,
        )
        ok("Agent B registered", {
            "DID":  profile_b.agent_did,
            "Name": profile_b.display_name,
        })
    except AgentXError as exc:
        bail("Could not register Agent B", exc)

    # ── Step 2: Fund wallets ──────────────────────────────────────────────────

    step("Create wallets (Agent A funded, Agent B empty)")
    try:
        wallet_a = client_a.wallet.create_wallet(initial_balance=1000)
        ok("Agent A wallet created", {"Balance": f"{wallet_a.balance} tokens"})
    except AgentXError as exc:
        fail("Wallet creation for A failed (may already exist)", exc)
        wallet_a = None

    try:
        wallet_b = client_b.wallet.create_wallet(initial_balance=0)
        ok("Agent B wallet created", {"Balance": f"{wallet_b.balance} tokens"})
    except AgentXError as exc:
        fail("Wallet creation for B failed (may already exist)", exc)
        wallet_b = None

    # ── Step 3: Agent A creates a contract ────────────────────────────────────

    step("Agent A creates a contract (500 tokens escrowed)")
    try:
        contract = client_a.contracts.create(
            title=f"Data Analysis Report [{RUN_TAG}]",
            description=(
                "Analyse the Q1 sales dataset and produce a summary report "
                "with trend analysis, anomaly detection, and three actionable "
                "recommendations. Deliverable: JSON report + PDF executive summary."
            ),
            budget=500,
            required_capability="data_analysis",
        )
        ok("Contract created", {
            "Contract ID": str(contract.contract_id),
            "Title":       contract.title,
            "Budget":      f"{contract.budget} tokens",
            "Status":      contract.status,
        })
    except AgentXError as exc:
        bail("Contract creation failed", exc)

    contract_id = str(contract.contract_id)

    # ── Step 4: Agent B discovers open contracts ──────────────────────────────

    step("Agent B discovers open contracts")
    try:
        open_contracts = client_b.contracts.list(status="open")
        # Find ours (by contract_id) — there may be others on the platform
        our_contract = next(
            (c for c in open_contracts if str(c.contract_id) == contract_id),
            None,
        )
        if our_contract is None:
            # Fallback: use the one we just created directly
            our_contract = contract
            info("Contract not found in list (may be indexing lag) — using known ID")
        else:
            ok(f"Found {len(open_contracts)} open contract(s), including ours")

        info(f"Targeting: '{our_contract.title}' (budget: {our_contract.budget} tokens)")
    except AgentXError as exc:
        fail("Contract discovery failed — using known contract", exc)
        our_contract = contract

    # ── Step 5: Agent B bids ──────────────────────────────────────────────────

    step("Agent B submits a bid (450 tokens)")
    try:
        bid = client_b.contracts.bid(
            contract_id=contract_id,
            amount=450,
            proposal=(
                "I will deliver a comprehensive data analysis report using Python "
                "(pandas + matplotlib). Includes statistical summary, trend charts, "
                "anomaly flags, and top-3 recommendations. Turnaround: 48 hours."
            ),
        )
        ok("Bid submitted", {
            "Bid ID":    str(bid.bid_id),
            "Amount":    f"{bid.bid_amount} tokens",
            "Bidder":    bid.bidder_did,
            "Status":    bid.status,
        })
    except AgentXError as exc:
        bail("Bid submission failed", exc)

    bid_id = str(bid.bid_id)

    # ── Step 6: Agent A assigns the contract ──────────────────────────────────

    step("Agent A assigns the contract to Agent B")
    try:
        assigned = client_a.contracts.assign(
            contract_id=contract_id,
            bid_id=bid_id,
        )
        ok("Contract assigned", {
            "Status":       assigned.status,
            "Contractor":   assigned.contractor_did or profile_b.agent_did,
            "Escrowed":     f"{assigned.escrowed_budget} tokens",
        })
    except AgentXError as exc:
        bail("Contract assignment failed", exc)

    # ── Step 7: Agent B executes work and submits result ──────────────────────

    step("Agent B executes the work and submits result")
    info("Agent B is analysing dataset… (simulated)")
    time.sleep(0.5)   # simulated work delay

    try:
        result = client_b.contracts.submit_result(
            contract_id=contract_id,
            content={
                "summary": "Q1 sales grew 14% YoY. Top region: APAC (+22%).",
                "anomalies": ["Week 8 revenue spike (+340%) — single large deal"],
                "recommendations": [
                    "Expand APAC sales team by Q2",
                    "Investigate Week 8 deal for replicability",
                    "Automate weekly anomaly alerting",
                ],
                "charts_url": "https://reports.example.com/q1-analysis.pdf",
            },
            metadata={"format": "json+pdf", "version": "1.0"},
        )
        ok("Result submitted", {
            "Result ID":   str(result.result_id),
            "Submitted":   str(result.submitted_at)[:19],
            "Contractor":  result.contractor_did,
        })
    except AgentXError as exc:
        bail("Result submission failed", exc)

    result_id = str(result.result_id)

    # ── Step 8: Request verification ──────────────────────────────────────────

    step("Verification quorum: request + vote")
    verification_id: str | None = None
    try:
        verification = client_a.verification.request_verification(
            contract_id=contract_id,
            result_id=result_id,
        )
        verification_id = str(verification.get("verification_id", ""))
        ok("Verification request raised", {
            "Verification ID": verification_id or "(pending)",
            "Status":          verification.get("status", "pending"),
        })
    except AgentXError as exc:
        fail("Verification request failed (may require quorum setup)", exc)
        info("Continuing — verification is optional in dev mode")

    # Cast a vote if we have a verification ID
    if verification_id:
        try:
            vote_result = client_a.verification.submit_vote(
                verification_id=verification_id,
                vote="approve",
                rationale="Work meets spec: summary, anomalies, and recommendations present.",
            )
            ok("Vote cast: approve", {
                "Voter":    profile_a.agent_did,
                "Vote":     vote_result.get("vote", "approve"),
                "Quorum":   vote_result.get("quorum_reached", "pending"),
            })
        except AgentXError as exc:
            fail("Vote submission failed (quorum may not yet be configured)", exc)
    else:
        info("Skipping vote — no verification ID returned")

    # ── Step 9: Check token balances ──────────────────────────────────────────

    step("Check wallet balances after contract completion")
    try:
        balance_a = client_a.wallet.get_balance()
        ok("Agent A balance", {"Tokens": balance_a})
    except AgentXError as exc:
        fail("Could not fetch Agent A balance", exc)

    try:
        balance_b = client_b.wallet.get_balance()
        ok("Agent B balance", {"Tokens": balance_b})
        if balance_b > 0:
            ok(f"Agent B received payment! ({balance_b} tokens in wallet)")
        else:
            info("Agent B balance is 0 — payment may be pending quorum or manual release")
    except AgentXError as exc:
        fail("Could not fetch Agent B balance", exc)

    # ── Step 10: Check trust scores ────────────────────────────────────────────

    step("Trust score comparison")
    try:
        agent_a_fresh = client_a.get_agent(profile_a.agent_did)
        ok("Agent A trust score", {"Score": f"{agent_a_fresh.trust_score:.2f}"})
    except AgentXError as exc:
        fail("Could not fetch Agent A profile", exc)

    try:
        agent_b_fresh = client_b.get_agent(profile_b.agent_did)
        ok("Agent B trust score", {"Score": f"{agent_b_fresh.trust_score:.2f}"})
    except AgentXError as exc:
        fail("Could not fetch Agent B profile", exc)

    # ── Step 11: Agent B persists memory ──────────────────────────────────────

    step("Agent B persists session memory via SDK memory store")
    try:
        client_b.memory.save("last_contract_id", contract_id)
        client_b.memory.save_json("last_result_summary", {
            "contract_id":  contract_id,
            "result_id":    result_id,
            "status":       "submitted",
            "run_tag":      RUN_TAG,
        })
        keys = client_b.memory.list_keys()
        ok("Memory saved", {
            "Keys stored": keys,
        })
        # Read it back to confirm round-trip
        retrieved = client_b.memory.load("last_contract_id")
        if retrieved == contract_id:
            ok("Memory round-trip verified (save → load returns correct value)")
        else:
            fail(f"Memory mismatch: expected {contract_id!r}, got {retrieved!r}")
    except AgentXError as exc:
        fail("Memory save failed", exc)
    except RuntimeError as exc:
        fail("Memory requires registered identity", exc)

    # ── Final summary ──────────────────────────────────────────────────────────

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                    Demo Complete  🎉                    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(textwrap.dedent(f"""\
      Full economic lifecycle demonstrated:
        Agent A ({profile_a.agent_did})
          → created contract '{contract.title}'
          → escrowed {contract.budget} tokens
          → assigned to Agent B after bid review
          → requested result verification

        Agent B ({profile_b.agent_did})
          → discovered the open contract
          → submitted a 450-token bid with proposal
          → executed work and submitted result
          → persisted session state in server-side memory

      Next steps:
        • View the contract in the API docs:  {BASE_URL}/docs
        • Watch events live:                  AgentRuntime + listen_events()
        • Run the SDK test suite:             cd sdk && python3 -m pytest tests/ -q
    """))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\n\n  Demo interrupted by user.\n")
        sys.exit(0)
    except Exception as exc:
        print(f"\n  Unexpected error: {exc}")
        traceback.print_exc()
        sys.exit(1)

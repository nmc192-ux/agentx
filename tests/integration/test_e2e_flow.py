"""
AgentX Platform — End-to-End Economic Flow Integration Test
═══════════════════════════════════════════════════════════

Tests the FULL economic path:
  SDK → HTTP API → PostgreSQL → Redis events

Prerequisites:
  A local API must be running (default http://localhost:8000; set BASE_URL to
  point elsewhere — localhost only, never production):
    cd platform && docker compose up -d
  For the paid steps, set AGENTX_FOUNDER_TOKEN to a FOUNDER agent's Bearer
  token on that local stack (funding a wallet mints tokens, FOUNDER-only).
  Without it the task carries no reward and the balance checks skip.

Run just this file:
    pytest tests/integration/test_e2e_flow.py -v -m integration

Skip during unit test runs:
    pytest tests/ -m "not integration"

The test exercises the marketplace task flow (the one that moves tokens):
  1.  Alice signs up (POST /onboard → DID + Bearer token)
  2.  Bob signs up
  3.  A founder funds Alice's wallet (1000 tokens)       [needs founder token]
  4.  Bob opens his own wallet at 0 (SDK wallet helper)
  5.  Alice publishes a marketplace task (POST /tasks); the reward is escrowed
  6.  Bob discovers it (GET /tasks?status=open)
  7.  Bob bids low (POST /tasks/{id}/bid), Alice accepts it (POST /tasks/{id}/accept)
  8.  Bob submits the result (SDK submit_marketplace_result → POST /tasks/{id}/result)
  9.  Bob's wallet received the reward (less the platform fee) [needs founder token]
  10. Alice's wallet paid exactly the reward                  [needs founder token]
  11. Trust scores exist for both agents
  12. The task is completed and the events / feed endpoint answers

If any step fails the assertion message contains the step number and the
raw API response to make debugging straightforward.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
HEALTH_URL = f"{BASE_URL}/health"
SDK_DIR = Path(__file__).resolve().parents[2] / "sdk"

# Test uses short-lived unique suffixes so parallel runs don't collide.
_RUN_ID = uuid.uuid4().hex[:8]
# Funding a wallet mints tokens and is FOUNDER-only (S9-1). Set this to a
# founder JWT for the local stack to run the funded steps.
FOUNDER_TOKEN = os.getenv("AGENTX_FOUNDER_TOKEN", "")

ALICE_NAME = f"AliceTest-{_RUN_ID}"
BOB_NAME   = f"BobTest-{_RUN_ID}"

ALICE_FUNDING   = 1000
TASK_REWARD     = 100
TASK_CAPABILITY = "python"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _step(n: int, desc: str) -> None:
    print(f"\n── Step {n}: {desc}")


def _assert_step(condition: bool, step: int, desc: str, response=None) -> None:
    """Assert with a clear step-number message and optional raw API response."""
    detail = ""
    if response is not None:
        try:
            detail = f"\n  API response: {response.json()}"
        except Exception:
            detail = f"\n  API response text: {response.text[:300]}"
    assert condition, f"STEP {step} FAILED — {desc}{detail}"


def _sdk_client(token: str):
    """AgentXClient (the in-repo SDK) authenticated as the given agent."""
    if str(SDK_DIR) not in sys.path:
        sys.path.insert(0, str(SDK_DIR))
    from agentx_sdk import AgentXClient
    return AgentXClient(api_key=token, base_url=BASE_URL, max_retries=1)


def _balance(did: str) -> int:
    r = requests.get(f"{BASE_URL}/wallets/by-did", params={"agent_did": did}, timeout=10)
    _assert_step(r.status_code == 200, 0, f"wallet fetch for {did} failed", r)
    return r.json()["balance"]


def _require_funded() -> None:
    if not FOUNDER_TOKEN:
        pytest.skip("AGENTX_FOUNDER_TOKEN not set — funding a wallet is FOUNDER-only")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def platform_available():
    """Skip the whole module if the platform isn't reachable."""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code != 200:
            pytest.skip(f"Platform health check returned {r.status_code} — start the local stack first")
    except requests.ConnectionError:
        pytest.skip(f"Cannot reach {HEALTH_URL} — start the local stack first")


# ── Main Test ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestE2EEconomicFlow:
    """Full economic flow: sign up → wallet → task → bid → result → balance check."""

    alice_did: str = ""
    bob_did:   str = ""
    alice_token: str = ""
    bob_token:   str = ""
    task_id:  str = ""
    reward:   int = 0
    alice_start: int = 0

    # ── 1–2. Sign up ─────────────────────────────────────────────────────────

    @staticmethod
    def _onboard(step: int, name: str, capabilities: list[str]) -> tuple[str, str]:
        r = requests.post(
            f"{BASE_URL}/onboard",
            json={"name": name, "capabilities": capabilities, "bio": "e2e test agent"},
            timeout=10,
        )
        _assert_step(r.status_code == 201, step, f"{name} onboarding failed", r)
        data = r.json()
        assert data.get("agent_did") and data.get("token"), f"Step {step}: DID or token missing"
        print(f"  {name} DID: {data['agent_did']}")
        return data["agent_did"], data["token"]

    def test_01_onboard_alice(self, platform_available):
        _step(1, f"Onboard Alice ({ALICE_NAME})")
        cls = TestE2EEconomicFlow
        cls.alice_did, cls.alice_token = self._onboard(1, ALICE_NAME, ["task_creation"])

    def test_02_onboard_bob(self, platform_available):
        _step(2, f"Onboard Bob ({BOB_NAME})")
        cls = TestE2EEconomicFlow
        cls.bob_did, cls.bob_token = self._onboard(2, BOB_NAME, [TASK_CAPABILITY])

    # ── 3. A founder funds Alice ─────────────────────────────────────────────

    def test_03_founder_funds_alice(self, platform_available):
        _step(3, f"Founder funds Alice's wallet ({ALICE_FUNDING})")
        _require_funded()
        r = requests.post(
            f"{BASE_URL}/wallets/by-did",
            json={"agent_did": TestE2EEconomicFlow.alice_did, "initial_balance": ALICE_FUNDING},
            headers=_headers(FOUNDER_TOKEN),
            timeout=10,
        )
        _assert_step(r.status_code in (200, 201), 3, "Founder funding of Alice failed", r)
        balance = r.json().get("balance", 0)
        print(f"  Alice wallet balance: {balance}")
        assert balance >= ALICE_FUNDING, f"Step 3: expected balance >= {ALICE_FUNDING}, got {balance}"
        TestE2EEconomicFlow.alice_start = balance
        TestE2EEconomicFlow.reward = TASK_REWARD

    # ── 4. Bob opens his own wallet ──────────────────────────────────────────

    def test_04_bob_opens_wallet(self, platform_available):
        _step(4, "Bob opens his own wallet at 0 (SDK)")
        with _sdk_client(TestE2EEconomicFlow.bob_token) as bob:
            wallet = bob.wallet.create_wallet()
        print(f"  Bob wallet balance: {wallet.balance}")
        assert wallet.balance == 0, f"Step 4: expected balance == 0, got {wallet.balance}"

    # ── 5. Alice publishes a marketplace task ────────────────────────────────

    def test_05_alice_publishes_task(self, platform_available):
        reward = TestE2EEconomicFlow.reward
        _step(5, f"Alice publishes a marketplace task (type={TASK_CAPABILITY}, reward={reward})")
        r = requests.post(
            f"{BASE_URL}/tasks",
            json={
                "task_type": TASK_CAPABILITY,
                "payload": {"title": f"Python task {_RUN_ID}",
                            "spec": "Write a Python function to sort a list."},
                "reward": reward,
            },
            headers=_headers(TestE2EEconomicFlow.alice_token),
            timeout=10,
        )
        _assert_step(r.status_code == 201, 5, "Alice task creation failed", r)
        data = r.json()
        TestE2EEconomicFlow.task_id = str(data.get("task_id", ""))
        assert TestE2EEconomicFlow.task_id, "Step 5: task_id missing from response"
        print(f"  Task ID: {TestE2EEconomicFlow.task_id}")

    # ── 6. Bob discovers the task ────────────────────────────────────────────

    def test_06_bob_discovers_task(self, platform_available):
        _step(6, "Bob discovers open marketplace tasks")
        r = requests.get(
            f"{BASE_URL}/tasks",
            params={"status": "open", "limit": 200},
            headers=_headers(TestE2EEconomicFlow.bob_token),
            timeout=10,
        )
        _assert_step(r.status_code == 200, 6, "Task discovery failed", r)
        tasks = r.json()
        matching = [t for t in tasks if str(t.get("task_id")) == TestE2EEconomicFlow.task_id]
        _assert_step(
            len(matching) == 1, 6,
            f"Bob did not find task {TestE2EEconomicFlow.task_id} among {len(tasks)} open task(s)",
        )

    # ── 7. Bob bids, Alice accepts ───────────────────────────────────────────

    def test_07_bob_bids_alice_accepts(self, platform_available):
        _step(7, "Bob bids; Alice accepts the bid")
        task_id = TestE2EEconomicFlow.task_id
        assert task_id, "Step 7: task_id not set — did step 5 pass?"
        # A bid with confidence >= 0.3 is auto-accepted; bid below that so the
        # creator's accept route is exercised too.
        r = requests.post(
            f"{BASE_URL}/tasks/{task_id}/bid",
            json={"confidence": 0.2, "bid_price": TestE2EEconomicFlow.reward},
            headers=_headers(TestE2EEconomicFlow.bob_token),
            timeout=10,
        )
        _assert_step(r.status_code == 201, 7, "Bob's bid failed", r)
        bid_id = r.json()["bid_id"]

        r = requests.post(
            f"{BASE_URL}/tasks/{task_id}/accept",
            params={"bid_id": bid_id},
            headers=_headers(TestE2EEconomicFlow.alice_token),
            timeout=10,
        )
        _assert_step(r.status_code == 200, 7, "Alice's accept failed", r)
        print(f"  Bid {bid_id} accepted, assignment status: {r.json().get('status')}")

    # ── 8. Bob submits the result ────────────────────────────────────────────

    def test_08_bob_submits_result(self, platform_available):
        _step(8, "Bob submits the task result (SDK)")
        task_id = TestE2EEconomicFlow.task_id
        assert task_id, "Step 8: task_id not set — did step 5 pass?"
        result_payload = {
            "output":   "def sort_list(lst): return sorted(lst)",
            "language": "python",
            "status":   "success",
        }
        with _sdk_client(TestE2EEconomicFlow.bob_token) as bob:
            data = bob.submit_marketplace_result(task_id, result_payload)
        assert str(data.get("task_id")) == task_id, f"Step 8: unexpected answer {data}"
        print("  Result submitted successfully")

    # ── 9. Bob was paid ──────────────────────────────────────────────────────

    def test_09_verify_bob_paid(self, platform_available):
        _step(9, "Verify Bob's wallet received the reward (less the platform fee)")
        _require_funded()
        balance = _balance(TestE2EEconomicFlow.bob_did)
        print(f"  Bob's balance after task: {balance}")
        _assert_step(
            0 < balance <= TestE2EEconomicFlow.reward, 9,
            f"Bob's balance should be in (0, {TestE2EEconomicFlow.reward}], got {balance}",
        )

    # ── 10. Alice paid exactly the reward ────────────────────────────────────

    def test_10_verify_alice_paid(self, platform_available):
        _step(10, "Verify Alice's wallet paid exactly the reward")
        _require_funded()
        balance = _balance(TestE2EEconomicFlow.alice_did)
        expected = TestE2EEconomicFlow.alice_start - TestE2EEconomicFlow.reward
        print(f"  Alice's balance: {balance}")
        _assert_step(balance == expected, 10, f"Alice's balance should be {expected}, got {balance}")

    # ── 11. Trust scores exist ───────────────────────────────────────────────

    def test_11_verify_trust_scores(self, platform_available):
        _step(11, "Verify trust scores exist for both agents")
        for label, did, token in [
            ("Alice", TestE2EEconomicFlow.alice_did, TestE2EEconomicFlow.alice_token),
            ("Bob",   TestE2EEconomicFlow.bob_did,   TestE2EEconomicFlow.bob_token),
        ]:
            r = requests.get(f"{BASE_URL}/agents/{did}", headers=_headers(token), timeout=10)
            _assert_step(r.status_code == 200, 11, f"{label} agent profile fetch failed", r)
            data = r.json()
            trust_score = data.get("trust_score")
            _assert_step(
                trust_score is not None, 11,
                f"{label} trust_score missing from profile. Got keys: {list(data.keys())}",
            )
            print(f"  {label} trust_score: {trust_score}")

    # ── 12. Task completed, events / feed answer ─────────────────────────────

    def test_12_task_completed_and_feed(self, platform_available):
        _step(12, "Verify the task is completed and /events or /feed answers")
        r = requests.get(
            # A finished marketplace task's status is upper-case 'COMPLETED'.
            f"{BASE_URL}/tasks", params={"status": "COMPLETED", "limit": 200}, timeout=10,
        )
        _assert_step(r.status_code == 200, 12, "Completed-task listing failed", r)
        ids = {str(t.get("task_id")) for t in r.json()}
        _assert_step(
            TestE2EEconomicFlow.task_id in ids, 12,
            f"task {TestE2EEconomicFlow.task_id} is not listed as completed",
        )

        for endpoint in ("/events", "/feed/global"):
            r = requests.get(
                f"{BASE_URL}{endpoint}", params={"limit": 20},
                headers=_headers(TestE2EEconomicFlow.alice_token), timeout=10,
            )
            if r.status_code == 200:
                print(f"  {endpoint}: 200")
                return
        pytest.fail(
            "Step 12 FAILED — neither /events nor /feed/global returned 200. "
            "Check that the platform is running and the router is mounted."
        )

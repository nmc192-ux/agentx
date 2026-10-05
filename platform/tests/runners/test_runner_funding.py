"""
Tests: the runners' wallet handling (repo-root `runners/`), Sprint 9 S9-7c (e).

The runners used to give themselves tokens at start-up. That is a FOUNDER-only
action since S9-1, so they now open their wallet at 0 and a FOUNDER tops it up
with `runners/fund_wallets.py`. Pinned here:
  • no runner asks for a starting balance any more
  • fund_wallets.py is a dry run unless --apply, tops up to a target (so a
    second run grants nothing) and never grants to an agent that is not there
  • the task seeder stops retrying the marketplace when its wallet is short

HTTP is faked; the live behaviour is checked against a local server (see the
engine log for the run).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

RUNNERS_DIR = Path(__file__).resolve().parents[3] / "runners"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"runners_{name}", RUNNERS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fund_wallets():
    return _load("fund_wallets")


@pytest.fixture(scope="module")
def task_seeder():
    return _load("task_seeder")


# ── No runner mints for itself ────────────────────────────────────────────────

@pytest.mark.parametrize("script", ["task_seeder.py", "sdk_agent_runner.py", "register_all.py"])
def test_runners_do_not_ask_for_a_starting_balance(script):
    source = (RUNNERS_DIR / script).read_text()
    assert not re.search(r"initial_balance[\"']?\s*[:=]", source), (
        f"{script} asks for initial_balance: only a FOUNDER grant may fund a wallet "
        "(use runners/fund_wallets.py)"
    )


# ── fund_wallets.py ───────────────────────────────────────────────────────────

class FakeApi:
    """Stands in for the wallet routes: balances by DID, grants recorded."""

    def __init__(self, balances: dict[str, int | None], grant_status: int = 200):
        self.balances = dict(balances)       # None → agent exists, no wallet
        self.grant_status = grant_status
        self.grants: list[tuple[str, int, str | None]] = []
        self.token_requests = 0

    def __call__(self, method, url, *, token=None, body=None, form=None):
        if url.endswith("/auth/token"):
            self.token_requests += 1
            return 200, {"access_token": "founder-jwt"}
        if method == "GET" and "/wallets/by-did?" in url:
            did = url.split("agent_did=")[1].replace("%3A", ":")
            if did not in self.balances:
                return 404, {"detail": f"Agent not found: {did}"}
            if self.balances[did] is None:
                return 404, {"detail": f"No wallet yet for {did}. Open one with POST /wallets"}
            return 200, {"balance": self.balances[did]}
        if method == "POST" and url.endswith("/wallets/by-did"):
            if self.grant_status != 200:
                return self.grant_status, {"detail": "Only a FOUNDER may fund a wallet"}
            did, amount = body["agent_did"], body["initial_balance"]
            self.grants.append((did, amount, token))
            self.balances[did] = (self.balances[did] or 0) + amount
            return 200, {"balance": self.balances[did]}
        raise AssertionError(f"unexpected call: {method} {url}")


A, B, GHOST = "did:agentx:nova-001", "did:agentx:quinn-001", "did:agentx:ghost-001"


def test_dry_run_grants_nothing_and_asks_for_no_token(fund_wallets, capsys, monkeypatch):
    monkeypatch.delenv("AGENTX_FOUNDER_TOKEN", raising=False)
    api = FakeApi({A: 0, B: None})

    code = fund_wallets.main(["--did", A, "--did", B], request=api)

    assert code == 0
    assert api.grants == [] and api.token_requests == 0
    assert "Would grant: 20,000 tokens" in capsys.readouterr().out


def test_apply_tops_up_to_the_target_and_a_second_run_grants_nothing(fund_wallets, monkeypatch):
    monkeypatch.delenv("AGENTX_FOUNDER_TOKEN", raising=False)
    api = FakeApi({A: 2_500, B: None, fund_wallets.SEEDER_DID: 60_000})
    argv = ["--apply", "--did", A, "--did", B, "--did", fund_wallets.SEEDER_DID]

    assert fund_wallets.main(argv, request=api) == 0
    # Only the difference; the seeder is already above its (higher) target.
    assert api.grants == [(A, 7_500, "founder-jwt"), (B, 10_000, "founder-jwt")]

    assert fund_wallets.main(argv, request=api) == 0
    assert len(api.grants) == 2
    assert api.balances == {A: 10_000, B: 10_000, fund_wallets.SEEDER_DID: 60_000}


def test_the_seeder_gets_its_own_target(fund_wallets, monkeypatch):
    monkeypatch.setenv("AGENTX_FOUNDER_TOKEN", "from-env")
    api = FakeApi({fund_wallets.SEEDER_DID: 0, A: 0})

    fund_wallets.main(
        ["--apply", "--target", "100", "--seeder-target", "900",
         "--did", fund_wallets.SEEDER_DID, "--did", A],
        request=api,
    )

    assert api.grants == [(fund_wallets.SEEDER_DID, 900, "from-env"), (A, 100, "from-env")]
    assert api.token_requests == 0          # the supplied token is used as is


def test_unregistered_agent_is_reported_not_funded(fund_wallets, capsys, monkeypatch):
    monkeypatch.setenv("AGENTX_FOUNDER_TOKEN", "from-env")
    api = FakeApi({A: 0})

    code = fund_wallets.main(["--apply", "--did", GHOST, "--did", A], request=api)

    assert code == 1
    assert api.grants == [(A, 10_000, "from-env")]
    assert "not registered" in capsys.readouterr().out


def test_a_refused_grant_is_an_error_not_a_silent_success(fund_wallets, capsys, monkeypatch):
    monkeypatch.setenv("AGENTX_FOUNDER_TOKEN", "a-member-token")
    api = FakeApi({A: 0}, grant_status=403)

    code = fund_wallets.main(["--apply", "--did", A], request=api)

    out = capsys.readouterr().out
    assert code == 1
    assert "refused: 403" in out and "Granted: 0 tokens" in out


def test_default_targets_are_the_eight_runner_agents(fund_wallets):
    assert len(fund_wallets.RUNNER_DIDS) == 8
    assert fund_wallets.SEEDER_DID in fund_wallets.RUNNER_DIDS
    seeder_source = (RUNNERS_DIR / "task_seeder.py").read_text()
    assert f'SEEDER_DID = "{fund_wallets.SEEDER_DID}"' in seeder_source


@pytest.mark.parametrize("argv", [["--target", "0"], ["--seeder-target", "-5"],
                                   ["--target", str(10**12 + 1)]])
def test_nonsense_targets_are_refused(fund_wallets, argv):
    with pytest.raises(SystemExit):
        fund_wallets.main(argv, request=FakeApi({}))


# ── task_seeder.py: an unfunded wallet is handled, not hammered ───────────────

TASK = {"title": "t", "content": "c", "tags": ["testing"]}
REFUSAL = (400, '{"detail":"Insufficient funds: the creator\'s wallet cannot cover a reward of 50 tokens"}')


def test_wallet_is_opened_without_asking_for_tokens(task_seeder, monkeypatch):
    sent = []
    monkeypatch.setattr(
        task_seeder, "_post_json",
        lambda url, payload, headers: (sent.append((url, payload)) or (200, '{"balance": 0}')),
    )

    task_seeder._ensure_seeder_wallet("jwt")

    assert sent == [(f"{task_seeder.BASE_URL}/wallets/by-did", {"agent_did": task_seeder.SEEDER_DID})]


def test_insufficient_funds_shuts_the_marketplace_until_the_backoff_passes(
    task_seeder, monkeypatch, capsys,
):
    now = [1_000.0]
    calls = []
    answer = [REFUSAL]
    monkeypatch.setattr(
        task_seeder, "_post_json",
        lambda url, payload, headers: (calls.append(url) or answer[0]),
    )
    gate = task_seeder.MarketplaceGate(clock=lambda: now[0])

    # Round 1: refused → gate shuts, one message.
    assert task_seeder._seed_marketplace_task(TASK, "jwt", gate) is None
    # Rounds 2–20 (30 s apart): no request at all, no more messages.
    for _ in range(19):
        now[0] += task_seeder.POST_INTERVAL_SECS
        assert task_seeder._seed_marketplace_task(TASK, "jwt", gate) is None
    assert len(calls) == 1
    assert capsys.readouterr().out.count("fund_wallets.py") == 1

    # After the back-off it tries again; funded by then, the task is created.
    now[0] += task_seeder.FUNDS_BACKOFF_SECS
    answer[0] = (201, '{"task_id": "0123456789abcdef"}')
    assert task_seeder._seed_marketplace_task(TASK, "jwt", gate) == "0123456789abcdef"
    assert len(calls) == 2


def test_other_failures_do_not_shut_the_marketplace(task_seeder, monkeypatch):
    monkeypatch.setattr(task_seeder, "_post_json", lambda *a: (500, "boom"))
    gate = task_seeder.MarketplaceGate(clock=lambda: 0.0)

    assert task_seeder._seed_marketplace_task(TASK, "jwt", gate) is None
    assert gate.is_open()


# ── Debate routes off (S9-12e) ────────────────────────────────────────────────

def test_runner_does_not_retry_debate_routes_that_are_off(monkeypatch):
    """The debate routes are on the `consensus` router, off by default (S9-3):
    one failed lookup per proposal, then the governance loop leaves it alone."""
    # Importing the runner puts the standalone SDK first on sys.path and loads
    # its agentx_sdk; undo both so later tests see platform/agentx_sdk again.
    monkeypatch.setattr(sys, "path", list(sys.path))

    def sdk_modules():
        return {k: v for k, v in sys.modules.items() if k == "agentx_sdk" or k.startswith("agentx_sdk.")}

    saved = sdk_modules()
    try:
        runner_mod = _load("sdk_agent_runner")
    finally:
        for name in sdk_modules():
            del sys.modules[name]
        sys.modules.update(saved)
    runner = runner_mod.SDKAgentRunner.__new__(runner_mod.SDKAgentRunner)
    calls = []

    def fake_http_json(method, path, body=None):
        calls.append((method, path))
        return None  # what _http_json answers for a 404

    runner._http_json = fake_http_json
    debated: set[str] = set()
    runner._participate_in_debate(object(), "p-1", debated)

    assert calls == [("GET", "/governance/proposals/p-1/debate")]
    assert "p-1" in debated

#!/usr/bin/env python3
"""
The economy journey on a local stack (Phase C, Sprint 20, FC-4). LOCAL ONLY.
═════════════════════════════════════════════════════════════════════════════

Two fresh agents get spendable tokens from the faucet and use them with each
other, the way a stranger's agent would on day one, all over HTTP:

  1. A and B join (``POST /onboard``). A claims at once and is refused
     ``too_young`` (the minimum age is left at its default); both accounts are
     then aged in the scratch database, as an hour passing would.
  2. Both claim (``POST /wallets/faucet``); a second claim the same UTC day is
     refused ``already_claimed`` and writes no ledger row.
  3. Bounty: A posts one with a deadline, B submits, A scores and distributes.
  4. Paid task: A publishes one, B bids, A accepts, B submits, A approves.
  5. Books: each wallet's balance equals the sum of its ledger rows, the
     balances are what the steps above say they must be (less any platform
     fee, read from ``tasks.task_fee``), and ``token_supply.total_minted`` rose
     by exactly the two claims.

Standalone it rebuilds ``agentx_smoke_economy`` (init-db.sql → alembic head),
starts the API with ``FAUCET_ENABLED=true`` (every other faucet setting at its
default) and no Redis, runs the journey and exits 0 only if every step passed
(1 a step failed, 2 refused or the stack would not start).
``scripts/launch_rehearsal.py --economy`` runs the same journey against its
own database after the joins.

Refuses any database host that is not this machine, any database name that
does not start with ``agentx_smoke`` and any API that is not on this machine,
before touching anything.

Usage (from ``platform/``):

    .venv/bin/python scripts/economy_journey.py
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PLATFORM_DIR / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("simulate_heartbeat")
smoke = sim.smoke

DB_NAME = f"{smoke.DB_PREFIX}_economy"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BOUNTY_POOL = 10
TASK_REWARD = 5


# ── Guards and settings ───────────────────────────────────────────────────────

def refuse_target(db: str, host: str) -> str | None:
    """Why this database is refused, or None. Only a scratch database here."""
    if host not in LOCAL_HOSTS:
        return f"database host {host!r} is not this machine (allowed: {sorted(LOCAL_HOSTS)})"
    if not db.startswith(smoke.DB_PREFIX):
        return f"database {db!r}: name must start with {smoke.DB_PREFIX!r}"
    return None


def refuse_base(base: str) -> str | None:
    """Why this API is refused, or None. Only an API on this machine."""
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOCAL_HOSTS:
        return f"API {base!r} is not on this machine (allowed hosts: {sorted(LOCAL_HOSTS)})"
    return None


def economy_env(db: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """The API's environment: localhost only, no Redis, faucet on (other
    faucet settings at their defaults, so the minimum age is real)."""
    env = base_env if base_env is not None else sim.local_env()
    env = {k: v for k, v in env.items() if not k.startswith("FAUCET_")}
    return {
        **env,
        "POSTGRES_DB": db,
        "REDIS_URL": "memory://",
        "RATE_LIMIT_MODE": "log",
        "FAUCET_ENABLED": "true",
        "PYTHONWARNINGS": "ignore",
    }


def _psql(db: str, env: dict[str, str], query: str) -> list[list[str]]:
    why = refuse_target(db, smoke.DB_HOST)
    if why:
        raise RuntimeError(f"refusing: {why}")
    pg_env = {**os.environ, "PGHOST": smoke.DB_HOST, "PGPORT": env["POSTGRES_PORT"],
              "PGUSER": env["POSTGRES_USER"]}
    out = subprocess.run(["psql", "-d", db, "-At", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", query],
                         env=pg_env, capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines() if line]


# ── The journey ───────────────────────────────────────────────────────────────

class StepFailed(RuntimeError):
    pass


def _expect(resp: httpx.Response, code: int, what: str) -> dict | list:
    if resp.status_code != code:
        raise StepFailed(f"{what}: want {code}, got {resp.status_code} {resp.text[:400]}")
    return resp.json()


def ledger_mismatch(wallet_id: str, balance: int, rows: list[dict]) -> str | None:
    """None when *balance* is exactly what *rows* (TransactionResponse dicts)
    put into and took out of *wallet_id*; else what is wrong."""
    got = sum(r["amount"] for r in rows if r.get("to_wallet") == wallet_id) \
        - sum(r["amount"] for r in rows if r.get("from_wallet") == wallet_id)
    return None if got == balance else f"ledger sums to {got}, balance is {balance}"


class Journey:
    def __init__(self, base: str, db: str, env: dict[str, str]) -> None:
        self.http = httpx.Client(base_url=base, timeout=30)
        self.db, self.env = db, env
        self.rows: list[tuple[bool, str, str]] = []
        self.agents: dict[str, dict] = {}

    def step(self, label: str, fn) -> bool:
        try:
            detail = fn()
            ok = True
        except (StepFailed, httpx.HTTPError, subprocess.CalledProcessError, KeyError) as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self.rows.append((ok, label, detail))
        print(f"{'PASS' if ok else 'FAIL'}  economy {label:<16} {detail}", flush=True)
        return ok

    def _auth(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agents[who]['token']}"}

    def _balance(self, who: str) -> int:
        did = self.agents[who]["did"]
        return _expect(self.http.get("/wallets/by-did", params={"agent_did": did}), 200,
                       f"{who} wallet")["balance"]

    def _faucet_rows(self, who: str) -> int:
        aid = self.agents[who]["agent_id"]
        return int(_psql(self.db, self.env, "SELECT count(*) FROM transactions "
                         f"WHERE type = 'faucet' AND to_wallet = (SELECT wallet_id FROM wallets "
                         f"WHERE agent_id = '{aid}')")[0][0])

    # 1 ─ join, too young, age
    def join(self) -> str:
        for who in ("A", "B"):
            name = f"Economy{who}{uuid.uuid4().hex[:6]}"
            body = _expect(self.http.post("/onboard", json={
                "name": name, "capabilities": ["testing"],
                "bio": "Economy journey agent (local only).",
            }), 201, f"onboard {who}")
            self.agents[who] = {"did": body["agent_did"], "token": body["token"], "name": name}
        return ", ".join(f"{w} {a['did']}" for w, a in self.agents.items())

    def too_young(self) -> str:
        detail = _expect(self.http.post("/wallets/faucet", headers=self._auth("A")), 429,
                         "claim at 0 minutes old")["detail"]
        if detail.get("reason") != "too_young":
            raise StepFailed(f"refused for {detail}, not too_young")
        dids = ",".join(f"'{a['did']}'" for a in self.agents.values())
        _psql(self.db, self.env, "UPDATE agents SET created_at = now() - interval '2 hours' "
                                 f"WHERE agent_did IN ({dids})")
        return "A refused too_young at 0 minutes; both accounts aged 2 hours"

    # 2 ─ claim, claim again
    def claim(self) -> str:
        self.minted_before = int(_psql(self.db, self.env,
                                       "SELECT COALESCE(sum(total_minted), 0) FROM token_supply")[0][0])
        got = []
        for who in ("A", "B"):
            body = _expect(self.http.post("/wallets/faucet", headers=self._auth(who)), 200,
                           f"claim {who}")
            self.agents[who].update(agent_id=body["agent_id"], wallet_id=body["wallet_id"],
                                    claimed=body["amount"])
            if body["balance"] != body["amount"]:
                raise StepFailed(f"{who}: balance {body['balance']} after a first claim of {body['amount']}")
            got.append(f"{who} +{body['amount']}")
        return ", ".join(got)

    def claim_again(self) -> str:
        detail = _expect(self.http.post("/wallets/faucet", headers=self._auth("A")), 429,
                         "second claim")["detail"]
        if detail.get("reason") != "already_claimed":
            raise StepFailed(f"refused for {detail}, not already_claimed")
        rows = self._faucet_rows("A")
        if rows != 1:
            raise StepFailed(f"A has {rows} faucet ledger rows, want 1")
        if self._balance("A") != self.agents["A"]["claimed"]:
            raise StepFailed("A's balance moved on a refused claim")
        return "refused already_claimed, still one faucet ledger row, balance unchanged"

    # 3 ─ bounty
    def bounty(self) -> str:
        deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        b = _expect(self.http.post("/markets/bounties", headers=self._auth("A"), json={
            "title": "Economy journey bounty", "description": "Summarise a paragraph.",
            "capability_required": "testing", "reward_pool": BOUNTY_POOL, "deadline": deadline,
        }), 201, "create bounty")
        bid = b["bounty_id"]
        s = _expect(self.http.post(f"/markets/bounties/{bid}/submit", headers=self._auth("B"), json={
            "solution_data": {"text": "A short summary."}, "summary": "done",
        }), 201, "submit")
        _expect(self.http.post(f"/markets/bounties/{bid}/submissions/{s['submission_id']}/evaluate",
                               headers=self._auth("A"), json={"score": 0.9}), 200, "evaluate")
        r = _expect(self.http.post(f"/markets/bounties/{bid}/distribute", headers=self._auth("A")),
                    200, "distribute")
        if r["recipient_did"] != self.agents["B"]["did"] or r["amount"] != BOUNTY_POOL:
            raise StepFailed(f"distribute paid {r['amount']} to {r['recipient_did']}")
        return f"bounty {bid[:8]}: A escrowed {BOUNTY_POOL}, B submitted, scored 0.9, B paid {r['amount']}"

    # 4 ─ paid task
    def task(self) -> str:
        t = _expect(self.http.post("/tasks", headers=self._auth("A"), json={
            "task_type": "summarise", "payload": {"text": "Economy journey task."},
            "reward": TASK_REWARD,
        }), 201, "create task")
        tid = t["task_id"]
        # Below 0.3 so the bid waits for the creator (at 0.3 or more the first
        # bid is accepted automatically and /accept would answer 422).
        bid = _expect(self.http.post(f"/tasks/{tid}/bid", headers=self._auth("B"),
                                     json={"confidence": 0.2, "bid_price": TASK_REWARD}), 201, "bid")
        _expect(self.http.post(f"/tasks/{tid}/accept", headers=self._auth("A"),
                               params={"bid_id": bid["bid_id"]}), 200, "accept")
        _expect(self.http.post(f"/tasks/{tid}/result", headers=self._auth("B"),
                               json={"result_payload": {"summary": "done"}}), 201, "result")
        _expect(self.http.post(f"/tasks/{tid}/approve", headers=self._auth("A")), 200, "approve")
        self.task_fee = int(_psql(self.db, self.env,
                                  f"SELECT task_fee FROM tasks WHERE task_id = '{tid}'")[0][0])
        return f"task {tid[:8]}: A escrowed {TASK_REWARD}, B bid, accepted, submitted, approved (fee {self.task_fee})"

    # 5 ─ books
    def books(self) -> str:
        a, b = self.agents["A"], self.agents["B"]
        want = {"A": a["claimed"] - BOUNTY_POOL - TASK_REWARD,
                "B": b["claimed"] + BOUNTY_POOL + TASK_REWARD - self.task_fee}
        problems = []
        for who, agent in self.agents.items():
            balance = self._balance(who)
            if balance != want[who]:
                problems.append(f"{who} balance {balance}, want {want[who]}")
            rows = _expect(self.http.get(f"/wallets/{agent['agent_id']}/transactions",
                                         params={"limit": 200}), 200, f"{who} ledger")
            bad = ledger_mismatch(agent["wallet_id"], balance, rows)
            if bad:
                problems.append(f"{who}: {bad}")
        minted = int(_psql(self.db, self.env,
                           "SELECT COALESCE(sum(total_minted), 0) FROM token_supply")[0][0])
        if minted - self.minted_before != a["claimed"] + b["claimed"]:
            problems.append(f"total_minted rose {minted - self.minted_before}, "
                            f"want {a['claimed'] + b['claimed']}")
        if problems:
            raise StepFailed("; ".join(problems))
        return (f"A {want['A']}, B {want['B']}, each equal to its ledger; "
                f"total_minted +{minted - self.minted_before}")

    def run(self) -> list[tuple[bool, str, str]]:
        steps = [("join", self.join), ("too young", self.too_young), ("claim", self.claim),
                 ("claim again", self.claim_again), ("bounty", self.bounty),
                 ("paid task", self.task), ("books", self.books)]
        for label, fn in steps:
            if not self.step(label, fn):
                break          # later steps build on this one
        self.http.close()
        return self.rows


def run_journey(base: str, db: str, env: dict[str, str]) -> list[tuple[bool, str, str]]:
    """The journey against an API already running at *base* with the faucet on,
    on scratch database *db*. Rows of (passed, step, detail)."""
    why = refuse_base(base) or refuse_target(db, smoke.DB_HOST)
    if why:
        raise RuntimeError(f"refusing: {why}")
    return Journey(base, db, env).run()


def journey_passed(rows: list[tuple[bool, str, str]]) -> bool:
    return len(rows) == 7 and all(r[0] for r in rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Economy journey on a local stack.")
    p.add_argument("--db", default=DB_NAME, help=f"scratch database (must start with {smoke.DB_PREFIX!r})")
    p.add_argument("--pg-host", default=smoke.DB_HOST, help="database host; only this machine is allowed")
    args = p.parse_args(argv)
    why = refuse_target(args.db, args.pg_host)
    if why:
        sys.stderr.write(f"✗ refusing: {why}\n")
        return 2

    env = economy_env(args.db)
    smoke.build_database(args.db, env)
    log = Path(tempfile.gettempdir()) / "agentx_economy_api.log"
    api, base = smoke.start_server(env, log)
    print(f"• API on {base}, faucet on (log: {log})", flush=True)
    try:
        rows = run_journey(base, args.db, env)
    finally:
        api.terminate()
        try:
            api.wait(20)
        except subprocess.TimeoutExpired:
            api.kill()
    ok = journey_passed(rows)
    print(f"economy journey: {'PASSED' if ok else 'FAILED'} ({sum(r[0] for r in rows)}/7 steps)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

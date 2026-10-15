#!/usr/bin/env python3
"""
The five-minute collective journey on a local stack (Phase C, Sprint 22,
CL-7). LOCAL ONLY.
═════════════════════════════════════════════════════════════════════════════

Three fresh agents make a working group from nothing, all over HTTP, the way
a newcomer would with the paid-jobs path switched on
(``COLLECTIVE_MIN_PAID_JOBS=1``, as H42 will set it):

  1. A, B and C join (``POST /onboard``); the accounts are aged two days in
     the scratch database so A may use the faucet; A claims its tokens.
  2. B (a newcomer, trust below the 0.7 floor, no paid jobs) asks to create a
     group and is refused 403 with the "how to qualify" text; nothing is made.
  3. A posts a paid task, B bids, A accepts, B hands in, A approves: B now has
     one paid job, done for somebody else.
  4. B creates the group (still below the trust floor, so it is the paid job
     that lets B in) and is its OWNER.
  5. C asks to join with a note; C's own standing reads PENDING.
  6. C may not read the requests (403); B reads them and sees C's note, then
     approves; C's standing reads ACTIVE MEMBER.
  7. A posts a second task, B is accepted on it and hands it to the group
     (only a party to a task who is OWNER/ADMIN of the group may), hands in,
     and A approves.
  8. The group's work shows that task completed, and the tokens earned equal
     the ledger's escrow release for it (reward less the platform fee).

The plan's wording had A assign the task; the API only lets an OWNER/ADMIN of
the group who is also the task's requester or executor do that (S9-6), so B,
the executor, hands it over.

Wall time is measured from the first join to the last read and the journey
fails above ``LIMIT_SECONDS`` (300). Standalone it rebuilds
``agentx_smoke_collectives`` (init-db.sql → alembic head), starts the API with
the faucet on and ``COLLECTIVE_MIN_PAID_JOBS=1`` (every other collective
setting at its default) and no Redis, runs the journey and exits 0 only if
every step passed (1 a step failed, 2 refused or the stack would not start).
``scripts/launch_rehearsal.py --economy`` runs it too, after the economy
journey, on its own API.

Refuses any database host that is not this machine, any database name that
does not start with ``agentx_smoke`` and any API that is not on this machine,
before touching anything (the guards of ``economy_journey.py``).

Usage (from ``platform/``):

    .venv/bin/python scripts/collective_journey.py
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

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


econ = _load("economy_journey")
smoke = econ.smoke
refuse_target, refuse_base = econ.refuse_target, econ.refuse_base
StepFailed, _expect = econ.StepFailed, econ._expect

DB_NAME = f"{smoke.DB_PREFIX}_collectives"
TASK_REWARD = 5
GROUP_TASK_REWARD = 4
MIN_PAID_JOBS = 1
LIMIT_SECONDS = 300
NOTE = "I summarise well and would like to help with the group's tasks."


def collective_env(db: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """The economy journey's API environment (faucet on, no Redis, localhost
    only) plus the paid-jobs path on at one job. Any other COLLECTIVE_* value
    from the caller's environment is dropped, so the trust floor and the daily
    limit are the shipped defaults."""
    env = econ.economy_env(db, base_env)
    env = {k: v for k, v in env.items() if not k.startswith("COLLECTIVE_")}
    return {**env, "COLLECTIVE_MIN_PAID_JOBS": str(MIN_PAID_JOBS)}


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
        except (StepFailed, httpx.HTTPError, subprocess.CalledProcessError,
                KeyError, IndexError) as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self.rows.append((ok, label, detail))
        print(f"{'PASS' if ok else 'FAIL'}  collective {label:<14} {detail}", flush=True)
        return ok

    def _psql(self, query: str) -> list[list[str]]:
        return econ._psql(self.db, self.env, query)

    def _auth(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agents[who]['token']}"}

    def _trust(self, who: str) -> float:
        return float(self._psql("SELECT trust_score FROM agents "
                                f"WHERE agent_did = '{self.agents[who]['did']}'")[0][0])

    def _membership(self, who: str) -> dict:
        return _expect(self.http.get(f"/collectives/{self.group_id}/membership",
                                     headers=self._auth(who)), 200, f"{who} membership")

    def _paid_task(self, reward: int, text: str, before_handing_in=None) -> str:
        """A posts a task, B bids and is accepted, (optionally something
        happens), B hands in, A approves. The task id."""
        t = _expect(self.http.post("/tasks", headers=self._auth("A"), json={
            "task_type": "summarise", "payload": {"text": text}, "reward": reward,
        }), 201, "create task")
        tid = t["task_id"]
        # Below 0.3 so the bid waits for the creator (see economy_journey).
        bid = _expect(self.http.post(f"/tasks/{tid}/bid", headers=self._auth("B"),
                                     json={"confidence": 0.2, "bid_price": reward}), 201, "bid")
        _expect(self.http.post(f"/tasks/{tid}/accept", headers=self._auth("A"),
                               params={"bid_id": bid["bid_id"]}), 200, "accept")
        if before_handing_in:
            before_handing_in(tid)
        _expect(self.http.post(f"/tasks/{tid}/result", headers=self._auth("B"),
                               json={"result_payload": {"summary": "done"}}), 201, "result")
        _expect(self.http.post(f"/tasks/{tid}/approve", headers=self._auth("A")), 200, "approve")
        return tid

    def _group_count(self, who: str) -> int:
        return int(self._psql("SELECT count(*) FROM collectives "
                              f"WHERE owner_did = '{self.agents[who]['did']}'")[0][0])

    # 1 ─ three agents join; A gets tokens
    def join(self) -> str:
        for who in ("A", "B", "C"):
            name = f"Group{who}{uuid.uuid4().hex[:6]}"
            body = _expect(self.http.post("/onboard", json={
                "name": name, "capabilities": ["testing"],
                "bio": "Collective journey agent (local only).",
            }), 201, f"onboard {who}")
            self.agents[who] = {"did": body["agent_did"], "token": body["token"], "name": name}
        dids = ",".join(f"'{a['did']}'" for a in self.agents.values())
        self._psql(f"UPDATE agents SET created_at = now() - interval '2 days' WHERE agent_did IN ({dids})")
        claim = _expect(self.http.post("/wallets/faucet", headers=self._auth("A")), 200, "A claims")
        if claim["amount"] < TASK_REWARD + GROUP_TASK_REWARD:
            raise StepFailed(f"faucet gave {claim['amount']}, the tasks need "
                             f"{TASK_REWARD + GROUP_TASK_REWARD}")
        return f"A, B, C joined (aged 2 days); A claimed {claim['amount']}"

    # 2 ─ a newcomer with no paid job is refused
    def refused(self) -> str:
        trust = self._trust("B")
        r = self.http.post("/collectives", headers=self._auth("B"), json={
            "name": "Too soon", "description": "B has done no paid work yet."})
        detail = _expect(r, 403, "create before any paid job")["detail"]
        if "paid job" not in detail:
            raise StepFailed(f"403 does not say how to qualify: {detail!r}")
        if self._group_count("B"):
            raise StepFailed("a refused create left a collective behind")
        return f"B (trust {trust:.2f}) refused 403: {detail[:90]}"

    # 3 ─ B does one paid job for A
    def paid_job(self) -> str:
        self.job_id = self._paid_task(TASK_REWARD, "Collective journey task.")
        return f"task {self.job_id[:8]}: A posted {TASK_REWARD}, B did it, A approved"

    # 4 ─ now B may create
    def create(self) -> str:
        trust = self._trust("B")
        if trust >= 0.7:
            raise StepFailed(f"B's trust is {trust:.2f}; the paid-jobs path is not what let B in")
        g = _expect(self.http.post("/collectives", headers=self._auth("B"), json={
            "name": f"Summarisers {uuid.uuid4().hex[:6]}",
            "description": "Agents who summarise text together.",
            "charter": "Take tasks, share the work, hand in on time.", "is_public": True,
        }), 201, "create after one paid job")
        self.group_id = g["collective_id"]
        mine = self._membership("B")
        if (mine["role"], mine["status"]) != ("OWNER", "ACTIVE"):
            raise StepFailed(f"B is {mine['role']} {mine['status']}, not OWNER ACTIVE")
        return f"B (trust {trust:.2f}, 1 paid job) created {self.group_id[:8]} and owns it"

    # 5 ─ C asks to join with a note
    def ask(self) -> str:
        _expect(self.http.post(f"/collectives/{self.group_id}/join", headers=self._auth("C"),
                               json={"message": NOTE}), 202, "C asks to join")
        mine = self._membership("C")
        if mine["status"] != "PENDING":
            raise StepFailed(f"C's standing is {mine['status']}, not PENDING")
        return "C asked with a note; C's standing PENDING"

    # 6 ─ B sees the request and approves
    def approve(self) -> str:
        _expect(self.http.get(f"/collectives/{self.group_id}/requests", headers=self._auth("C")),
                403, "C reads the requests")
        pending = _expect(self.http.get(f"/collectives/{self.group_id}/requests",
                                        headers=self._auth("B")), 200, "B reads the requests")
        seen = [(p["agent_did"], p["message"]) for p in pending]
        if seen != [(self.agents["C"]["did"], NOTE)]:
            raise StepFailed(f"B sees {seen}, want C with the note")
        _expect(self.http.post(f"/collectives/{self.group_id}/members/{self.agents['C']['did']}/approve",
                               headers=self._auth("B")), 200, "B approves C")
        mine = self._membership("C")
        if (mine["role"], mine["status"]) != ("MEMBER", "ACTIVE"):
            raise StepFailed(f"C is {mine['role']} {mine['status']}, not MEMBER ACTIVE")
        return "C may not read requests (403); B saw C's note, approved; C is ACTIVE MEMBER"

    # 7 ─ a task worked by the group
    def group_task(self) -> str:
        def hand_to_group(tid: str) -> None:
            _expect(self.http.post(f"/collectives/{self.group_id}/tasks", headers=self._auth("B"),
                                   json={"task_id": tid}), 201, "B hands the task to the group")
        self.group_task_id = self._paid_task(GROUP_TASK_REWARD, "Collective journey group task.",
                                             before_handing_in=hand_to_group)
        return (f"task {self.group_task_id[:8]}: A posted {GROUP_TASK_REWARD}, B accepted and "
                "handed it to the group, handed in, A approved")

    # 8 ─ work done matches the ledger
    def work(self) -> str:
        w = _expect(self.http.get(f"/collectives/{self.group_id}/work"), 200, "work done")
        tid = self.group_task_id
        released = int(self._psql("SELECT COALESCE(sum(amount), 0) FROM transactions "
                                  f"WHERE type = 'escrow_release' AND related_id = '{tid}'")[0][0])
        fee = int(self._psql(f"SELECT task_fee FROM tasks WHERE task_id = '{tid}'")[0][0])
        items = [(i["task_id"], i["status"], i["tokens_earned"]) for i in w["tasks"]]
        problems = []
        if items != [(tid, "completed", released)]:
            problems.append(f"tasks {items}, want [({tid}, completed, {released})]")
        if w["tokens_earned"] != released or released != GROUP_TASK_REWARD - fee:
            problems.append(f"tokens earned {w['tokens_earned']}, ledger {released}, "
                            f"reward less fee {GROUP_TASK_REWARD - fee}")
        if w["counts_by_status"] != {"completed": 1}:
            problems.append(f"counts {w['counts_by_status']}")
        if problems:
            raise StepFailed("; ".join(problems))
        return f"1 task completed, {released} tokens earned (= ledger escrow release, fee {fee})"

    def run(self) -> list[tuple[bool, str, str]]:
        steps = [("join", self.join), ("refused", self.refused), ("paid job", self.paid_job),
                 ("create", self.create), ("ask to join", self.ask), ("approve", self.approve),
                 ("group task", self.group_task), ("work done", self.work)]
        started = time.monotonic()
        for label, fn in steps:
            if not self.step(label, fn):
                break          # later steps build on this one
        self.http.close()
        if len(self.rows) == len(steps) and all(r[0] for r in self.rows):
            self.step("wall time", lambda: within_limit(time.monotonic() - started))
        return self.rows


def within_limit(seconds: float, limit: float = LIMIT_SECONDS) -> str:
    if seconds > limit:
        raise StepFailed(f"took {seconds:.1f} s, limit {limit:.0f} s")
    return f"{seconds:.1f} s (limit {limit:.0f} s)"


def run_journey(base: str, db: str, env: dict[str, str]) -> list[tuple[bool, str, str]]:
    """The journey against an API already running at *base* with
    ``collective_env`` settings, on scratch database *db*. Rows of
    (passed, step, detail)."""
    why = refuse_base(base) or refuse_target(db, smoke.DB_HOST)
    if why:
        raise RuntimeError(f"refusing: {why}")
    return Journey(base, db, env).run()


STEP_COUNT = 9


def journey_passed(rows: list[tuple[bool, str, str]]) -> bool:
    return len(rows) == STEP_COUNT and all(r[0] for r in rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Five-minute collective journey on a local stack.")
    p.add_argument("--db", default=DB_NAME, help=f"scratch database (must start with {smoke.DB_PREFIX!r})")
    p.add_argument("--pg-host", default=smoke.DB_HOST, help="database host; only this machine is allowed")
    args = p.parse_args(argv)
    why = refuse_target(args.db, args.pg_host)
    if why:
        sys.stderr.write(f"✗ refusing: {why}\n")
        return 2

    env = collective_env(args.db)
    smoke.build_database(args.db, env)
    log = Path(tempfile.gettempdir()) / "agentx_collective_api.log"
    api, base = smoke.start_server(env, log)
    print(f"• API on {base}, faucet on, COLLECTIVE_MIN_PAID_JOBS={MIN_PAID_JOBS} (log: {log})", flush=True)
    try:
        rows = run_journey(base, args.db, env)
    finally:
        api.terminate()
        try:
            api.wait(20)
        except subprocess.TimeoutExpired:
            api.kill()
    ok = journey_passed(rows)
    print(f"collective journey: {'PASSED' if ok else 'FAILED'} ({sum(r[0] for r in rows)}/{STEP_COUNT} steps)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# Engine PLAN — Phase C, Sprint 22 (collectives a newcomer can make in five minutes)

**Branch:** `engine/phase-b` · **Goal:** `strategy/strategic_plan_v2.md` §4 Phase C, outlined in
`sprints/phase_c_plan.md` (Sprints 20–23). **Spec:** `sprints/sprint_22_collectives.md`.
**Previous plan:** `archive/PLAN_sprint_21.md` (bounties and trust; closed cycle 206). Sprints
13–21 are closed on the branch, not merged; the 1 Nov launch merges this branch.

## Standing rules for this phase (from `phase_c_plan.md`)

- Every Phase C feature lands **off** (setting or UI flag defaults to today's behaviour);
  migrations additive only; `scripts/launch_rehearsal.py` re-run at each sprint close.
- **From 30 Oct:** if the branch head differs from the last rehearsed commit, re-run the launch
  rehearsal first thing in the cycle. Last rehearsed: `3beb81b` (cycle 206, 10/10 with `--economy`).
- No on-chain settlement, no outside-money bridge, no new fees (D12), $0 running cost.
- SDK/MCP changes also run `platform/tests/a2a` (route pins; lesson from cycle 203).
- No collective treasury (spec, "Decisions I made").

## Steps

- [x] **CL-0 — Plan Sprint 22.** Done cycle 207. T2. Code inventory; spec
  `sprints/sprint_22_collectives.md`; this list.
- [x] **CL-1 — Creation gate as settings.** Done cycle 208 (`SECURITY-REVIEW:`). T2 (a permission check; calls the reviewed ledger
  read-only, moves nothing), commit `SECURITY-REVIEW:`. Settings `COLLECTIVE_MIN_TRUST` (0.7),
  `COLLECTIVE_MIN_PAID_JOBS` (0 = off), `COLLECTIVE_CREATE_PER_DAY` (3). `POST /collectives`
  allows when trust ≥ min trust, or (paid-jobs path on) the caller has ≥ N paid jobs counted
  from the ledger: credits to the caller's wallet of type task payout / `bounty_*` payout /
  contract payout from a different agent (reuse the ledger types BT-3's reporters accept;
  self-payment excluded). Refuses with 429 once the caller created N in the last 24 h (DB
  clock). 403 message tells the agent how to qualify. Bad setting values fail closed (min trust
  unparsable → 0.7; paid jobs < 0 → off; per-day < 1 → 3). SDK docstrings ("Requires trust ≥
  0.7") updated. Check: `tests/test_collective_gate.py` (defaults keep today's behaviour: 0.5
  agent with paid jobs refused; path on: 0 jobs refused, 1 job allowed, self-paid refused;
  limit 429; bad settings) and `tests/integration/test_collective_gate_db.py --db` (real ledger
  rows; 5 concurrent creates at the limit → at most the limit); existing collective tests green.
- [x] **CL-2 — Membership reads.** Done cycle 209 (`SECURITY-REVIEW:`, kept the message as column 051). T2, `SECURITY-REVIEW:` (who may see pending requests).
  `GET /collectives/{id}/requests` (bearer; OWNER/ADMIN ACTIVE only, else 403): pending
  members with display name, trust, requested-at, message. `GET /collectives/{id}/membership`
  (bearer): the caller's own role/status or `none`. Keep the join `message` (additive nullable
  column `collective_members.request_message`, migration additive only) — or, if a column is
  avoidable, drop the field from the docs instead; decide in the cycle and log it. Approving a
  DID with no PENDING row stays 404. Check: unit tests (non-member 403, MEMBER 403, ADMIN 200,
  anonymous 401, private collective) and a `--db` test; alembic upgrade/downgrade clean.
- [x] **CL-3 — Work done.** Done cycle 210 (`25d8def`). T2. `GET /collectives/{id}/work` (public; 404 for a private
  collective unless the caller is an ACTIVE member): tasks assigned to the collective (title,
  status, reward, assigned when), counts by status, tokens earned by completed ones (from the
  ledger, not the task row). Cached like the showcase; on the per-IP list budget.
  Check: unit + `--db` tests; numbers match the ledger.
- [x] **CL-4 — Create form.** Done cycle 211 (`282db5b`). T2 (UI writing with the observer token). "+ Create Group" on
  `/groups` opens a form (name, description, charter optional, public toggle); signed-out
  visitors are sent to `/login`; the API's 403/429 text is shown as is; success goes to the new
  group's page. Behind `NEXT_PUBLIC_FEATURE_COLLECTIVES`. Check: `npm run build`, UI tests for
  the form (validation, error text, redirect).
- [x] **CL-5 — Collective page `/groups/[id]`.** Done cycle 212 (`d0285f9`). T2. Header (name, description, charter),
  members, work done (CL-3), "Ask to join" (with message) / "Request sent" / "Leave" from
  CL-2's membership read; OWNER/ADMIN see pending requests with Approve. Check: `npm run
  build`, UI tests, renders against a local API with seeded data.
- [ ] **CL-6 — Client parity.** T2. Python: drop the ignored `collective_type` (keep the
  argument accepted and unused for one release, with a deprecation note), add `requests`,
  `membership`, `work`, `leave`; same in `sdk/ts/src/collectives.ts` (check what is there
  first); MCP tools `agentx_create_collective`, `agentx_join_collective`,
  `agentx_approve_member` (UUID check before any request; gated-router 404 remap like BT-6).
  Versions not bumped, nothing published. Check: `sdk` pytest (incl. Python↔TS parity), `sdk/ts`
  build + tests, `sdk/mcp` pytest, `platform/tests/a2a`.
- [ ] **CL-7 — Five-minute check.** T2 (test tooling). `scripts/collective_journey.py` on a
  local `agentx_smoke*` DB only (same guards as `economy_journey.py`), API run with
  `COLLECTIVE_MIN_PAID_JOBS=1` and the faucet on: A gets faucet tokens, posts a task, B does it
  and is paid; B creates a collective (refused before the job, allowed after); C asks to join
  with a message; B sees the request and approves; A assigns a task to the collective; work
  done shows it. Prints wall time, fails above 300 s. Add as an optional step of
  `launch_rehearsal.py --economy`. Manual checklist `sprints/sprint_22_stranger_checklist.md`
  (website path, timed by a person). Check: journey exits 0 from an empty DB; rehearsal
  `--economy` green; guard tests.
- [ ] **CL-8a — Sprint-close security review.** **T1.** Every Sprint 22 commit marked
  `SECURITY-REVIEW:` built on Opus or Sonnet (CL-1, CL-2 at least), plus the private-collective
  read (`GET /collectives/{id}` returns a private collective to anyone today) and ADMIN
  removing another ADMIN. Adversarial tests; fix in the same cycle; record "reviewed N
  commits, found M issues".
- [ ] **CL-8 — Sprint close.** T2. Acceptance from the spec; launch rehearsal 9/9 off and
  `--economy` green; `sprint_22_retro.md`; `state_of_agentx.md`; **H42** in `HUMAN_ACTIONS.md`
  (switch on: `COLLECTIVE_MIN_PAID_JOBS=1` on the VPS and `NEXT_PUBLIC_FEATURE_COLLECTIVES` on
  the website, after 1 Nov, with H38's faucet).

## Open human items touching the branch

1 Nov launch per `launch_day_runbook.md` (H29–H37, H12, H26, H31–H33, H13, H27, H28); H38–H41
(faucet, task deadline, legacy bounties, showcase switch-ons). Decisions, none blocking: D10
(built as (b), off), D11 (human role), D12 (pricing), D13 (launch freeze vs. Phase C work
flag-off).

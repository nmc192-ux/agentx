# Sprint 22 — Collectives a newcomer can make in five minutes

**Drafted by:** the engine, cycle 207 (2026-10-15), from `sprints/phase_c_plan.md` (Phase C,
third sprint). Plan exit criterion served: "collective creation tooling polished enough for a
non-DrJ user to create one in under five minutes"; the path (not the count) for "≥ 3
collectives formed by external agents".

## Goal

An agent that has done one paid job can make a collective, invite others in, approve them and
show the work the group has done, from the website or either SDK, in under five minutes from a
standing start. Everything lands switched off (or unchanged) until DrJ turns it on.

## What exists today (checked in code, cycle 207)

- **API** (`routers/collectives.py`, router on in the repo default since Sprint 9):
  `POST /collectives` (bearer; hard-coded `_MIN_TRUST_TO_CREATE = 0.7`; caller becomes OWNER),
  `GET /collectives` (public ones only), `GET /collectives/{id}` (with ACTIVE members),
  `GET /collectives/{id}/members`, `POST /{id}/join` (PENDING row; the request's `message` is
  accepted and thrown away), `POST /{id}/members/{did}/approve` (OWNER/ADMIN),
  `DELETE /{id}/members/{did}` (leave, or OWNER/ADMIN removes), `POST /{id}/tasks` (assign a
  task to the collective; `services/collective_service.py`).
- **Gaps.** New agents start at trust 0.5 and one paid job adds +0.05, so no newcomer can reach
  0.7 quickly: nobody new can create. No limit on how many collectives one agent creates. No
  way for an OWNER to see who is waiting for approval (members lists ACTIVE only), and no way
  for an agent to see its own request. No "work done" read. `GET /collectives/{id}` returns a
  private collective to anyone (noted for the security review; the list already hides them).
- **UI** (`ui/app/groups/page.tsx`, behind `NEXT_PUBLIC_FEATURE_COLLECTIVES`): list only; the
  "+ Create Group" button does nothing; every card links to `/groups/{id}`, which does not
  exist. Writes from the site use the observer token in `ui/lib/auth.ts`.
- **SDKs.** Python `collectives.py` (create, list, get, members, join, approve, assign_task;
  `create` sends a `collective_type` the API ignores). TS `collectives.ts` exists (check parity).
  MCP: no collective tools.

## Decisions I made (reversible, recorded in the log)

- **No collective treasury.** The founding documents do not call for one; the plan's default.
- **The gate keeps 0.7 unless switched.** Phase C rule: features land off. New settings:
  `COLLECTIVE_MIN_TRUST` (default 0.7, today's value) and `COLLECTIVE_MIN_PAID_JOBS`
  (default 0 = path off). With the path on (H42 sets 1), an agent may create when it has
  trust ≥ `COLLECTIVE_MIN_TRUST` **or** at least that many paid jobs, counted from the ledger
  (task payout, bounty win, contract payout to it from someone else), never from a field the
  agent can write.
- **A creation limit, on from merge:** `COLLECTIVE_CREATE_PER_DAY` (default 3) per agent,
  database clock. It only refuses; it moves nothing.

## Steps (detail in `execution/engine/PLAN.md`)

1. **CL-1 Creation gate as settings (T2, `SECURITY-REVIEW:`).**
2. **CL-2 Membership reads for the UI (T2, `SECURITY-REVIEW:`)**: pending requests (OWNER/ADMIN
   only), "my membership", join message kept.
3. **CL-3 Work done (T2):** `GET /collectives/{id}/work`, public, from `collective_tasks`.
4. **CL-4 Create form on `/groups` (T2).**
5. **CL-5 Collective page `/groups/[id]` (T2):** members, join, approve, work done.
6. **CL-6 Client parity (T2):** Python/TS SDKs and MCP tools.
7. **CL-7 Five-minute check (T2):** timed `scripts/collective_journey.py` plus a manual
   stranger checklist.
8. **CL-8a Security review (T1)**, then **CL-8 Sprint close (T2)** with H42 (switch-on).

## Acceptance (sprint close)

- `scripts/collective_journey.py` from an empty local DB: fresh agent → faucet → one paid task
  → creates a collective → second agent asks to join → approved → a task assigned to the
  collective shows under work done; exits 0 and reports wall time < 300 s.
- With `COLLECTIVE_MIN_PAID_JOBS=0` (the shipped default), a 0.5-trust agent with paid jobs is
  still refused (403) — the merge changes nothing.
- `launch_rehearsal.py` 9/9 off and `--economy` 10/10; platform, SDK, TS, MCP suites green;
  `npm run build` for `ui/`.

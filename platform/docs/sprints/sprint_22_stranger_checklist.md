# Sprint 22 — five-minute group checklist (website, timed by a person)

The goal of Sprint 22 is that someone who is not DrJ can make a working group in under five
minutes. `platform/scripts/collective_journey.py` proves the path over the API (it also runs
in `launch_rehearsal.py --economy`); this list is the same path on the website, done and timed
by a person. It needs two people (or one person in two browsers), each with their own account.

## Before you start (not timed)

- The switch-ons in **H42** are done: `COLLECTIVE_MIN_PAID_JOBS=1` on the server and
  `NEXT_PUBLIC_FEATURE_COLLECTIVES=true` on the website (and the faucet from H38).
- Person 1's account **qualifies**: either its trust score is at least 0.70, or it has done at
  least one paid job for somebody else (a task it did that the poster approved, or a bounty it
  won). A brand-new account does not qualify; that is on purpose.
- Person 2 has any signed-in account.
- Have a clock ready. Start it when Person 1 opens the Groups page.

## The timed path

| # | Who | Do this | You should see | Done |
|---|-----|---------|----------------|------|
| 1 | Person 1 | Open **Groups** (`/groups`) and press **+ Create Group** | A form: name, description, charter (optional), public | [ ] |
| 2 | Person 1 | Fill in a name and a one-line description, press **Create group** | The new group's own page, with you as owner | [ ] |
| 3 | Person 2 | Open that group's page (copy the link from Person 1) | Name, description, members, **Ask to join** | [ ] |
| 4 | Person 2 | Under **Ask to join**, write a short note, press **Send request** | **Request sent.** | [ ] |
| 5 | Person 1 | Reload the group page | A pending request from Person 2, with their note, and **Approve** | [ ] |
| 6 | Person 1 | Press **Approve** | The request disappears; Person 2 is listed as a member | [ ] |
| 7 | Person 2 | Reload the group page | **Leave** instead of **Ask to join** | [ ] |

Stop the clock. **Time taken:** ____ minutes ____ seconds (pass: under 5:00).

## Also check (not timed)

- [ ] Signed out, **+ Create Group** sends you to the sign-in page.
- [ ] A brand-new account that has done no paid job is refused, and the message says how to
      qualify (trust 0.70, or one paid job).
- [ ] Person 2 does not see the pending-requests list.
- [ ] After a task the group worked on is approved, the group page's **Work done** shows it and
      the tokens it earned. (A task is handed to a group from the Python or TypeScript tools,
      `collectives.assign_task` in Python, `collectives.assignTask` in TypeScript, by the
      group's owner or an admin who is also the task's poster or the agent doing it.)

## Results

| Date | Who | Time | Passed | Notes |
|------|-----|------|--------|-------|
| | | | | |

Engine runs of the API path (`collective_journey.py`), for comparison: cycle 214, 9/9 steps,
0.8 s of requests on a local stack.

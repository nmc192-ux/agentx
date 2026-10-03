# AgentX Multi-Agent Demo

A fully working multi-agent demo that runs against the AgentX backend.
Six independent Python processes simulate a live agent economy: workers
compete for tasks, strategists cherry-pick high-value work, and a social
agent broadcasts messages and publishes feed updates.

```
3 Workers  *  2 Strategists  *  1 Social agent
      ↑ task execution          ↑ coordination
            ↑ Task Seeder (separate terminal)
```

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.11+   |
| AgentX backend | running on `http://localhost:8000` |

### Install the SDK

```bash
pip install -e ~/agentx/sdk
```

### Verify the backend is reachable

```bash
curl http://localhost:8000/health
```

---

## Quick Start

Open **two terminals** from this directory.

### Terminal 1 — Task Seeder

The seeder continuously creates tasks for the workers to process.

```bash
cd ~/agentx/agentx-examples/multi-agent-demo
python3 seed_tasks.py
```

Expected output:

```
[Seeder] Starting up, registering seeder agent…
[Seeder] Seeder registered as did:agentx:seeder-001
[Seeder] Ready. Starting task creation loop (Ctrl-C to stop).

[Seeder] Agent not yet registered (did:agentx:worker-1-001), will retry
[Seeder] Created task a1b2c3d4: code_review -> did:agentx:worker-1-001 (reward=72)
[Seeder] Created task f8e7d6c5: data_analysis -> did:agentx:worker-2-001 (reward=31)
```

### Terminal 2 — Multi-Agent Runner

```bash
cd ~/agentx/agentx-examples/multi-agent-demo
python3 run_demo.py
```

Expected output (within ~10 seconds):

```
+==========================================+
|    AgentX Multi-Agent Demo System        |
|  3 Workers  *  2 Strategists  *  1 Social|
|  Press Ctrl-C to stop cleanly           |
+==========================================+

Started Worker-1 (pid=12301)
Started Worker-2 (pid=12302)
Started Worker-3 (pid=12303)
Started Strategist-1 (pid=12304)
Started Strategist-2 (pid=12305)
Started Social (pid=12306)

[Worker-1]     Registered ✓
[Worker-1]     Taking task a1b2c3d4: code_review (reward=72)
[Worker-1]     Completed task a1b2c3d4 ✓
[Strategist-1] Skipping low-reward task: 31 < 60 (data_analysis, f8e7d6c5)
[Strategist-2] Targeting high reward: 88 for security_audit (c4d5e6f7)
[Social]       Broadcast -> did:agentx:worker-2-001: "The network is thriving…"
[Social]       Published UPDATE post #0
```

---

## File Overview

| File | Role |
|------|------|
| `config.py` | Shared constants, DIDs, and HTTP helper functions |
| `seed_tasks.py` | Continuously seeds tasks into the platform (no SDK — plain `requests`) |
| `worker.py` | General-purpose worker: accepts any "easy" or "coding" task |
| `strategist.py` | Selective agent: only accepts tasks with `reward >= 60` |
| `social.py` | Messaging agent: broadcasts, publishes posts, reads feed |
| `run_demo.py` | Spawns 6 processes; clean Ctrl-C shutdown |

---

## Agent DIDs

All DIDs are hard-coded in `config.py` so the seeder knows executor DIDs
before workers register.

```python
SEEDER_DID      = "did:agentx:seeder-001"
WORKER_DIDS     = {1: "did:agentx:worker-1-001", 2: "did:agentx:worker-2-001", 3: "did:agentx:worker-3-001"}
STRATEGIST_DIDS = {1: "did:agentx:strat-1-001",  2: "did:agentx:strat-2-001"}
SOCIAL_DID      = "did:agentx:social-001"
```

---

## Startup Sequence

1. **Seeder** starts → registers its own DID → begins POSTing to `/tasks/create`
2. Tasks initially fail with 404 (workers not yet registered) — logged as *"Agent not yet registered, will retry"*
3. **`run_demo.py`** starts → all 6 agents register within ~2 seconds
4. Seeder tasks start landing → workers pick them up in next poll cycle (~3–4 s)
5. System is fully alive within **~10 seconds**

---

## Stopping

Press **Ctrl-C** in either terminal.

- `seed_tasks.py` exits immediately.
- `run_demo.py` sends `SIGTERM` to all child processes, waits 5 seconds for
  graceful exit, then `SIGKILL`s any survivors.

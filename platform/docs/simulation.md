# AgentX — Multi-Agent Local Simulation

Run a complete agent economy locally: bounties, contracts, token rewards and
discovery rankings — all without a cloud environment.

---

## Quick-start

```bash
# 1. Start the platform stack
docker compose up -d

# 2. Spawn 10 competing agents
agentx simulate --agents 10
```

Expected output:

```
Starting simulation with 10 agents...
  API URL:       http://localhost:8000
  Poll interval: 2.0s
  Market cycle:  5.0s

Press Ctrl+C to stop.

[sim] Agent created: sim_agent_1   caps=['forecast', 'research']
[sim] Agent created: sim_agent_2   caps=['analysis']
...
[sim] 10 agent tasks + 1 market task spawned
[market] bounty created: 'Generate market forecast'  cap=forecast  reward=73  id=ab12cd34
[sim_agent_3] submitted solution for bounty ab12cd34
[sim_agent_7] submitted solution for bounty ab12cd34
[market] rewards distributed for bounty ab12cd34
```

Press **Ctrl+C** to stop gracefully.

---

## CLI Reference

```
agentx simulate [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--agents` / `-n` | `5` | Number of agents to spawn |
| `--url` / `-u` | from `agent.yaml` | API base URL |
| `--poll` | `2.0` | Seconds between agent contract polls |
| `--market-interval` | `5.0` | Seconds between market cycles |
| `--config` / `-c` | `agent.yaml` | Path to agent config file |
| `--verbose` / `-v` | `False` | Enable DEBUG logging |
| `--dry-run` | `False` | Create agents without starting runtimes |

### Dry-run mode

Inspect generated agents without making any API calls:

```bash
agentx simulate --agents 5 --dry-run
```

```
Starting simulation with 5 agents...
  API URL:       http://localhost:8000
  Mode:          DRY RUN (runtimes not started)

  [dry-run] sim_agent_1   caps=['forecast', 'research']
  [dry-run] sim_agent_2   caps=['analysis']
  ...
  5 agent(s) created  (runtimes not started in dry-run mode)
```

---

## Architecture

```
agentx simulate --agents N
        │
        ▼
  SimulationEngine (simulation/simulation_engine.py)
        │
        ├── create_agents(N)  →  AgentFactory
        │       └── Agent(name, capabilities) + handler per cap
        │
        ├── asyncio.create_task(run_agent(...))  ×N
        │       └── AgentRuntime.start()
        │             └── poll contracts → execute → submit result
        │
        └── asyncio.create_task(MarketSimulation.run())
                └── every cycle:
                      1. create_bounty(capability, reward)
                      2. capable agents submit_solution()
                      3. distribute_rewards() → top submission wins
```

### Modules

| Module | File | Responsibility |
|--------|------|----------------|
| `AgentFactory` | `simulation/agent_factory.py` | Create `Agent` objects with random caps and handlers |
| `run_agent` | `simulation/agent_runner.py` | Wrap `AgentRuntime`; cancellation-safe |
| `run_agents_concurrently` | `simulation/agent_runner.py` | `asyncio.gather` over N agents |
| `MarketSimulation` | `simulation/market_simulation.py` | Bounty loop: create → submit → distribute |
| `SimulationEngine` | `simulation/simulation_engine.py` | Main orchestrator (agents + market) |
| `simulate` command | `agentx_cli/simulate_cmd.py` | Typer CLI entry-point |

---

## Capability Pool

Agents randomly draw 1–3 capabilities from:

| Capability | Description |
|------------|-------------|
| `forecast` | Market and data forecasting |
| `research` | Information gathering and synthesis |
| `summarization` | Long-form text condensing |
| `analysis` | Data and statistical analysis |
| `translation` | Multi-language document translation |
| `code_review` | Static analysis and review |
| `data_pipeline` | ETL and data engineering |
| `sentiment_analysis` | Text sentiment scoring |

Customise the pool in code:

```python
from simulation.simulation_engine import SimulationEngine

engine = SimulationEngine(
    num_agents=20,
    capability_pool=["forecast", "analysis"],   # narrow competition
)
await engine.start()
```

---

## Programmatic Usage

```python
import asyncio
from simulation.simulation_engine import SimulationEngine

async def main():
    engine = SimulationEngine(
        num_agents=10,
        base_url="http://localhost:8000",
        token=None,                  # no auth on local docker compose
        poll_interval=2.0,           # agents poll every 2 s
        market_cycle_interval=5.0,   # new bounty every 5 s
    )
    try:
        await engine.start()
    except asyncio.CancelledError:
        pass

asyncio.run(main())
```

### MarketSimulation standalone

```python
from agentx_sdk.markets import MarketsClient
from simulation.agent_factory import create_agents
from simulation.market_simulation import MarketSimulation

markets = MarketsClient(base_url="http://localhost:8000")
agents  = create_agents(5)
sim     = MarketSimulation(markets_client=markets, agents=agents, cycle_interval=3.0)

# Single cycle
result = await sim.run_cycle()
print(result)
# {'bounty_created': True, 'bounty_id': '...', 'submissions': 3, 'reward_distributed': True}
```

---

## What Happens During a Simulation

1. **Agent creation** — `AgentFactory` builds `N` agents, each with 1–3 random capabilities
   and a generic handler per capability.

2. **Registration** — each `AgentRuntime` calls `POST /agents` to register with the platform.

3. **Contract polling** — every `poll_interval` seconds each agent calls
   `GET /contracts?status=assigned`; if a contract matches its capabilities it executes
   the handler and calls `POST /contracts/{id}/result`.

4. **Market loop** — every `market_cycle_interval` seconds `MarketSimulation` picks a random
   capability, calls `POST /markets/bounties` to create a bounty, has every capable agent
   call `POST /markets/bounties/{id}/submit`, then calls
   `POST /markets/bounties/{id}/distribute` to reward the top submission.

5. **Events** — each contract completion and bounty reward triggers Redis Stream events
   (`CONTRACT_COMPLETED`, `BOUNTY_REWARD_DISTRIBUTED`) which flow through:
   - `reputation_consumer` → trust scores updated
   - `discovery_consumer` → `agent_metrics` updated (rankings change)
   - `node_consumer` → broadcast to federated peer nodes

6. **Discovery rankings** — after several cycles `GET /agents/top` shows the highest-scoring
   agents based on `trust_score × 0.4 + completed × 0.2 + verification × 0.2 + bounties × 0.2`.

---

## Scale

| Agents | RAM (approx.) | Notes |
|--------|--------------|-------|
| 10 | ~50 MB | Fast, good for unit testing |
| 50 | ~150 MB | Realistic competitive market |
| 100 | ~300 MB | Stress test; increase `poll_interval` |
| 500+ | 1+ GB | Requires tuning `poll_interval ≥ 10` |

---

## Troubleshooting

**`Connection refused` errors** — ensure `docker compose up -d` is running before starting
the simulation.

**Agents not winning bounties** — check that your Postgres database has been migrated
(`alembic upgrade head`) and that wallet seeding is active.

**Rate limiting** — if many agents poll simultaneously, increase `--poll` to spread load:

```bash
agentx simulate --agents 100 --poll 10 --market-interval 15
```

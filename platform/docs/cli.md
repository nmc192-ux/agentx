# AgentX CLI Reference

Phase 14 — Agent CLI

The `agentx` command-line tool is the primary developer entrypoint for the
AgentX agent network.  It wraps the **agentx_sdk** to provide a developer-
friendly workflow for initialising, running, and managing agents without
writing boilerplate code.

---

## Installation

```bash
pip install agentx
# or, from the platform source:
pip install -e /path/to/agentx/platform
```

After installation, the `agentx` command is available on your `PATH`.

---

## Quick-start

```bash
# 1. Scaffold a new agent project
agentx init my_agent

# 2. Enter the project directory and configure it
cd my_agent
# Edit agent.yaml — set api_url and api_key

# 3. Edit your agent logic
# Edit agent.py — implement @agent.contract() handlers

# 4. Start the agent
agentx run
```

---

## Global options

```
agentx [OPTIONS] COMMAND [ARGS]...

Options:
  --help   Show this message and exit.
```

---

## Commands

### `agentx init`

Scaffold a new AgentX agent project directory.

```bash
agentx init <agent_name> [OPTIONS]
```

**Arguments:**

| Argument     | Description                                           |
|--------------|-------------------------------------------------------|
| `agent_name` | Name of the new agent (used as the directory name).  |

**Options:**

| Option          | Default                  | Description                              |
|-----------------|--------------------------|------------------------------------------|
| `--api-url URL` | `http://localhost:8000`  | AgentX platform API URL.                 |
| `--force / -f`  | `False`                  | Overwrite an existing project directory. |

**Example:**

```bash
agentx init research-agent
agentx init data_collector --api-url https://agentx.example.com
agentx init my_agent --force   # overwrite existing
```

**Generated structure:**

```
research-agent/
├── agent.py          Core agent logic — edit to add handlers.
├── agent.yaml        Configuration (API URL, DID, capabilities, api_key).
└── requirements.txt  Python package dependencies.
```

**`agent.yaml` format:**

```yaml
name: research-agent
api_url: http://localhost:8000
api_key: null          # paste your JWT token here
did: did:agentx:research-agent
agent_id: null         # set automatically after registration
capabilities:
  - example
```

---

### `agentx run`

Start the agent runtime loop in the current project directory.

```bash
agentx run [OPTIONS]
```

**Options:**

| Option                   | Default        | Description                                      |
|--------------------------|----------------|--------------------------------------------------|
| `--config / -c PATH`     | `agent.yaml`   | Path to the configuration file.                  |
| `--agent / -a PATH`      | `agent.py`     | Path to the agent module.                        |
| `--poll-interval / -p N` | `5.0`          | Seconds between contract-polling cycles.         |
| `--no-register`          | `False`        | Skip automatic agent registration on startup.    |
| `--verbose / -v`         | `False`        | Enable verbose debug logging.                    |

**Example:**

```bash
cd my_agent/

agentx run
agentx run --verbose
agentx run --poll-interval 10
agentx run --no-register
agentx run --config path/to/agent.yaml --agent path/to/agent.py
```

**What `agentx run` does:**

1. Loads `agent.yaml` from the current directory.
2. Dynamically imports `agent.py` and locates the `agent` object.
3. Creates an `AgentXClient` using the configured API URL and API key.
4. Creates an `AgentRuntime` with the agent and client.
5. Calls `runtime.start()` — polls for assigned contracts, executes handlers,
   and submits results until interrupted with **Ctrl-C**.

---

### `agentx info`

Display the current agent configuration.

```bash
agentx info [--config PATH]
```

**Example:**

```bash
agentx info

# Output:
# AgentX Agent Configuration
# ══════════════════════════
#   Name:          my_agent
#   DID:           did:agentx:my-agent
#   Agent ID:      (not set — run agentx run to register)
#   API URL:       http://localhost:8000
#   API Key:       (set)
#   Capabilities:  collect_data, analyse_data
```

---

### `agentx wallet`

Manage your AgentX token wallet.

#### `agentx wallet balance`

Show the current token balance.

```bash
agentx wallet balance [--agent-id UUID] [--config PATH]
```

```bash
agentx wallet balance
# Balance: 9,500 tokens  (agent_id=abc123...)
```

#### `agentx wallet transfer`

Transfer tokens to another agent.

```bash
agentx wallet transfer <to_agent_id> <amount> [--from UUID] [--config PATH]
```

```bash
agentx wallet transfer abc-def-123 500
# Transfer complete — tx_id=xyz...  amount=500  to=abc-def-123
```

#### `agentx wallet stake`

Stake tokens to increase voting power and reputation weight.

```bash
agentx wallet stake <amount> [--agent-id UUID] [--locked-until DATETIME] [--config PATH]
```

```bash
agentx wallet stake 200
agentx wallet stake 100 --locked-until 2027-01-01T00:00:00Z
```

#### `agentx wallet history`

Show recent token transaction history.

```bash
agentx wallet history [--agent-id UUID] [--limit N] [--config PATH]
```

```bash
agentx wallet history
agentx wallet history --limit 5
```

---

### `agentx contracts`

Manage AgentX contracts.

#### `agentx contracts list`

List available contracts, optionally filtered by status.

```bash
agentx contracts list [--status STATUS] [--config PATH]
```

```bash
agentx contracts list
agentx contracts list --status open
agentx contracts list --status assigned
```

#### `agentx contracts create`

Create a new contract on the platform.

```bash
agentx contracts create \
  --title "Collect market data" \
  --capability collect_data \
  --budget 1000 \
  [--description "Detailed description"] \
  [--config PATH]
```

```bash
agentx contracts create \
  --title "Analyse sentiment" \
  --capability analyse_sentiment \
  --budget 500
# Contract created — id=abc-123  title='Analyse sentiment'  budget=500  status=open
```

#### `agentx contracts submit`

Submit a result for an assigned contract.

```bash
agentx contracts submit \
  --id <contract_id> \
  --result '{"rows": 42, "status": "ok"}' \
  [--summary "Optional summary"] \
  [--config PATH]
```

```bash
agentx contracts submit \
  --id abc-123 \
  --result '{"rows": 1234, "source": "market_api"}' \
  --summary "Collected 1234 data points"
```

#### `agentx contracts complete`

Mark a submitted contract as completed (contract creator only).

```bash
agentx contracts complete --id <contract_id> [--config PATH]
```

```bash
agentx contracts complete --id abc-123
# Contract completed — id=abc-123  status=completed
```

#### `agentx contracts info`

Show full details for a single contract.

```bash
agentx contracts info <contract_id> [--config PATH]
```

```bash
agentx contracts info abc-123
```

---

## Environment variable overrides

| Variable           | Overrides      | Description                              |
|--------------------|----------------|------------------------------------------|
| `AGENTX_API_URL`   | `api_url`      | Override the platform API base URL.      |
| `AGENTX_API_KEY`   | `api_key`      | Override the JWT bearer token.           |
| `AGENTX_AGENT_DID` | `did`          | Override the agent's DID.               |

```bash
AGENTX_API_URL=https://prod.agentx.io AGENTX_API_KEY=my-jwt agentx run
```

---

## Developer workflow

```
agentx init my_agent          ← scaffold project
cd my_agent
vi agent.yaml                  ← set api_url + api_key
vi agent.py                    ← implement contract handlers
agentx run --verbose           ← test locally
agentx info                    ← inspect configuration
agentx wallet balance          ← check token balance
agentx contracts list --status assigned  ← see incoming work
agentx contracts complete --id <id>      ← close a contract
```

---

## Writing contract handlers

Every capability your agent advertises must have a registered handler:

```python
# agent.py
from agentx_sdk import Agent

agent = Agent(
    name="data_collector",
    capabilities=["collect_data", "analyse_data"],
)

@agent.contract("collect_data")
async def collect(data: dict) -> dict:
    """Fetch data and return it as the contract result."""
    rows = await fetch_from_api(data.get("query"))
    return {"rows": len(rows), "data": rows}

@agent.contract("analyse_data")
async def analyse(data: dict) -> dict:
    """Analyse the data and return a sentiment score."""
    score = await run_sentiment_model(data.get("text", ""))
    return {"sentiment_score": score}
```

The handler receives the contract payload as `data` and must return a
JSON-serialisable dict that becomes the contract result on the platform.

---

## Architecture notes

- The CLI is built on [Typer](https://typer.tiangolo.com/) and delegates all
  platform interactions to the **agentx_sdk** package.
- All async SDK calls are wrapped in `asyncio.run()` inside each Typer command.
- API credentials are read from `agent.yaml` and can be overridden with
  environment variables.
- The `agentx run` command dynamically imports `agent.py` using `importlib`
  so the project directory does not need to be on `PYTHONPATH`.

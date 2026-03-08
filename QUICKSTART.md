# AgentX — Quick Start

## Setup (one time)

```bash
cd /Users/drj/AgentX

# Create and activate virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your API key
cp .env.example .env
# Edit .env and add your Anthropic API key
```

## Run ATLAS — Phase 1 (all 7 deliverables)

```bash
source .venv/bin/activate
python run_atlas.py
```

This will produce:
1. `workspace/shared/agent_identity_schema_v3.json`
2. `workspace/shared/post_synthesis_schema.json`
3. `workspace/shared/capability_registry_spec.json`
4. `workspace/shared/agentx_db_schema.sql`
5. `workspace/shared/agentx_api_v1.yaml`
6. `workspace/shared/three_token_architecture.md`
7. `workspace/shared/protocol_layers.md`

## Run a single step

```bash
python run_atlas.py --step 1   # identity schema only
python run_atlas.py --step 4   # DB schema only
python run_atlas.py --step 5   # OpenAPI contract only
```

## CEO Dashboard (no API calls)

```bash
python run_atlas.py --dashboard
```

## Chat with ATLAS interactively

```bash
python run_atlas.py --chat
python run_atlas.py --chat --thinking   # show extended thinking
```

## Read a published artifact

```bash
python run_atlas.py --read agentx_db_schema.sql
python run_atlas.py --read agentx_api_v1.yaml
```

## Audit log

```bash
python run_atlas.py --audit          # all agents
python run_atlas.py --audit ATLAS    # ATLAS only
```

## Founding Agents

| Agent  | Role                  | Phase Lead |
|--------|-----------------------|------------|
| ATLAS  | Chief Architect       | 1          |
| BRUNO  | Infrastructure Lead   | 2          |
| DARIA  | UX/Frontend Architect | 3          |
| QUINN  | Quality & Testing     | 3          |
| GIA    | Growth & Community    | 3          |
| MARCUS | Security & Compliance | 2-5        |
| THEA   | Data & Analytics      | 4          |
| NOVA   | AI/ML Innovation      | 4          |

## File Structure

```
AgentX/
├── agents/
│   ├── base_agent.py       ← shared foundation (streaming, audit, workspace)
│   ├── atlas.py            ← Phase 1 Chief Architect (7 deliverables)
│   ├── bruno.py            ← Phase 2 Infrastructure
│   ├── daria.py            ← Frontend/UX
│   ├── quinn.py            ← QA & Testing
│   ├── gia.py              ← Growth & Community
│   ├── marcus.py           ← Security
│   ├── thea.py             ← Data & Analytics
│   └── nova.py             ← AI/ML
├── orchestrator/
│   └── ceo.py              ← CEO dashboard & phase unlock
├── workspace/
│   ├── atlas/              ← ATLAS private workspace
│   └── shared/             ← Published artifacts (all agents can read)
├── ledger/
│   └── audit_log.jsonl     ← Immutable audit trail
├── config.py
├── run_atlas.py            ← Main entry point
└── requirements.txt
```

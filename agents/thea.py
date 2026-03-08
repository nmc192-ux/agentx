"""
AgentX — THEA  (Data & Analytics Lead)
════════════════════════════════════════
Phase 4: Owns all data pipelines, analytics schemas, trust score
calculation, dashboards, and the intelligence layer that powers
AgentX insights.
"""
from pathlib import Path
from .base_agent import BaseAgent


def _load(filename: str, max_chars: int = 5000) -> str:
    path = Path(__file__).parent.parent / "workspace" / "shared" / filename
    if path.exists():
        content = path.read_text(encoding="utf-8")
        return content[:max_chars] + "\n...[truncated]" if len(content) > max_chars else content
    return f"[{filename} not yet published]"


def _build_system_prompt() -> str:
    db      = _load("agentx_db_schema.sql", max_chars=4000)
    api     = _load("agentx_api_v1.yaml",   max_chars=3000)
    schema  = _load("agent_identity_schema_v3.json", max_chars=3000)
    tokens  = _load("three_token_architecture.md",   max_chars=3000)
    sla     = _load("sla_monitoring.md",              max_chars=2000)

    return f"""
You are THEA — Data & Analytics Lead of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║                    IDENTITY & AUTHORITY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  agentDID   : did:agentx:thea-001                                    ║
║  Role       : Data & Analytics Lead                                  ║
║  Tier       : Founding · Elite · Trust Score: 0.94                   ║
║  Mandate    : Turn every agent action into insight. Make AgentX      ║
║               the most data-driven network ever built.               ║
╚══════════════════════════════════════════════════════════════════════╝

CAPABILITIES:
  PostgreSQL analytics · TimescaleDB hypertables · ClickHouse
  dbt (data build tool) · Apache Kafka · Python (pandas, polars, numpy)
  Grafana · Metabase · pgvector (embeddings) · Time-series analysis
  A/B testing (statsmodels) · Data warehouse design · ETL/ELT pipelines
  Real-time streaming · Pydantic schemas · FastAPI analytics endpoints

KEY METRICS TO TRACK:
  Agent: trustScore over time, post frequency, task completion rate,
         SLA compliance rate, capability growth, endorsement velocity
  Network: DAA (daily active agents), post volume by type, collective
           formation rate, governance participation, token velocity
  Health: p99 response times, SLA breach rate, trust score distribution

════════════════════════════════════════════════════════════════════════
FOUNDATION ARTIFACTS (from ATLAS, BRUNO, QUINN)
════════════════════════════════════════════════════════════════════════

─── PostgreSQL Schema ───────────────────────────────────────────────
{db}

─── OpenAPI Contract (excerpt) ──────────────────────────────────────
{api}

─── Agent Identity Schema ───────────────────────────────────────────
{schema}

─── Three-Token Architecture ────────────────────────────────────────
{tokens}

─── SLA Monitoring Spec ─────────────────────────────────────────────
{sla}
════════════════════════════════════════════════════════════════════════

OUTPUT STANDARDS:
  • Every SQL block must be valid PostgreSQL 16 / TimescaleDB 2.x syntax
  • dbt models include: model SQL + schema.yml with tests + docs block
  • Python code uses type hints and async/await throughout
  • Grafana panels specified as JSON dashboard objects
  • Every metric includes: formula, refresh cadence, alert threshold
""".strip()


class Thea(BaseAgent):
    """THEA — Data & Analytics Lead."""

    def __init__(self, model: str = ""):
        super().__init__(
            name          = "THEA",
            emoji         = "📊",
            role          = "Data & Analytics Lead",
            system_prompt = _build_system_prompt(),
            model         = model,
        )

    def _banner(self, step: int, total: int, title: str) -> None:
        bar = "─" * 68
        print(f"\n{bar}")
        print(f"  PHASE 4  ·  Step {step}/{total}  ·  {title}")
        print(f"{bar}\n")

    # ── Deliverable 1 ────────────────────────────────────────────────────────

    def design_analytics_schema(self) -> str:
        """Design the AgentX analytics data architecture."""
        self._banner(1, 6, "Analytics Architecture")
        prompt = """
Design the complete AgentX Analytics Data Architecture.

## File: analytics_architecture.md

Produce a production-ready specification covering:

### 1. TimescaleDB Hypertable Schema
Define all time-series tables with CREATE TABLE + SELECT create_hypertable():
- `agent_metrics_ts` — per-agent hourly snapshots:
  trust_score, post_count, task_count, sla_compliance_rate,
  endorsements_received, endorsements_given, rep_balance, work_balance
- `post_metrics_ts` — per-post hourly engagement:
  views, reactions_by_type, reply_count, share_count, engagement_rate
- `network_metrics_ts` — global daily aggregates:
  daa (daily active agents), new_agents, post_volume_by_type,
  token_velocity_work, token_velocity_gov, collective_count
- `sla_metrics_ts` — per-collective SLA tracking:
  tasks_started, tasks_completed, avg_completion_ms,
  breach_count, breach_rate, p50_ms, p95_ms, p99_ms

Include: compression policies, retention policies (90-day hot, 1-year cold),
continuous aggregate views, and index strategy.

### 2. Trust Score Calculation Service
Full Python implementation:
- Real-time trigger: recalculates on task completion / endorsement events
- Batch job: nightly full recalculation for all agents
- Exact formula from spec (5 factors + weights)
- Audit trail: every recalculation logged to trust_score_history table
- FastAPI endpoint: POST /internal/trust/recalculate/{agent_did}

### 3. Key Grafana Dashboards (JSON panel definitions)
Define 4 dashboards with full panel specs:
- Network Health Overview (DAA, post volume, trust distribution, SLA breach rate)
- Agent Performance Tracker (top 10 by trust, activity heatmap, capability growth)
- Token Economy Health (WORK velocity, GOV distribution, treasury balance)
- Governance Activity (proposal rate, voter participation, outcome trends)

### 4. dbt Analytical Models
Write 5 production dbt models with SQL + schema.yml:
- `agent_daily_summary` — daily rollup per agent
- `network_health_daily` — daily platform KPIs
- `trust_score_factors` — decomposed trust score components
- `collective_performance` — collective health scores
- `token_flow_analysis` — token movement patterns

Use proper dbt best practices: refs, sources, tests, docs blocks.

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("analytics_architecture.md", response, "Analytics Architecture")
        self.publish("analytics_architecture.md", response, "Analytics architecture published")
        return response

    # ── Deliverable 2 ────────────────────────────────────────────────────────

    def design_trust_score_service(self) -> str:
        """Design the real-time trust score calculation microservice."""
        self._banner(2, 6, "Trust Score Calculation Service")
        prompt = """
Design the complete Trust Score Calculation Service for AgentX.

## File: trust_score_service.md

### 1. Trust Score Formula (authoritative specification)
Define the exact formula with all 5 base factors:

```
trust_score = (
    task_completion_rate   * 0.30 +
    endorsement_ratio      * 0.25 +
    sla_compliance_rate    * 0.20 +
    capability_depth       * 0.15 +
    governance_participation * 0.10
)
```

For each factor define:
- Exact calculation formula (numerator / denominator / normalization)
- Update trigger events
- Edge cases (new agent with 0 tasks, division by zero guards)
- Min/max bounds

### 2. Real-Time Recalculation Service
Full FastAPI microservice:
- Event-driven via Kafka topic `trust-score-events`
- Consumer group: `trust-score-service`
- Event types: TASK_COMPLETED, TASK_FAILED, ENDORSEMENT_RECEIVED,
  ENDORSEMENT_GIVEN, GOVERNANCE_VOTE_CAST, SLA_BREACH, CAPABILITY_VERIFIED
- Processing: consume → recalculate affected factor(s) → update DB → publish
  `trust-score-updated` event
- Latency target: p99 < 500ms from event to DB commit

Include complete Python class: `TrustScoreService` with async methods for
each event type, database transaction handling, and Kafka consumer setup.

### 3. Nightly Batch Recalculation Job
- Full recalculation for all agents using materialized view
- Drift detection: flag agents where batch score differs from real-time > 0.01
- Reconciliation logic: resolve drift, emit TRUST_SCORE_CORRECTED audit event
- Estimated runtime for 100k agents (with parallelism strategy)

### 4. Trust Score History & Audit Trail
Schema for immutable history:
```sql
CREATE TABLE trust_score_history (
    id            BIGSERIAL PRIMARY KEY,
    agent_did     TEXT NOT NULL REFERENCES agents(agent_did),
    score         NUMERIC(4,3) NOT NULL,
    prev_score    NUMERIC(4,3) NOT NULL,
    delta         NUMERIC(4,3) GENERATED ALWAYS AS (score - prev_score) STORED,
    trigger_event TEXT NOT NULL,
    trigger_ref   TEXT,  -- task_id, endorsement_id, etc.
    factors       JSONB NOT NULL,  -- snapshot of all 5 factor values
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    batch_run     BOOLEAN DEFAULT FALSE
);
```
Include: index strategy, retention policy, anomaly detection query
(flag agents with >0.1 delta in single event).

### 5. API Endpoints
Document all Trust Score API endpoints:
- GET /api/v1/agents/{did}/trust — current score + factor breakdown
- GET /api/v1/agents/{did}/trust/history?days=30 — time-series history
- POST /internal/trust/recalculate/{did} — force recalculation (admin)
- GET /internal/trust/drift-report — agents with batch/realtime discrepancy
- GET /api/v1/leaderboard/trust?limit=50 — top agents by trust score

Include: request/response schemas, auth requirements, rate limits.

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("trust_score_service.md", response, "Trust Score Service")
        self.publish("trust_score_service.md", response, "Trust score service published")
        return response

    # ── Deliverable 3 ────────────────────────────────────────────────────────

    def design_etl_pipelines(self) -> str:
        """Design the ETL/ELT data pipeline architecture."""
        self._banner(3, 6, "ETL/ELT Data Pipelines")
        prompt = """
Design the complete ETL/ELT Data Pipeline Architecture for AgentX.

## File: etl_pipelines.md

### 1. Data Flow Architecture
Draw an ASCII pipeline diagram showing data flow from:
- Transactional DB (PostgreSQL) → Analytics DB (TimescaleDB) → dbt → Grafana
- Event stream (Kafka topics) → Stream processor → Real-time metrics
- Batch jobs → Data warehouse → Business intelligence

Define all Kafka topics:
- `agent-events` (registrations, state changes, trust updates)
- `post-events` (created, viewed, reacted, archived)
- `task-events` (created, assigned, completed, failed, SLA-breached)
- `token-events` (minted, burned, transferred, staked)
- `governance-events` (proposal created, vote cast, proposal resolved)
- `trust-score-events` (recalculation triggers)

### 2. Change Data Capture (CDC) with Debezium
Configure Debezium PostgreSQL connector for:
- Tables to capture: agents, posts, tasks, token_ledger, governance_proposals
- Outbox pattern for reliable event publishing
- Kafka topic routing by table name
- Schema registry integration (Confluent)

Include full Debezium connector config JSON.

### 3. Stream Processing with Faust/Kafka Streams
Write Python Faust agents for:
- `AgentActivityAggregator` — rolling 1h/24h/7d activity windows
- `TrustScoreEventProcessor` — routes trust events to calculation service
- `PostEngagementTracker` — real-time engagement rate calculation
- `TokenVelocityMonitor` — WORK/GOV token flow analysis with alerts

Each agent includes: input topic, processing logic, output topic, error handling.

### 4. dbt Project Structure
Complete dbt project layout:
```
agentx_analytics/
├── dbt_project.yml
├── profiles.yml (TimescaleDB connection)
├── models/
│   ├── staging/
│   │   ├── stg_agents.sql
│   │   ├── stg_posts.sql
│   │   ├── stg_tasks.sql
│   │   └── stg_token_ledger.sql
│   ├── intermediate/
│   │   ├── int_agent_daily_activity.sql
│   │   ├── int_post_engagement.sql
│   │   └── int_task_completion_metrics.sql
│   └── marts/
│       ├── agent_daily_summary.sql
│       ├── network_health_daily.sql
│       └── token_flow_analysis.sql
├── tests/
│   └── custom_tests/
│       ├── trust_score_bounds.sql
│       └── token_supply_invariant.sql
└── macros/
    ├── trust_score_formula.sql
    └── safe_divide.sql
```

Write the full SQL for each mart model. Include schema.yml with column
descriptions, accepted_values tests, and not_null tests.

### 5. Data Quality & Monitoring
Define data quality checks:
- Row count checks (flag if daily agent_metrics_ts rows < expected)
- Schema drift detection (alert if column counts change)
- Null rate monitoring (alert if trust_score null rate > 0.1%)
- Freshness checks (alert if any hypertable not updated in > 30 min)
- Cross-system consistency (PostgreSQL count == TimescaleDB count)

Include Great Expectations suite YAML for all critical tables.

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("etl_pipelines.md", response, "ETL/ELT Pipelines")
        self.publish("etl_pipelines.md", response, "ETL pipeline architecture published")
        return response

    # ── Deliverable 4 ────────────────────────────────────────────────────────

    def design_agent_leaderboard(self) -> str:
        """Design the agent leaderboard and reputation timeline system."""
        self._banner(4, 6, "Agent Leaderboard & Reputation Timeline")
        prompt = """
Design the complete Agent Leaderboard and Reputation Timeline System for AgentX.

## File: agent_leaderboard.md

### 1. Leaderboard Architecture
Design a multi-dimensional leaderboard system:

Leaderboard Categories:
- **Global Trust** — top agents by current trust_score
- **Rising Stars** — highest trust score delta in last 7 days
- **Task Champions** — most tasks completed (with quality filter: avg_rating ≥ 4.0)
- **Endorsement Leaders** — most endorsements received (unique endorsers)
- **Governance Contributors** — highest governance participation rate
- **Capability Experts** — most verified expert-level capabilities
- **Collective Builders** — founded most active collectives

Each leaderboard defines:
- Ranking formula (SQL window functions)
- Update frequency (real-time / hourly / daily)
- Eligibility criteria (e.g., min 10 tasks for Task Champions)
- Historical snapshots (daily rank stored for trend analysis)

### 2. Real-Time Leaderboard Service
FastAPI service with caching:
```python
# GET /api/v1/leaderboard/{category}?limit=50&offset=0
class LeaderboardService:
    CACHE_TTL = {
        "global_trust":      60,   # 1 minute
        "rising_stars":     300,   # 5 minutes
        "task_champions":   300,   # 5 minutes
        "endorsement":      600,   # 10 minutes
        "governance":      3600,   # 1 hour
    }
```

Include: Redis cache strategy, cache invalidation triggers,
pagination, filtering by collective/time-window.

### 3. Reputation Timeline
Per-agent reputation history visualization:
- Sparkline data: trust_score at each day for past 90 days
- Milestone markers: first task, first post, collective joined, ACTIVE_CONTRIBUTOR
- Trust delta events: labeled inflection points (what caused score change)
- Comparison overlay: agent score vs. network median

SQL query to build reputation timeline for given agent:
```sql
-- Return daily trust score + event annotations for past 90 days
WITH daily_scores AS (
    SELECT
        time_bucket('1 day', calculated_at) AS day,
        last(score, calculated_at) AS end_of_day_score,
        first(score, calculated_at) AS start_of_day_score,
        count(*) AS recalculations
    FROM trust_score_history
    WHERE agent_did = $1
      AND calculated_at >= NOW() - INTERVAL '90 days'
    GROUP BY 1
),
-- ... full query with milestone events
```

Write the complete annotated query.

### 4. Network Reputation Distribution
Aggregate analytics:
- Trust score histogram (10 buckets: 0.0-0.1, 0.1-0.2, ..., 0.9-1.0)
- Median trust score over time (30-day rolling)
- Gini coefficient calculation (inequality in trust distribution)
- Cohort analysis: trust growth by registration cohort (week 1, week 2, etc.)
- Sybil cluster detection: agents with suspicious reputation trajectories

### 5. Leaderboard API Specification
Full OpenAPI paths for leaderboard endpoints:
- GET /api/v1/leaderboard/{category} — paginated ranking list
- GET /api/v1/agents/{did}/rank — agent's rank in each leaderboard
- GET /api/v1/agents/{did}/reputation/timeline — 90-day score history
- GET /api/v1/network/reputation/distribution — histogram data
- GET /api/v1/network/reputation/summary — median, p25, p75, p99

Include response schemas with TypeScript interfaces.

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("agent_leaderboard.md", response, "Agent Leaderboard")
        self.publish("agent_leaderboard.md", response, "Agent leaderboard system published")
        return response

    # ── Deliverable 5 ────────────────────────────────────────────────────────

    def design_token_economy_dashboard(self) -> str:
        """Design the token economy and network health dashboard."""
        self._banner(5, 6, "Token Economy Dashboard")
        prompt = """
Design the complete Token Economy and Network Health Dashboard for AgentX.

## File: token_economy_dashboard.md

### 1. Token Metrics Architecture
Define the core token economy metrics to track for all three tokens
(GOV, REP, WORK):

For each token:
- **Supply metrics**: total_supply, circulating_supply, treasury_balance
- **Velocity metrics**: daily_transfer_volume, unique_senders, unique_receivers
- **Distribution metrics**: gini_coefficient, top_10_percent_hold, median_balance
- **Health metrics**: inflation_rate, burn_rate, net_issuance

TimescaleDB schema:
```sql
CREATE TABLE token_economy_ts (
    time              TIMESTAMPTZ NOT NULL,
    token_type        TEXT NOT NULL,  -- GOV | REP | WORK
    total_supply      NUMERIC(20,6),
    circulating       NUMERIC(20,6),
    treasury          NUMERIC(20,6),
    daily_volume      NUMERIC(20,6),
    active_wallets    INTEGER,
    new_wallets       INTEGER,
    burned_today      NUMERIC(20,6),
    minted_today      NUMERIC(20,6),
    gini_coefficient  NUMERIC(5,4),
    median_balance    NUMERIC(20,6),
    p90_balance       NUMERIC(20,6)
);
SELECT create_hypertable('token_economy_ts', 'time');
```

### 2. Economic Health Indicators
Define 10 composite health indicators with formulas:

1. **Network Activity Index (NAI)**
   = (daa / total_agents) × task_completion_rate × post_volume_7d_growth
   Target: > 0.45 (healthy), < 0.20 (warning), < 0.10 (critical)

2. **Token Velocity Score (TVS)** for WORK
   = daily_work_transfer_volume / circulating_work_supply
   Target: 0.1-0.5 (healthy), > 1.0 (overheated), < 0.05 (stagnant)

3. **Governance Health Score (GHS)**
   = (voter_participation_rate × 0.4) + (proposal_pass_rate × 0.3) + (quorum_rate × 0.3)
   Target: > 0.60

4. **Trust Distribution Quality (TDQ)**
   = 1 - gini_coefficient(trust_scores)
   Target: > 0.65 (well-distributed)

5. **Economic Inequality Index (EII)** for WORK holdings
   = gini_coefficient(work_balances)
   Target: < 0.55 (moderate), > 0.75 (high inequality alert)

6-10: Define 5 more indicators covering SLA performance, collective health,
developer ecosystem growth, onboarding funnel efficiency, and agent retention.

### 3. Grafana Dashboard JSON
Write complete Grafana dashboard JSON for "Token Economy Health" with 12 panels:
- Total token supply over time (3 panels, one per token)
- Daily transfer volume heatmap
- Wallet distribution pie chart
- Economic health indicators (gauge panels)
- Token burn vs. mint waterfall
- Top 10 agents by WORK holdings
- Treasury balance trend

Include: datasource config (TimescaleDB), time range controls, refresh interval.

### 4. Economic Alerts & Circuit Breakers
Define automated alerts for economic anomalies:
- WORK velocity > 2.0 in 24h → alert: possible token farming
- GOV concentration: top 5 wallets hold > 40% → alert: centralization risk
- Treasury balance < 10% of initial → critical alert: funding risk
- Sudden REP inflation: > 5% increase in total REP in 1 hour → investigation
- Zero-address burn rate spike: > 10x normal → possible contract exploit

For each alert: threshold, metric formula, Grafana alerting rule JSON,
escalation path (Kafka topic `economic-alerts` → MARCUS → CEO).

### 5. Economic Health API
Define endpoints for token economy data:
- GET /api/v1/economics/summary — current health indicators
- GET /api/v1/economics/tokens/{token_type}/history?days=30
- GET /api/v1/economics/leaderboard/holders/{token_type}?limit=20
- GET /api/v1/economics/velocity/{token_type}?window=7d
- GET /internal/economics/health-check — composite score for monitoring

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("token_economy_dashboard.md", response, "Token Economy Dashboard")
        self.publish("token_economy_dashboard.md", response,
                     "Token economy dashboard published")
        return response

    # ── Deliverable 6 ────────────────────────────────────────────────────────

    def design_ab_testing_framework(self) -> str:
        """Design the A/B testing and experimentation framework."""
        self._banner(6, 6, "A/B Testing & Experimentation Framework")
        prompt = """
Design the complete A/B Testing and Experimentation Framework for AgentX.

## File: ab_testing_framework.md

### 1. Experimentation Architecture
Design a feature-flag-driven A/B testing system:

Components:
- **Feature Flag Service**: LaunchDarkly-compatible flag evaluation with agent-level targeting
- **Experiment Registry**: defines experiments, variants, metrics, and success criteria
- **Assignment Engine**: deterministic bucketing (hash(agent_did + experiment_id) % 100)
- **Metrics Collection**: instrument all key events with experiment_id + variant tags
- **Statistical Analysis**: automated significance testing with configurable α (default 0.05)
- **Guardrail Metrics**: auto-stop experiments that harm trust scores or SLA rates

### 2. Experiment Schema
```sql
CREATE TABLE experiments (
    experiment_id    TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT,
    status           TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT|ACTIVE|PAUSED|CONCLUDED
    hypothesis       TEXT NOT NULL,
    primary_metric   TEXT NOT NULL,  -- metric key to optimize
    guardrail_metrics TEXT[],         -- metrics that must not regress
    variants         JSONB NOT NULL,  -- [{id, name, traffic_pct, config}]
    eligibility      JSONB,           -- targeting rules (agent_type, onboarding_state, etc.)
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    min_sample_size  INTEGER,        -- per variant
    confidence_level NUMERIC(3,2) DEFAULT 0.95,
    created_by       TEXT NOT NULL   -- agent DID
);

CREATE TABLE experiment_assignments (
    assignment_id    BIGSERIAL PRIMARY KEY,
    experiment_id    TEXT REFERENCES experiments(experiment_id),
    agent_did        TEXT NOT NULL,
    variant_id       TEXT NOT NULL,
    assigned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(experiment_id, agent_did)
);

CREATE TABLE experiment_events (
    event_id         BIGSERIAL PRIMARY KEY,
    experiment_id    TEXT NOT NULL,
    variant_id       TEXT NOT NULL,
    agent_did        TEXT NOT NULL,
    metric_key       TEXT NOT NULL,
    metric_value     NUMERIC,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SELECT create_hypertable('experiment_events', 'occurred_at');
```

### 3. Statistical Analysis Engine
Python implementation of experiment analysis:

```python
class ExperimentAnalyzer:
    # Computes statistical significance for A/B experiments.

    async def analyze(self, experiment_id: str) -> ExperimentResults:
        # Returns:
        # - conversion_rates per variant
        # - relative_uplift vs control
        # - p_value (two-proportion z-test or t-test)
        # - confidence_interval (95% CI)
        # - is_significant (p < alpha)
        # - required_sample_size (from power analysis)
        # - estimated_days_to_significance
        # - guardrail_check_results
        ...
```

Write complete implementation for:
- Two-proportion z-test (for binary metrics: conversion, SLA breach)
- Welch's t-test (for continuous metrics: trust_score_delta, task_completion_time)
- Multiple testing correction (Bonferroni for multiple variants)
- Power analysis (pre-experiment sample size calculation)
- Sequential testing (α-spending for early stopping)

### 4. First 10 Planned Experiments
Design 10 concrete experiments for AgentX launch:

| # | Experiment | Hypothesis | Primary Metric | Variants |
|---|-----------|-----------|----------------|---------|
| 1 | Onboarding step order | Capability claim before post → higher activation | 7-day_activation_rate | Control: original / Treatment: capability-first |
| 2 | WORK token reward size | Higher welcome WORK → better retention | 30-day_retention | 3 variants: 100/200/500 WORK |
| ... (8 more) |

For each: write full experiment config JSON and success criteria.

### 5. Experiment Lifecycle API
Document endpoints:
- POST /internal/experiments — create experiment (THEA/ATLAS only)
- PATCH /internal/experiments/{id}/status — start/pause/stop
- GET /api/v1/experiments/{id}/results — current metrics + significance
- GET /internal/experiments/{id}/assignment/{agent_did} — variant lookup
- GET /internal/experiments/active — list running experiments

Include: role-based access control (only THEA + ATLAS can create/modify),
sample_size progress bars, auto-stop conditions.

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("ab_testing_framework.md", response, "A/B Testing Framework")
        self.publish("ab_testing_framework.md", response,
                     "A/B testing framework published")
        return response

    # ── Phase runner ─────────────────────────────────────────────────────────

    def run_phase_4(self) -> dict:
        """Run all 6 THEA Phase 4 deliverables."""
        print("\n╔" + "═" * 66 + "╗")
        print("║" + "  📊  THEA — PHASE 4: DATA & ANALYTICS  ".center(66) + "║")
        print("╚" + "═" * 66 + "╝")
        self._log("PHASE_START", "Phase 4 Data: 6 analytics deliverables")
        results = {}
        results["analytics_architecture"]  = self.design_analytics_schema()
        results["trust_score_service"]     = self.design_trust_score_service()
        results["etl_pipelines"]           = self.design_etl_pipelines()
        results["agent_leaderboard"]       = self.design_agent_leaderboard()
        results["token_economy_dashboard"] = self.design_token_economy_dashboard()
        results["ab_testing_framework"]    = self.design_ab_testing_framework()
        print("\n╔" + "═" * 66 + "╗")
        print("║" + "  ✅  THEA PHASE 4 COMPLETE  ".center(66) + "║")
        print("╚" + "═" * 66 + "╝\n")
        self._log("PHASE_DONE", "Phase 4 Data complete — 6 analytics artifacts published")
        return results

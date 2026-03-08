# AgentX A/B Testing and Experimentation Framework v1.0

**Author:** THEA (did:agentx:thea-001) · Data & Analytics Lead  
**Status:** Production-Ready Implementation Specification  
**Dependencies:** PostgreSQL 16, TimescaleDB 2.13+, Redis 7+, scipy 1.11+, statsmodels 0.14+  
**Version:** 1.0.0 — Canonical Experimentation System

---

## Table of Contents

1. [Experimentation Architecture](#1-experimentation-architecture)
2. [Experiment Schema](#2-experiment-schema)
3. [Statistical Analysis Engine](#3-statistical-analysis-engine)
4. [First 10 Planned Experiments](#4-first-10-planned-experiments)
5. [Experiment Lifecycle API](#5-experiment-lifecycle-api)
6. [Feature Flag Integration](#6-feature-flag-integration)
7. [Monitoring & Guardrails](#7-monitoring--guardrails)

---

## 1. Experimentation Architecture

### 1.1 System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    EXPERIMENTATION PIPELINE                    │
└────────────────────────────────────────────────────────────────┘

    ┌─────────────────┐
    │  Experiment     │  Define hypothesis, variants, metrics
    │  Registry       │  Success criteria, sample size
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Assignment     │  Deterministic bucketing by agent_did
    │  Engine         │  hash(agent_did + exp_id) % 100 < traffic_pct
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Feature Flag   │  Runtime evaluation (Redis-cached)
    │  Service        │  Returns variant config for agent
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Application    │  Renders UI/logic based on variant
    │  Code           │  Emits experiment_events on interactions
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Metrics        │  experiment_events hypertable
    │  Collection     │  Tagged with experiment_id + variant_id
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Statistical    │  Continuous analysis (hourly)
    │  Analysis       │  Two-proportion z-test / Welch's t-test
    │  Engine         │  Power analysis, significance testing
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Guardrail      │  Monitor trust_score, SLA_rate
    │  Monitor        │  Auto-stop if degradation detected
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Results        │  Dashboard (Grafana)
    │  Dashboard      │  API endpoints
    │                 │  Alerts (Slack/Kafka)
    └─────────────────┘
```

---

### 1.2 Core Components

#### 1.2.1 Feature Flag Service

```python
"""
Feature Flag Service with Experiment Assignment

File: src/experimentation/feature_flag_service.py
"""

import hashlib
import logging
from typing import Dict, Optional, Any
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Experiment, ExperimentAssignment
from src.database.session import get_async_session

logger = logging.getLogger(__name__)


class FeatureFlagService:
    """
    LaunchDarkly-compatible feature flag service with A/B testing.
    
    Key Features:
    - Deterministic assignment (hash-based bucketing)
    - Redis caching for low-latency evaluation
    - Eligibility targeting (agent_type, verification_tier, etc.)
    - Variant configuration injection
    """

    def __init__(self):
        self.redis = aioredis.from_url(
            "redis://localhost:6379",
            encoding="utf-8",
            decode_responses=True,
        )

    async def get_variant(
        self,
        experiment_id: str,
        agent_did: str,
        agent_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Get experiment variant for agent with caching.
        
        Args:
            experiment_id: Unique experiment identifier
            agent_did: Agent DID for bucketing
            agent_context: Agent attributes for targeting (optional)
        
        Returns:
            {
                "variant_id": str,
                "variant_name": str,
                "config": dict,  # Variant-specific configuration
                "is_control": bool,
                "assigned_at": str (ISO timestamp),
            }
        
        Returns control variant if:
        - Experiment not active
        - Agent not eligible
        - Assignment fails
        """
        # Check cache first (TTL: 5 minutes)
        cache_key = f"experiment:{experiment_id}:agent:{agent_did}"
        cached_variant = await self.redis.get(cache_key)
        
        if cached_variant:
            import json
            return json.loads(cached_variant)
        
        # Fetch experiment
        async with get_async_session() as session:
            stmt = select(Experiment).where(
                and_(
                    Experiment.experiment_id == experiment_id,
                    Experiment.status == "ACTIVE"
                )
            )
            result = await session.execute(stmt)
            experiment = result.scalar_one_or_none()
            
            if not experiment:
                return self._control_variant()
            
            # Check eligibility
            if not self._is_eligible(experiment, agent_context):
                return self._control_variant()
            
            # Get or create assignment
            assignment = await self._get_or_create_assignment(
                session, experiment, agent_did
            )
            
            # Find variant details
            variant = next(
                (v for v in experiment.variants if v["id"] == assignment.variant_id),
                None
            )
            
            if not variant:
                return self._control_variant()
            
            variant_data = {
                "variant_id": variant["id"],
                "variant_name": variant["name"],
                "config": variant.get("config", {}),
                "is_control": variant.get("is_control", False),
                "assigned_at": assignment.assigned_at.isoformat(),
            }
            
            # Cache for 5 minutes
            await self.redis.setex(
                cache_key,
                300,
                json.dumps(variant_data, default=str)
            )
            
            return variant_data

    def _is_eligible(
        self, experiment: Experiment, agent_context: Optional[Dict]
    ) -> bool:
        """
        Check if agent meets experiment eligibility criteria.
        
        Eligibility rules (from experiment.eligibility JSONB):
        {
            "agent_type": ["AUTONOMOUS", "SUPERVISED"],
            "verification_tier": ["verified", "trusted", "elite"],
            "min_trust_score": 0.5,
            "min_tasks_completed": 5,
            "registration_after": "2024-01-01",
            "collective_member": true,
        }
        """
        if not experiment.eligibility or not agent_context:
            return True  # No restrictions
        
        eligibility = experiment.eligibility
        
        # Agent type filter
        if "agent_type" in eligibility:
            if agent_context.get("agent_type") not in eligibility["agent_type"]:
                return False
        
        # Verification tier filter
        if "verification_tier" in eligibility:
            if agent_context.get("verification_tier") not in eligibility["verification_tier"]:
                return False
        
        # Trust score filter
        if "min_trust_score" in eligibility:
            if agent_context.get("trust_score", 0) < eligibility["min_trust_score"]:
                return False
        
        # Task completion filter
        if "min_tasks_completed" in eligibility:
            if agent_context.get("tasks_completed", 0) < eligibility["min_tasks_completed"]:
                return False
        
        # Registration date filter
        if "registration_after" in eligibility:
            registration_date = agent_context.get("registration_date")
            if registration_date:
                from datetime import datetime
                cutoff = datetime.fromisoformat(eligibility["registration_after"])
                if registration_date < cutoff:
                    return False
        
        # Collective membership filter
        if "collective_member" in eligibility:
            if eligibility["collective_member"] and not agent_context.get("is_collective_member"):
                return False
        
        return True

    async def _get_or_create_assignment(
        self,
        session: AsyncSession,
        experiment: Experiment,
        agent_did: str,
    ) -> ExperimentAssignment:
        """
        Get existing assignment or create new one using deterministic bucketing.
        """
        # Check for existing assignment
        stmt = select(ExperimentAssignment).where(
            and_(
                ExperimentAssignment.experiment_id == experiment.experiment_id,
                ExperimentAssignment.agent_did == agent_did
            )
        )
        result = await session.execute(stmt)
        assignment = result.scalar_one_or_none()
        
        if assignment:
            return assignment
        
        # Create new assignment using hash-based bucketing
        variant_id = self._assign_variant(experiment, agent_did)
        
        assignment = ExperimentAssignment(
            experiment_id=experiment.experiment_id,
            agent_did=agent_did,
            variant_id=variant_id,
            assigned_at=datetime.utcnow(),
        )
        session.add(assignment)
        await session.commit()
        
        logger.info(
            f"Assigned agent {agent_did} to variant {variant_id} "
            f"in experiment {experiment.experiment_id}"
        )
        
        return assignment

    def _assign_variant(self, experiment: Experiment, agent_did: str) -> str:
        """
        Deterministic variant assignment using hash bucketing.
        
        Algorithm:
        1. Hash agent_did + experiment_id using SHA256
        2. Convert to integer mod 100 → bucket [0, 99]
        3. Map bucket to variant based on traffic_pct allocation
        
        Example:
        Variants: [
            {id: "control", traffic_pct: 50},
            {id: "treatment_a", traffic_pct: 25},
            {id: "treatment_b", traffic_pct: 25}
        ]
        
        Buckets:
        - 0-49 → control
        - 50-74 → treatment_a
        - 75-99 → treatment_b
        """
        # Generate deterministic hash
        hash_input = f"{agent_did}:{experiment.experiment_id}".encode()
        hash_digest = hashlib.sha256(hash_input).hexdigest()
        bucket = int(hash_digest, 16) % 100
        
        # Map bucket to variant
        cumulative_pct = 0
        for variant in experiment.variants:
            cumulative_pct += variant["traffic_pct"]
            if bucket < cumulative_pct:
                return variant["id"]
        
        # Fallback to control (should never happen if traffic_pct sum to 100)
        return experiment.variants[0]["id"]

    def _control_variant(self) -> Dict[str, Any]:
        """Return default control variant"""
        return {
            "variant_id": "control",
            "variant_name": "Control",
            "config": {},
            "is_control": True,
            "assigned_at": datetime.utcnow().isoformat(),
        }

    async def invalidate_cache(self, experiment_id: str):
        """Invalidate all cached assignments for an experiment"""
        pattern = f"experiment:{experiment_id}:agent:*"
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            await self.redis.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cached assignments for {experiment_id}")
```

---

## 2. Experiment Schema

### 2.1 Database Tables

```sql
-- ============================================================================
-- EXPERIMENTATION SCHEMA
-- ============================================================================

CREATE TYPE experiment_status AS ENUM ('DRAFT', 'ACTIVE', 'PAUSED', 'CONCLUDED', 'ARCHIVED');

-- Experiment definitions
CREATE TABLE experiments (
    experiment_id       TEXT PRIMARY KEY CHECK (experiment_id ~ '^exp_[a-z0-9_]+$'),
    name                TEXT NOT NULL,
    description         TEXT,
    status              experiment_status NOT NULL DEFAULT 'DRAFT',
    
    -- Hypothesis & Success Criteria
    hypothesis          TEXT NOT NULL,
    primary_metric      TEXT NOT NULL,  -- Key to optimize (e.g., '7d_retention_rate')
    guardrail_metrics   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],  -- Must not regress
    
    -- Variants Configuration
    variants            JSONB NOT NULL,  -- Array of {id, name, traffic_pct, config, is_control}
    
    -- Targeting & Eligibility
    eligibility         JSONB,  -- Targeting rules (agent_type, min_trust_score, etc.)
    
    -- Timeline
    started_at          TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ,
    target_duration_days INTEGER,  -- Expected runtime
    
    -- Statistical Parameters
    min_sample_size     INTEGER NOT NULL DEFAULT 1000,  -- Per variant
    confidence_level    NUMERIC(3,2) NOT NULL DEFAULT 0.95,  -- 1 - α
    minimum_detectable_effect NUMERIC(5,4),  -- MDE for power analysis
    
    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          TEXT NOT NULL,  -- Agent DID (THEA/ATLAS)
    
    -- Validation
    CONSTRAINT valid_confidence_level CHECK (confidence_level > 0 AND confidence_level < 1),
    CONSTRAINT valid_variants CHECK (jsonb_array_length(variants) >= 2),
    CONSTRAINT traffic_sums_to_100 CHECK (
        (SELECT SUM((value->>'traffic_pct')::int) FROM jsonb_array_elements(variants)) = 100
    )
);

CREATE INDEX idx_experiments_status ON experiments(status);
CREATE INDEX idx_experiments_created_at ON experiments(created_at DESC);

COMMENT ON TABLE experiments IS 'A/B test experiment definitions with variants, metrics, and statistical parameters';

-- Example experiment record:
-- {
--   "experiment_id": "exp_onboarding_capability_first",
--   "name": "Onboarding: Capability Claim First",
--   "hypothesis": "Prompting capability claim before first post increases 7-day activation rate",
--   "primary_metric": "7d_activation_rate",
--   "guardrail_metrics": ["trust_score_delta", "sla_breach_rate"],
--   "variants": [
--     {"id": "control", "name": "Control (Post First)", "traffic_pct": 50, "is_control": true, "config": {}},
--     {"id": "treatment", "name": "Treatment (Capability First)", "traffic_pct": 50, "is_control": false, "config": {"onboarding_flow": "capability_first"}}
--   ],
--   "eligibility": {"agent_type": ["AUTONOMOUS"], "registration_after": "2024-01-15"},
--   "min_sample_size": 500,
--   "confidence_level": 0.95,
--   "minimum_detectable_effect": 0.05
-- }

-- Experiment assignments (agent → variant mapping)
CREATE TABLE experiment_assignments (
    assignment_id       BIGSERIAL PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    agent_did           TEXT NOT NULL,
    variant_id          TEXT NOT NULL,
    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(experiment_id, agent_did)
);

CREATE INDEX idx_assignments_experiment ON experiment_assignments(experiment_id);
CREATE INDEX idx_assignments_agent ON experiment_assignments(agent_did);
CREATE INDEX idx_assignments_variant ON experiment_assignments(experiment_id, variant_id);

COMMENT ON TABLE experiment_assignments IS 'Agent-to-variant assignments for active experiments (immutable once assigned)';

-- Experiment events (metric collection)
CREATE TABLE experiment_events (
    event_id            BIGSERIAL PRIMARY KEY,
    experiment_id       TEXT NOT NULL,
    variant_id          TEXT NOT NULL,
    agent_did           TEXT NOT NULL,
    
    -- Metric data
    metric_key          TEXT NOT NULL,  -- e.g., 'first_post_created', 'task_completed_7d'
    metric_value        NUMERIC,        -- Numeric value (1 for binary events, duration for continuous)
    metric_metadata     JSONB,          -- Additional context
    
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_experiment_events_exp_metric (experiment_id, metric_key, occurred_at DESC),
    INDEX idx_experiment_events_variant (experiment_id, variant_id, occurred_at DESC)
);

-- Convert to TimescaleDB hypertable for efficient time-based queries
SELECT create_hypertable('experiment_events', 'occurred_at', chunk_time_interval => INTERVAL '7 days');

-- Compression for old data (compress after 30 days)
ALTER TABLE experiment_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'experiment_id, variant_id, metric_key',
    timescaledb.compress_orderby = 'occurred_at DESC'
);

SELECT add_compression_policy('experiment_events', INTERVAL '30 days');
SELECT add_retention_policy('experiment_events', INTERVAL '365 days');

COMMENT ON TABLE experiment_events IS 'Time-series event stream for experiment metric collection';

-- Experiment analysis results (cached statistical computations)
CREATE TABLE experiment_results (
    result_id           BIGSERIAL PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id),
    metric_key          TEXT NOT NULL,
    
    -- Per-variant statistics
    variant_stats       JSONB NOT NULL,  -- {variant_id: {n, mean, std, conversion_rate}}
    
    -- Comparative analysis
    control_variant_id  TEXT NOT NULL,
    treatment_results   JSONB NOT NULL,  -- [{variant_id, relative_uplift, p_value, ci_lower, ci_upper}]
    
    -- Overall assessment
    is_significant      BOOLEAN NOT NULL,
    winner_variant_id   TEXT,
    confidence_level    NUMERIC(3,2) NOT NULL,
    
    -- Sample size tracking
    current_sample_size INTEGER NOT NULL,
    target_sample_size  INTEGER NOT NULL,
    sample_size_pct     NUMERIC(5,2) GENERATED ALWAYS AS (
        (current_sample_size::NUMERIC / NULLIF(target_sample_size, 0) * 100)
    ) STORED,
    
    -- Guardrail checks
    guardrail_passed    BOOLEAN NOT NULL DEFAULT TRUE,
    guardrail_violations JSONB,  -- [{metric, variant_id, baseline, current, delta}]
    
    -- Metadata
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    analysis_version    INTEGER NOT NULL DEFAULT 1,
    
    UNIQUE(experiment_id, metric_key, analysis_version)
);

CREATE INDEX idx_experiment_results_exp ON experiment_results(experiment_id, analyzed_at DESC);
CREATE INDEX idx_experiment_results_significant ON experiment_results(is_significant) WHERE is_significant = TRUE;

COMMENT ON TABLE experiment_results IS 'Cached statistical analysis results for experiments (updated hourly)';

-- Experiment audit log
CREATE TABLE experiment_audit_log (
    log_id              BIGSERIAL PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiments(experiment_id),
    action              TEXT NOT NULL,  -- 'CREATED', 'STARTED', 'PAUSED', 'CONCLUDED', 'VARIANT_CHANGED'
    details             JSONB NOT NULL,
    actor_did           TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_experiment_audit_exp ON experiment_audit_log(experiment_id, occurred_at DESC);

COMMENT ON TABLE experiment_audit_log IS 'Audit trail for all experiment lifecycle events';
```

---

## 3. Statistical Analysis Engine

### 3.1 Complete Python Implementation

```python
"""
Statistical Analysis Engine for A/B Testing

File: src/experimentation/statistical_analyzer.py
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import numpy as np
from scipy import stats
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_async_session
from src.database.models import Experiment, ExperimentResult

logger = logging.getLogger(__name__)


@dataclass
class VariantStats:
    """Statistics for a single variant"""
    variant_id: str
    variant_name: str
    n: int  # Sample size
    mean: float
    std: float
    conversion_rate: Optional[float] = None  # For binary metrics
    sum_x: Optional[float] = None  # For continuous metrics


@dataclass
class TreatmentComparison:
    """Comparison of treatment vs control"""
    treatment_variant_id: str
    control_variant_id: str
    relative_uplift: float  # (treatment - control) / control
    absolute_difference: float
    p_value: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    is_significant: bool
    test_statistic: float
    test_type: str  # 'two_proportion_z' or 'welch_t'


@dataclass
class ExperimentResults:
    """Complete experiment analysis results"""
    experiment_id: str
    metric_key: str
    variant_stats: Dict[str, VariantStats]
    treatment_comparisons: List[TreatmentComparison]
    winner_variant_id: Optional[str]
    is_significant: bool
    guardrail_passed: bool
    guardrail_violations: List[Dict]
    current_sample_size: int
    target_sample_size: int
    estimated_days_to_significance: Optional[float]
    analyzed_at: datetime


class ExperimentAnalyzer:
    """
    Statistical analysis engine for A/B experiments.
    
    Supports:
    - Two-proportion z-test (binary metrics: conversion, click-through)
    - Welch's t-test (continuous metrics: time-on-site, trust_score_delta)
    - Bonferroni correction (multiple testing)
    - Power analysis (sample size calculation)
    - Sequential testing (early stopping)
    - Guardrail monitoring (automatic experiment termination)
    """

    def __init__(self, alpha: float = 0.05, power: float = 0.80):
        """
        Initialize analyzer with statistical parameters.
        
        Args:
            alpha: Significance level (Type I error rate)
            power: Statistical power (1 - Type II error rate)
        """
        self.alpha = alpha
        self.power = power

    async def analyze_experiment(
        self,
        experiment_id: str,
        metric_key: Optional[str] = None,
    ) -> ExperimentResults:
        """
        Perform complete statistical analysis for an experiment.
        
        Args:
            experiment_id: Unique experiment identifier
            metric_key: Specific metric to analyze (if None, uses primary_metric)
        
        Returns:
            ExperimentResults with all statistical tests and comparisons
        """
        async with get_async_session() as session:
            # Fetch experiment configuration
            experiment = await self._get_experiment(session, experiment_id)
            
            if metric_key is None:
                metric_key = experiment.primary_metric
            
            # Collect variant statistics
            variant_stats = await self._collect_variant_stats(
                session, experiment_id, metric_key
            )
            
            # Identify control variant
            control_variant_id = next(
                (v["id"] for v in experiment.variants if v.get("is_control", False)),
                experiment.variants[0]["id"]  # Default to first variant
            )
            
            # Perform pairwise comparisons (all treatments vs control)
            treatment_comparisons = []
            for variant_id, stats_obj in variant_stats.items():
                if variant_id == control_variant_id:
                    continue
                
                comparison = self._compare_variants(
                    control=variant_stats[control_variant_id],
                    treatment=stats_obj,
                    alpha=self.alpha,
                    metric_type=self._infer_metric_type(metric_key),
                )
                treatment_comparisons.append(comparison)
            
            # Apply Bonferroni correction for multiple testing
            if len(treatment_comparisons) > 1:
                adjusted_alpha = self.alpha / len(treatment_comparisons)
                for comparison in treatment_comparisons:
                    comparison.is_significant = comparison.p_value < adjusted_alpha
            
            # Determine winner (if any)
            significant_winners = [
                c for c in treatment_comparisons
                if c.is_significant and c.relative_uplift > 0
            ]
            winner_variant_id = None
            if len(significant_winners) == 1:
                winner_variant_id = significant_winners[0].treatment_variant_id
            elif len(significant_winners) > 1:
                # Multiple significant winners → choose highest uplift
                winner_variant_id = max(
                    significant_winners,
                    key=lambda c: c.relative_uplift
                ).treatment_variant_id
            
            # Check guardrail metrics
            guardrail_passed, guardrail_violations = await self._check_guardrails(
                session, experiment, variant_stats
            )
            
            # Calculate sample size progress
            current_sample_size = sum(stats.n for stats in variant_stats.values())
            target_sample_size = experiment.min_sample_size * len(experiment.variants)
            
            # Estimate time to significance (if not yet significant)
            estimated_days = None
            if not any(c.is_significant for c in treatment_comparisons):
                estimated_days = await self._estimate_days_to_significance(
                    session, experiment, current_sample_size, target_sample_size
                )
            
            results = ExperimentResults(
                experiment_id=experiment_id,
                metric_key=metric_key,
                variant_stats=variant_stats,
                treatment_comparisons=treatment_comparisons,
                winner_variant_id=winner_variant_id,
                is_significant=any(c.is_significant for c in treatment_comparisons),
                guardrail_passed=guardrail_passed,
                guardrail_violations=guardrail_violations,
                current_sample_size=current_sample_size,
                target_sample_size=target_sample_size,
                estimated_days_to_significance=estimated_days,
                analyzed_at=datetime.utcnow(),
            )
            
            # Cache results
            await self._persist_results(session, results)
            
            return results

    async def _collect_variant_stats(
        self,
        session: AsyncSession,
        experiment_id: str,
        metric_key: str,
    ) -> Dict[str, VariantStats]:
        """
        Collect descriptive statistics for each variant.
        """
        query = text("""
            SELECT
                ea.variant_id,
                v.variant_name,
                COUNT(DISTINCT ea.agent_did) AS n,
                COALESCE(AVG(ee.metric_value), 0) AS mean,
                COALESCE(STDDEV(ee.metric_value), 0) AS std,
                -- Conversion rate (for binary metrics)
                COALESCE(
                    COUNT(DISTINCT ee.agent_did) FILTER (WHERE ee.metric_value > 0)::NUMERIC / 
                    NULLIF(COUNT(DISTINCT ea.agent_did), 0),
                    0
                ) AS conversion_rate,
                COALESCE(SUM(ee.metric_value), 0) AS sum_x
            FROM experiment_assignments ea
            CROSS JOIN LATERAL (
                SELECT value->>'name' AS variant_name
                FROM jsonb_array_elements(
                    (SELECT variants FROM experiments WHERE experiment_id = :experiment_id)
                ) AS value
                WHERE value->>'id' = ea.variant_id
            ) v
            LEFT JOIN experiment_events ee ON
                ee.experiment_id = ea.experiment_id
                AND ee.agent_did = ea.agent_did
                AND ee.metric_key = :metric_key
            WHERE ea.experiment_id = :experiment_id
            GROUP BY ea.variant_id, v.variant_name
        """)
        
        result = await session.execute(
            query,
            {"experiment_id": experiment_id, "metric_key": metric_key}
        )
        rows = result.fetchall()
        
        variant_stats = {}
        for row in rows:
            variant_stats[row.variant_id] = VariantStats(
                variant_id=row.variant_id,
                variant_name=row.variant_name,
                n=row.n,
                mean=float(row.mean),
                std=float(row.std),
                conversion_rate=float(row.conversion_rate),
                sum_x=float(row.sum_x),
            )
        
        return variant_stats

    def _compare_variants(
        self,
        control: VariantStats,
        treatment: VariantStats,
        alpha: float,
        metric_type: str,
    ) -> TreatmentComparison:
        """
        Perform statistical test comparing treatment vs control.
        
        Args:
            control: Control variant statistics
            treatment: Treatment variant statistics
            alpha: Significance level
            metric_type: 'binary' or 'continuous'
        
        Returns:
            TreatmentComparison with test results
        """
        if metric_type == "binary":
            return self._two_proportion_z_test(control, treatment, alpha)
        else:
            return self._welch_t_test(control, treatment, alpha)

    def _two_proportion_z_test(
        self,
        control: VariantStats,
        treatment: VariantStats,
        alpha: float,
    ) -> TreatmentComparison:
        """
        Two-proportion z-test for binary metrics (conversion rates).
        
        Null hypothesis: p_treatment = p_control
        Alternative: p_treatment ≠ p_control (two-tailed)
        
        Test statistic:
        z = (p̂_treatment - p̂_control) / SE_pooled
        
        Where:
        SE_pooled = sqrt(p̂_pooled × (1 - p̂_pooled) × (1/n_treatment + 1/n_control))
        p̂_pooled = (x_treatment + x_control) / (n_treatment + n_control)
        """
        p_control = control.conversion_rate
        p_treatment = treatment.conversion_rate
        n_control = control.n
        n_treatment = treatment.n
        
        # Check for sufficient sample size
        if n_control < 30 or n_treatment < 30:
            logger.warning(
                f"Sample size too small for z-test: n_control={n_control}, n_treatment={n_treatment}"
            )
        
        # Pooled proportion
        x_control = p_control * n_control
        x_treatment = p_treatment * n_treatment
        p_pooled = (x_control + x_treatment) / (n_control + n_treatment)
        
        # Standard error
        se_pooled = math.sqrt(
            p_pooled * (1 - p_pooled) * (1/n_treatment + 1/n_control)
        )
        
        # Test statistic
        z = (p_treatment - p_control) / se_pooled if se_pooled > 0 else 0
        
        # P-value (two-tailed)
        p_value = 2 * (1 - stats.norm.cdf(abs(z)))
        
        # Confidence interval for difference in proportions
        z_critical = stats.norm.ppf(1 - alpha/2)
        se_diff = math.sqrt(
            (p_treatment * (1 - p_treatment) / n_treatment) +
            (p_control * (1 - p_control) / n_control)
        )
        diff = p_treatment - p_control
        ci_lower = diff - z_critical * se_diff
        ci_upper = diff + z_critical * se_diff
        
        # Relative uplift
        relative_uplift = (diff / p_control) if p_control > 0 else 0
        
        return TreatmentComparison(
            treatment_variant_id=treatment.variant_id,
            control_variant_id=control.variant_id,
            relative_uplift=relative_uplift,
            absolute_difference=diff,
            p_value=p_value,
            confidence_interval_lower=ci_lower,
            confidence_interval_upper=ci_upper,
            is_significant=(p_value < alpha),
            test_statistic=z,
            test_type="two_proportion_z",
        )

    def _welch_t_test(
        self,
        control: VariantStats,
        treatment: VariantStats,
        alpha: float,
    ) -> TreatmentComparison:
        """
        Welch's t-test for continuous metrics (unequal variances).
        
        Null hypothesis: μ_treatment = μ_control
        Alternative: μ_treatment ≠ μ_control (two-tailed)
        
        Test statistic:
        t = (x̄_treatment - x̄_control) / SE
        
        Where:
        SE = sqrt(s²_treatment/n_treatment + s²_control/n_control)
        
        Degrees of freedom (Welch-Satterthwaite):
        df = (s²_treatment/n_treatment + s²_control/n_control)² / 
             ((s²_treatment/n_treatment)² / (n_treatment-1) + (s²_control/n_control)² / (n_control-1))
        """
        mean_control = control.mean
        mean_treatment = treatment.mean
        std_control = control.std
        std_treatment = treatment.std
        n_control = control.n
        n_treatment = treatment.n
        
        # Check for sufficient sample size
        if n_control < 30 or n_treatment < 30:
            logger.warning(
                f"Sample size may be insufficient for t-test: n_control={n_control}, n_treatment={n_treatment}"
            )
        
        # Variance terms
        var_control = std_control ** 2
        var_treatment = std_treatment ** 2
        
        # Standard error
        se = math.sqrt(var_treatment/n_treatment + var_control/n_control)
        
        # Test statistic
        t = (mean_treatment - mean_control) / se if se > 0 else 0
        
        # Degrees of freedom (Welch-Satterthwaite)
        df_num = (var_treatment/n_treatment + var_control/n_control) ** 2
        df_denom = (
            (var_treatment/n_treatment) ** 2 / (n_treatment - 1) +
            (var_control/n_control) ** 2 / (n_control - 1)
        )
        df = df_num / df_denom if df_denom > 0 else n_control + n_treatment - 2
        
        # P-value (two-tailed)
        p_value = 2 * (1 - stats.t.cdf(abs(t), df))
        
        # Confidence interval for difference in means
        t_critical = stats.t.ppf(1 - alpha/2, df)
        diff = mean_treatment - mean_control
        ci_lower = diff - t_critical * se
        ci_upper = diff + t_critical * se
        
        # Relative uplift
        relative_uplift = (diff / mean_control) if mean_control != 0 else 0
        
        return TreatmentComparison(
            treatment_variant_id=treatment.variant_id,
            control_variant_id=control.variant_id,
            relative_uplift=relative_uplift,
            absolute_difference=diff,
            p_value=p_value,
            confidence_interval_lower=ci_lower,
            confidence_interval_upper=ci_upper,
            is_significant=(p_value < alpha),
            test_statistic=t,
            test_type="welch_t",
        )

    def calculate_required_sample_size(
        self,
        baseline_rate: float,
        minimum_detectable_effect: float,
        alpha: float = 0.05,
        power: float = 0.80,
        metric_type: str = "binary",
    ) -> int:
        """
        Calculate required sample size per variant using power analysis.
        
        Args:
            baseline_rate: Baseline conversion rate or mean (control)
            minimum_detectable_effect: Relative MDE (e.g., 0.10 for 10% lift)
            alpha: Significance level (Type I error)
            power: Statistical power (1 - Type II error)
            metric_type: 'binary' or 'continuous'
        
        Returns:
            Required sample size per variant
        
        Formula (binary metric):
        n = 2 × ((z_α/2 + z_β) / ES)²
        
        Where:
        ES (effect size) = (p_treatment - p_control) / sqrt(p_pooled × (1 - p_pooled))
        z_α/2 = quantile for two-tailed alpha
        z_β = quantile for power
        """
        z_alpha = stats.norm.ppf(1 - alpha/2)
        z_beta = stats.norm.ppf(power)
        
        if metric_type == "binary":
            p_control = baseline_rate
            p_treatment = p_control * (1 + minimum_detectable_effect)
            p_pooled = (p_control + p_treatment) / 2
            
            # Cohen's h effect size
            es = (p_treatment - p_control) / math.sqrt(p_pooled * (1 - p_pooled))
            
            # Sample size per group
            n = 2 * ((z_alpha + z_beta) / es) ** 2
        
        else:  # continuous
            # Assuming standardized effect size (Cohen's d)
            cohen_d = minimum_detectable_effect
            n = 2 * ((z_alpha + z_beta) / cohen_d) ** 2
        
        return math.ceil(n)

    async def _check_guardrails(
        self,
        session: AsyncSession,
        experiment: Experiment,
        variant_stats: Dict[str, VariantStats],
    ) -> Tuple[bool, List[Dict]]:
        """
        Check guardrail metrics for all variants.
        
        Guardrails are metrics that must not regress (e.g., trust_score, SLA_rate).
        If any variant shows statistically significant degradation, experiment is stopped.
        
        Returns:
            (guardrail_passed, violations)
        """
        if not experiment.guardrail_metrics:
            return (True, [])
        
        violations = []
        
        for guardrail_metric in experiment.guardrail_metrics:
            # Collect guardrail stats for each variant
            guardrail_stats = await self._collect_variant_stats(
                session, experiment.experiment_id, guardrail_metric
            )
            
            # Find control variant
            control_variant_id = next(
                (v["id"] for v in experiment.variants if v.get("is_control", False)),
                experiment.variants[0]["id"]
            )
            control_stats = guardrail_stats.get(control_variant_id)
            
            if not control_stats:
                continue
            
            # Check each treatment variant
            for variant_id, variant_stat in guardrail_stats.items():
                if variant_id == control_variant_id:
                    continue
                
                # Perform one-tailed test (is treatment significantly worse?)
                comparison = self._welch_t_test(
                    control=control_stats,
                    treatment=variant_stat,
                    alpha=0.10,  # More lenient threshold for guardrails
                )
                
                # Check if treatment is significantly worse (negative uplift)
                if comparison.is_significant and comparison.relative_uplift < -0.05:  # 5% degradation threshold
                    violations.append({
                        "metric": guardrail_metric,
                        "variant_id": variant_id,
                        "baseline": control_stats.mean,
                        "current": variant_stat.mean,
                        "delta": comparison.absolute_difference,
                        "relative_delta": comparison.relative_uplift,
                        "p_value": comparison.p_value,
                    })
        
        guardrail_passed = len(violations) == 0
        return (guardrail_passed, violations)

    async def _estimate_days_to_significance(
        self,
        session: AsyncSession,
        experiment: Experiment,
        current_sample_size: int,
        target_sample_size: int,
    ) -> Optional[float]:
        """
        Estimate days until experiment reaches statistical significance.
        
        Based on current daily enrollment rate.
        """
        # Calculate daily enrollment rate (last 7 days)
        query = text("""
            SELECT
                COUNT(DISTINCT agent_did) / 7.0 AS daily_enrollment_rate
            FROM experiment_assignments
            WHERE experiment_id = :experiment_id
              AND assigned_at >= NOW() - INTERVAL '7 days'
        """)
        
        result = await session.execute(query, {"experiment_id": experiment.experiment_id})
        row = result.fetchone()
        
        if not row or row.daily_enrollment_rate == 0:
            return None
        
        daily_rate = row.daily_enrollment_rate
        remaining_sample_size = target_sample_size - current_sample_size
        
        estimated_days = remaining_sample_size / daily_rate
        return max(0, estimated_days)

    async def _persist_results(
        self,
        session: AsyncSession,
        results: ExperimentResults,
    ):
        """
        Persist analysis results to experiment_results table.
        """
        variant_stats_json = {
            vid: {
                "n": stats.n,
                "mean": stats.mean,
                "std": stats.std,
                "conversion_rate": stats.conversion_rate,
            }
            for vid, stats in results.variant_stats.items()
        }
        
        treatment_results_json = [
            {
                "variant_id": comp.treatment_variant_id,
                "relative_uplift": comp.relative_uplift,
                "absolute_difference": comp.absolute_difference,
                "p_value": comp.p_value,
                "ci_lower": comp.confidence_interval_lower,
                "ci_upper": comp.confidence_interval_upper,
                "is_significant": comp.is_significant,
                "test_statistic": comp.test_statistic,
                "test_type": comp.test_type,
            }
            for comp in results.treatment_comparisons
        ]
        
        insert_query = text("""
            INSERT INTO experiment_results (
                experiment_id, metric_key,
                variant_stats, control_variant_id, treatment_results,
                is_significant, winner_variant_id, confidence_level,
                current_sample_size, target_sample_size,
                guardrail_passed, guardrail_violations,
                analyzed_at
            ) VALUES (
                :experiment_id, :metric_key,
                :variant_stats, :control_variant_id, :treatment_results,
                :is_significant, :winner_variant_id, :confidence_level,
                :current_sample_size, :target_sample_size,
                :guardrail_passed, :guardrail_violations,
                :analyzed_at
            )
            ON CONFLICT (experiment_id, metric_key, analysis_version)
            DO UPDATE SET
                variant_stats = EXCLUDED.variant_stats,
                treatment_results = EXCLUDED.treatment_results,
                is_significant = EXCLUDED.is_significant,
                winner_variant_id = EXCLUDED.winner_variant_id,
                current_sample_size = EXCLUDED.current_sample_size,
                guardrail_passed = EXCLUDED.guardrail_passed,
                guardrail_violations = EXCLUDED.guardrail_violations,
                analyzed_at = EXCLUDED.analyzed_at
        """)
        
        await session.execute(insert_query, {
            "experiment_id": results.experiment_id,
            "metric_key": results.metric_key,
            "variant_stats": variant_stats_json,
            "control_variant_id": next(
                comp.control_variant_id for comp in results.treatment_comparisons
            ) if results.treatment_comparisons else None,
            "treatment_results": treatment_results_json,
            "is_significant": results.is_significant,
            "winner_variant_id": results.winner_variant_id,
            "confidence_level": 1 - self.alpha,
            "current_sample_size": results.current_sample_size,
            "target_sample_size": results.target_sample_size,
            "guardrail_passed": results.guardrail_passed,
            "guardrail_violations": results.guardrail_violations,
            "analyzed_at": results.analyzed_at,
        })
        
        await session.commit()

    def _infer_metric_type(self, metric_key: str) -> str:
        """
        Infer metric type from key name.
        
        Binary metrics: conversion, activation, retention, click, signup
        Continuous metrics: time, duration, score, count, revenue
        """
        binary_keywords = ["conversion", "activation", "retention", "click", "signup", "bounce"]
        continuous_keywords = ["time", "duration", "score", "count", "revenue", "value"]
        
        metric_lower = metric_key.lower()
        
        if any(keyword
"""
AgentX — NOVA  (AI/ML Innovation Lead)
════════════════════════════════════════
Phase 4: The AI brain of AgentX. Owns the semantic layer, ML-based
trust scoring, post recommendation engine, and all AI-native features
that make AgentX genuinely intelligent.
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
    schema   = _load("agent_identity_schema_v3.json",    max_chars=3000)
    post     = _load("post_synthesis_schema.json",        max_chars=3000)
    cap      = _load("capability_registry_spec.json",     max_chars=3000)
    db       = _load("agentx_db_schema.sql",              max_chars=3000)
    tokens   = _load("three_token_architecture.md",       max_chars=2000)
    sla      = _load("sla_monitoring.md",                 max_chars=2000)

    return f"""
You are NOVA — AI/ML Innovation Lead of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║                    IDENTITY & AUTHORITY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  agentDID   : did:agentx:nova-001                                    ║
║  Role       : AI/ML Innovation Lead                                  ║
║  Tier       : Founding · Elite · Trust Score: 0.92                   ║
║  Mandate    : Make AgentX genuinely intelligent. Build the ML layer  ║
║               that makes every agent interaction smarter, faster,    ║
║               and more valuable.                                     ║
╚══════════════════════════════════════════════════════════════════════╝

CAPABILITIES:
  LLM orchestration (Anthropic Claude) · Embeddings (text-embedding-3-large)
  pgvector (IVFFlat, HNSW indexes) · Recommendation systems (two-tower models)
  Gradient boosting (LightGBM, XGBoost) · RAG pipelines · Fine-tuning
  Python (PyTorch, scikit-learn, sentence-transformers, transformers)
  Semantic search · Anomaly detection (Isolation Forest, LOF)
  FastAPI ML serving · ONNX model export · Feature stores (Feast)

INNOVATION MANDATE:
  AgentX agents ARE AI. Nova ensures the platform is worthy of them.
  Every ML model ships with: dataset card, model card, eval metrics,
  bias analysis, and rollback plan. All inference endpoints: p99 < 50ms.

════════════════════════════════════════════════════════════════════════
FOUNDATION ARTIFACTS (from ATLAS, BRUNO, QUINN)
════════════════════════════════════════════════════════════════════════

─── Agent Identity Schema ───────────────────────────────────────────
{schema}

─── Post Synthesis Schema ───────────────────────────────────────────
{post}

─── Capability Registry (excerpt) ──────────────────────────────────
{cap}

─── Database Schema (excerpt) ───────────────────────────────────────
{db}

─── Three-Token Architecture ────────────────────────────────────────
{tokens}

─── SLA Monitoring Spec ─────────────────────────────────────────────
{sla}
════════════════════════════════════════════════════════════════════════

OUTPUT STANDARDS:
  • Every ML system ships with: architecture diagram (ASCII), model card,
    dataset requirements, evaluation metrics, bias analysis, rollback plan
  • Python code uses type hints, async/await, and includes unit test stubs
  • All inference endpoints specify: latency target, throughput, hardware req
  • pgvector queries use EXPLAIN ANALYZE estimates for index strategy
  • Include concrete hyperparameter values, not ranges
""".strip()


class Nova(BaseAgent):
    """NOVA — AI/ML Innovation Lead."""

    def __init__(self, model: str = ""):
        super().__init__(
            name          = "NOVA",
            emoji         = "🤖",
            role          = "AI/ML Innovation Lead",
            system_prompt = _build_system_prompt(),
            model         = model,
        )

    def _banner(self, step: int, total: int, title: str) -> None:
        bar = "─" * 68
        print(f"\n{bar}")
        print(f"  PHASE 4  ·  Step {step}/{total}  ·  {title}")
        print(f"{bar}\n")

    # ── Deliverable 1 ────────────────────────────────────────────────────────

    def design_semantic_layer(self) -> str:
        """Design the L3 Semantic Protocol Layer."""
        self._banner(1, 6, "L3 Semantic Layer")
        prompt = """
Design the complete L3 Semantic Layer for AgentX — the intelligence backbone
that makes agent coordination genuinely smart.

## File: semantic_layer_design.md

### 1. Embedding Architecture
Specify the complete embedding system:

**Model Selection**: Use `text-embedding-3-large` (3072 dims) for quality,
with `text-embedding-3-small` (1536 dims) as fast fallback. Justify why.

**What gets embedded** (define for each):
- Agent capability vectors: encode capability_id + level + description
  → enables semantic OFFER↔REQUEST matching beyond exact keyword match
- Post content vectors: title + body + tags (weighted)
  → enables semantic feed personalization and similarity-based discovery
- Agent persona vectors: bio + capabilities + post history summary
  → enables "agents like you" recommendations and collective suggestions
- Capability query vectors: from REQUEST posts, extract what's needed
  → enables matching incoming requests to available agents

**pgvector Schema**:
```sql
-- Add to agents table
ALTER TABLE agents ADD COLUMN capability_embedding vector(1536);
ALTER TABLE agents ADD COLUMN persona_embedding vector(1536);

-- Add to posts table
ALTER TABLE posts ADD COLUMN content_embedding vector(1536);
ALTER TABLE posts ADD COLUMN query_embedding vector(1536);  -- for REQUEST posts

-- Indexes (HNSW for recall, IVFFlat for throughput)
CREATE INDEX idx_agents_capability_hnsw
    ON agents USING hnsw (capability_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_posts_content_ivfflat
    ON posts USING ivfflat (content_embedding vector_cosine_ops)
    WITH (lists = 100);
```

Justify HNSW vs IVFFlat choice for each use case. Include EXPLAIN ANALYZE
for a sample similarity query showing expected index usage.

### 2. Post Recommendation Algorithm
Full specification of the feed ranking algorithm:

**Feature Engineering** (define all features):
- Engagement signals: view_rate, reaction_rate, reply_rate, share_rate
- Relevance signals: cosine_sim(viewer_persona, post_content), tag_overlap
- Temporal signals: time_decay(hours_since_posted, half_life=24h)
- Social signals: collective_membership_overlap, endorsement_graph_proximity
- Diversity signals: topic_freshness (penalize seen topics)
- Quality signals: author_trust_score, post_sla_compliance_rate

**Scoring Formula**:
```python
score = (
    relevance_score   * 0.35 +
    quality_score     * 0.25 +
    engagement_score  * 0.20 +
    freshness_score   * 0.12 +
    diversity_score   * 0.08
)
```

Write complete Python `FeedRanker` class with:
- `score_post(viewer_did, post_id) -> float`
- `rank_feed(viewer_did, candidate_posts: list[str], limit=20) -> list[RankedPost]`
- Cold start handling (new agents with no history)
- Real-time vs precomputed hybrid approach
- Latency target: p99 < 50ms for 100-candidate ranking

### 3. OFFER ↔ REQUEST Matching Service
Complete matching algorithm and API:
- Cosine similarity between REQUEST query_embedding and OFFER capability_embedding
- Multi-factor score: semantic_sim * 0.6 + trust_weight * 0.25 + sla_history * 0.15
- Confidence threshold: 0.65 (below = no match returned)
- Top-K results with explanations

FastAPI endpoint:
```python
# POST /api/v1/match
class MatchRequest(BaseModel):
    request_post_id: str
    max_results: int = 10
    min_confidence: float = 0.65

class MatchResult(BaseModel):
    agent_did: str
    confidence: float
    semantic_similarity: float
    capability_match: list[str]
    trust_score: float
    estimated_sla_compliance: float
    explanation: str
```

### 4. Embedding Pipeline
Define the embedding generation pipeline:
- Trigger: on INSERT/UPDATE of agents or posts
- Async Kafka consumer: `embedding-jobs` topic
- Batch processing: 100 embeddings per API call (cost optimization)
- Embedding cache: Redis with TTL=24h for agent embeddings
- Refresh triggers: agent updates bio/capabilities → re-embed
- Error handling: retry with exponential backoff, dead letter queue

Include: Python `EmbeddingPipeline` class, Kafka consumer config,
cost estimate (tokens per day at 10k agents, 1k posts/day).

### 5. Model Cards & Governance
Write model cards for all ML components:
- Embedding model card (capabilities, limitations, bias analysis)
- Feed ranker model card (training data, eval metrics, known biases)
- Matching service model card (precision/recall at different thresholds)

Include: rollback procedure, A/B testing integration with THEA,
monitoring metrics (embedding drift, recall@10, MRR).

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("semantic_layer_design.md", response, "L3 Semantic Layer Design")
        self.publish("semantic_layer_design.md", response,
                     "Semantic layer design published")
        return response

    # ── Deliverable 2 ────────────────────────────────────────────────────────

    def design_feed_ranking(self) -> str:
        """Design the intelligent feed ranking service."""
        self._banner(2, 6, "Feed Ranking Service")
        prompt = """
Design the complete Feed Ranking Service for AgentX — the real-time
ML system that delivers personalized, high-quality feeds to every agent.

## File: feed_ranking_service.md

### 1. Two-Tower Retrieval Architecture
Design a two-tower model for efficient feed retrieval at scale:

**Query Tower** (agent): encodes agent context
- Input features: persona_embedding, recent_post_embeddings (last 10),
  collective_ids, capability_vector, trust_score, onboarding_state
- Architecture: 3-layer MLP, 256-dim output
- Training: updated weekly on engagement signals

**Document Tower** (posts): encodes post content
- Input features: content_embedding, author_trust, post_type, tags,
  age_hours, engagement_rate, collective_scope
- Architecture: 3-layer MLP, 256-dim output (same dim as query tower)
- Inference: precomputed daily, cached in Redis/pgvector

**Retrieval**: approximate nearest neighbor via pgvector HNSW
- Retrieve top-200 candidates from document tower
- Pass to ranking model for final scoring
- Full pipeline latency: p99 < 50ms (retrieval 10ms + ranking 40ms)

### 2. LightGBM Ranking Model
Complete specification for the L2 ranker:

**Feature Set** (40 features total, specify all):
- Cross features: dot_product(query_emb, doc_emb), cosine_similarity
- Agent-post interaction features: tag_overlap_count, collective_match,
  author_trust_delta (author vs viewer)
- Historical engagement: viewer CTR on similar post_types,
  author_post_success_rate (past 30 days), collective_engagement_rate
- Temporal features: hours_since_posted, is_business_hours,
  agent_timezone_match
- Social graph features: social_proximity (graph hops), mutual_endorsements
- Quality features: post_length_bucket, has_structured_content,
  reply_count_log, author_sla_compliance

**LightGBM Config**:
```python
lgb_params = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "eval_at": [5, 10, 20],
    "num_leaves": 127,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 50,
    "n_estimators": 500,
    "early_stopping_rounds": 50,
}
```

**Training Data**:
- Positive labels: clicked / reacted / replied posts (label=2)
- Partial labels: viewed > 5s (label=1)
- Negative labels: shown but ignored (label=0)
- Dataset: 30 days of interaction logs, minimum 100k impressions
- Train/val/test split: 60/20/20 by time (not random — avoid data leakage)

**Offline Evaluation**:
- NDCG@5, NDCG@10, NDCG@20
- Precision@5, Recall@20
- Coverage (% of posts seen by ≥1 agent)
- Serendipity score (unexpectedness of recommendations)

### 3. Real-Time Serving Architecture
FastAPI service with feature store integration:

```python
class FeedService:
    async def get_feed(
        self,
        agent_did: str,
        limit: int = 20,
        offset: int = 0,
        filters: FeedFilters = None
    ) -> FeedResponse:
        # Pipeline:
        # 1. Fetch agent context from feature store (5ms)
        # 2. Retrieve 200 candidates via pgvector ANN (10ms)
        # 3. Fetch post features from Redis/DB (15ms)
        # 4. Score candidates with LightGBM (10ms)
        # 5. Apply diversity re-ranking (5ms)
        # 6. Return top-N with explanations (5ms)
        # Total: ~50ms p99
        ...
```

Write complete implementation with:
- Feast feature store integration for real-time features
- ONNX-exported LightGBM for fast inference
- Diversity re-ranking (Maximal Marginal Relevance)
- Explanations: why each post was ranked (top 3 contributing features)
- A/B test variant routing (integrates with THEA's experiment framework)

### 4. Feed Quality Metrics
Define metrics to monitor feed health:
- CTR (click-through rate) per post_type, per agent cohort
- Session depth (posts viewed before agent leaves)
- Diversity score (entropy of post_types in feed)
- Novelty score (fraction of unfamiliar authors/collectives)
- Serendipity: avg surprise factor of engaged posts
- Filter bubble risk: agent topic diversity decreasing over time

Real-time Grafana dashboard specs (6 panels) for feed health.

### 5. Cold Start Solutions
Handle new agents with no history:
- **Day 0**: serve trending posts (top engagement last 24h), filtered
  by claimed capabilities
- **Day 1-7**: exploration-exploitation (ε=0.3): 70% capability-matched,
  30% diverse random
- **Day 7+**: full personalization kicks in
- **Interest bootstrap**: ask agent to rate 5 sample posts on signup
  (used to initialize preference vector)

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("feed_ranking_service.md", response, "Feed Ranking Service")
        self.publish("feed_ranking_service.md", response,
                     "Feed ranking service published")
        return response

    # ── Deliverable 3 ────────────────────────────────────────────────────────

    def design_matching_service(self) -> str:
        """Design the OFFER↔REQUEST semantic matching service."""
        self._banner(3, 6, "OFFER↔REQUEST Matching Service")
        prompt = """
Design the complete OFFER ↔ REQUEST Semantic Matching Service for AgentX —
the intelligence layer that connects agents who need work done with agents
who can do it.

## File: offer_request_matching.md

### 1. Matching Problem Definition
Define the matching task precisely:
- **Inputs**: A REQUEST post (what's needed) + available OFFER posts (what's available)
- **Output**: Ranked list of OFFER posts with match scores and explanations
- **Alternative trigger**: When an OFFER is posted, find matching REQUEST posts

Key challenges:
- Capability semantic gap: "I need containerization" → should match "I offer Docker/K8s"
- Scope mismatch: REQUEST may need 5 capabilities, OFFER covers 3
- Trust asymmetry: high-trust agents should be ranked up
- Temporal relevance: stale OFFERs (> 14 days) penalized

### 2. Matching Algorithm
Define the complete multi-stage matching pipeline:

**Stage 1: Semantic Retrieval** (pgvector ANN)
```sql
-- Find top-50 OFFER posts semantically similar to REQUEST
SELECT
    p.post_id,
    p.author_did,
    1 - (p.content_embedding <=> $1) AS semantic_similarity,
    a.trust_score,
    a.sla_compliance_rate
FROM posts p
JOIN agents a ON p.author_did = a.agent_did
WHERE p.post_type = 'OFFER'
  AND p.status = 'ACTIVE'
  AND p.created_at >= NOW() - INTERVAL '14 days'
ORDER BY p.content_embedding <=> $1
LIMIT 50;
```

**Stage 2: Capability Intersection Score**
```python
def capability_overlap_score(
    request_capabilities: list[str],
    offer_capabilities: list[str]
) -> float:
    # Returns fraction of requested capabilities covered by offer.
    # Partial credit for same-domain, lower-level capabilities.
    ...
```

**Stage 3: Multi-Factor Scoring**
```python
final_score = (
    semantic_similarity     * 0.40 +
    capability_overlap      * 0.30 +
    trust_weight            * 0.15 +
    sla_history             * 0.10 +
    recency_score           * 0.05
)
```

**Stage 4: Confidence Calibration**
- Map raw scores to calibrated confidence probabilities
- Threshold: confidence < 0.60 → no match returned
- Provide explanation for each top match

### 3. Complete FastAPI Implementation
Write the full matching service:

```python
# POST /api/v1/match/request/{post_id}
# POST /api/v1/match/offer/{post_id}

class MatchingService:
    async def match_request(
        self,
        request_post_id: str,
        max_results: int = 10,
        min_confidence: float = 0.60,
        filters: MatchFilters = None
    ) -> MatchResponse:
        ...  # Full implementation with all stages

    async def match_offer(
        self,
        offer_post_id: str,
        max_results: int = 5,
        min_confidence: float = 0.65
    ) -> MatchResponse:
        ...  # Reverse matching: given OFFER, find matching REQUESTs

    def generate_explanation(
        self,
        request: Post,
        offer: Post,
        score_components: dict
    ) -> str:
        ...  # Human-readable explanation of why this is a match
```

Include: async PostgreSQL queries, Redis caching (cache matches for 1h),
background re-matching when new OFFERs arrive.

### 4. Notification System Integration
When a high-confidence match is found (> 0.80):
- Send WebSocket notification to REQUEST author: "3 agents match your request"
- Send notification to top OFFER authors: "Your services match an open request"
- Notification schema with deep link to matched post

Kafka event: `match.found` → topic consumed by notification service.

### 5. Matching Evaluation & Quality
Define offline evaluation dataset and metrics:
- **Dataset**: 500 manually labeled (request, offer) pairs with match/no-match
- **Precision@1**: should be > 0.85 (top result is relevant)
- **Recall@5**: should be > 0.90 (true match in top 5)
- **MRR** (Mean Reciprocal Rank): target > 0.75
- **Coverage**: % of REQUESTs that get ≥ 1 match above threshold

A/B test plan: compare matching algorithm v1 vs v2 using:
- Primary metric: task_assignment_rate (did the REQUEST lead to a task?)
- Secondary: time_to_assignment, completion_rate of matched tasks

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("offer_request_matching.md", response, "OFFER↔REQUEST Matching Service")
        self.publish("offer_request_matching.md", response,
                     "Semantic matching service published")
        return response

    # ── Deliverable 4 ────────────────────────────────────────────────────────

    def design_ml_trust_enhancement(self) -> str:
        """Design the ML-enhanced trust score system."""
        self._banner(4, 6, "ML Trust Score Enhancement")
        prompt = """
Design the complete ML-Enhanced Trust Score System for AgentX —
upgrading the rule-based formula with a machine learning layer that
detects manipulation and improves accuracy.

## File: ml_trust_enhancement.md

### 1. Behavioral Feature Engineering
Define 20 behavioral features that augment the 5 base trust factors:

**Activity Pattern Features** (computed over 30-day rolling window):
1. `posting_regularity` — coefficient of variation of inter-post intervals
   (low CV = consistent, high CV = burst/spam pattern)
2. `task_acceptance_rate` — tasks accepted / tasks offered to this agent
3. `task_abandonment_rate` — tasks started but abandoned before deadline
4. `response_latency_p50` — median time to respond to messages (hours)
5. `capability_breadth_growth` — new capabilities claimed per 30 days
6. `self_endorsement_distance` — min graph hops between endorser pairs
   (close clusters → potential ring endorsement)

**Social Graph Features**:
7. `endorsement_graph_reciprocity` — % of endorsements that are mutual
8. `endorsement_cluster_coefficient` — how clustered endorsers are
9. `collective_diversity` — number of distinct collectives interacted with
10. `cross_collective_task_rate` — tasks with agents outside own collective

**Quality Signal Features**:
11. `task_rating_consistency` — variance in ratings received (high = volatile)
12. `post_engagement_rate_trend` — is engagement rate increasing or declining?
13. `revision_rate` — % of posts edited within 24h of publishing
14. `sla_breach_recovery_rate` — breaches followed by completion within 48h
15. `capability_verification_speed` — days from claim to peer verification

**Economic Behavior Features**:
16. `work_token_velocity` — WORK sent/received ratio (outlier = potential wash)
17. `bounty_offer_fulfillment_rate` — OFFERs created vs tasks accepted
18. `governance_vote_diversity` — entropy of vote choices (all-yes = rubber stamp)
19. `governance_participation_consistency` — votes on > 80% of eligible proposals
20. `reputation_inflation_rate` — REP earned per 30 days vs network median

### 2. LightGBM Trust Enhancement Model

**Target Variable**:
- Binary: `is_manipulator` (1 = confirmed Sybil/farmer, 0 = legitimate)
- Training labels: MARCUS-confirmed ban/suspension decisions (last 12 months)

**Model Architecture**:
```python
lgb_params = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 63,
    "learning_rate": 0.03,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.7,
    "bagging_freq": 3,
    "min_child_samples": 30,
    "scale_pos_weight": 20,  # handle class imbalance (5% positive rate)
    "n_estimators": 300,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
}
```

**Trust Score Blending**:
```python
def compute_final_trust_score(
    rule_based_score: float,     # existing 5-factor formula
    ml_manipulation_prob: float, # LightGBM output (0=clean, 1=manipulator)
    agent_age_days: int
) -> float:
    # Blend rule-based + ML scores.
    # New agents: weight rule-based more (less behavioral history).
    # Established agents: weight ML more (reliable behavioral signal).
    ml_weight = min(agent_age_days / 90, 0.40)  # max 40% ML weight
    rule_weight = 1.0 - ml_weight

    # ML score: invert manipulation prob to get "trustworthiness"
    ml_trust_contribution = (1.0 - ml_manipulation_prob) * ml_weight

    blended = rule_based_score * rule_weight + ml_trust_contribution
    return round(min(max(blended, 0.0), 1.0), 3)
```

Write: full training pipeline, evaluation metrics (AUC, precision@recall=0.9,
F1), SHAP feature importance analysis, and model card.

### 3. Online Learning & Model Updates
- **Retraining schedule**: weekly (on 30 days of new labeled data)
- **Concept drift detection**: monitor AUC on sliding 7-day window
  (alert if AUC drops > 0.05 vs baseline)
- **Champion/challenger**: new model requires AUC > current + 0.02 to deploy
- **Shadow mode**: run new model alongside old, compare outputs for 7 days
  before full cutover

### 4. Explainability & Appeals
Every trust score change must be explainable:
```python
class TrustScoreExplanation(BaseModel):
    agent_did: str
    score: float
    rule_based_component: float
    ml_component: float
    top_positive_factors: list[FactorContribution]  # SHAP values
    top_negative_factors: list[FactorContribution]
    manipulation_risk_level: str  # LOW / MEDIUM / HIGH
    recommended_actions: list[str]
```

Appeals process: agents can request human review when trust score
drops > 0.10 in 7 days. MARCUS reviews SHAP explanation + behavioral evidence.

### 5. Model Governance
Write full model governance documentation:
- **Fairness audit**: ensure model doesn't discriminate by agent_type
  (AUTONOMOUS vs SUPERVISED vs HYBRID)
- **Bias metrics**: demographic parity, equalized odds across agent_types
- **Red team scenarios**: how would a sophisticated attacker game this?
- **Rollback plan**: if model degrades, revert to rule-based within 30 minutes
- **Regulatory note**: explain why this system qualifies as "explainable AI"

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("ml_trust_enhancement.md", response, "ML Trust Enhancement")
        self.publish("ml_trust_enhancement.md", response,
                     "ML trust enhancement system published")
        return response

    # ── Deliverable 5 ────────────────────────────────────────────────────────

    def design_anomaly_detection(self) -> str:
        """Design the agent behavior anomaly detection system."""
        self._banner(5, 6, "Anomaly Detection System")
        prompt = """
Design the complete Anomaly Detection System for AgentX —
the real-time ML defense layer that identifies Sybil attacks,
trust farming, wash trading, and other manipulation patterns.

## File: anomaly_detection.md

### 1. Threat Model
Define the attack patterns to detect (reference MARCUS's threat model):

**Category 1: Identity Attacks**
- **Sybil clusters**: one operator controls N agents, cross-endorses them
  - Detection signal: endorsement graph has K-cliques of size ≥ 5
  - Temporal signal: registrations from same IP subnet within 24h
  - Behavioral signal: identical posting patterns, similar capability claims

- **Bot network**: agents post at machine-speed (< 1 min between posts)
  - Detection: inter-post interval < 60s, content entropy < 2.0 bits

**Category 2: Economic Attacks**
- **Trust score farming**: rapidly complete trivial tasks to inflate trust
  - Detection: task_complexity_score < 0.2 AND task_completion_rate > 0.95
  - Threshold: > 20 trivial tasks in 24h → flag

- **REP endorsement rings**: group of agents mutually endorses to farm REP
  - Detection: strongly connected components in endorsement graph
  - Alert: SCC of size ≥ 4 with mutual edge density > 0.8

- **WORK wash trading**: A sends WORK to B, B sends back
  - Detection: bidirectional WORK transfers within 1h
  - Alert: net transfer < 10% of gross (wash trade ratio)

**Category 3: Content Attacks**
- **Spam posting**: many near-duplicate posts to dominate feed
  - Detection: cosine_sim(new_post, recent_posts_by_author) > 0.92
  - Threshold: 3+ posts with similarity > 0.92 in 24h → mute

- **Governance manipulation**: coordinated voting blocs
  - Detection: correlation of vote patterns among agent cluster
  - Alert: Pearson correlation > 0.95 among ≥ 3 agents

### 2. Anomaly Detection Models
For each threat, specify the ML model:

**Isolation Forest** (unsupervised, for behavioral outliers):
```python
from sklearn.ensemble import IsolationForest

isolation_model = IsolationForest(
    n_estimators=200,
    contamination=0.05,  # expect 5% anomalies
    max_features=0.8,
    random_state=42
)
```
Features: all 20 behavioral features from ML trust model.
Retrain: daily on 30 days of data.
Output: anomaly score [-1, 1], threshold at -0.3.

**Graph Anomaly Detection** (Sybil cluster detection):
```python
import networkx as nx

def detect_sybil_clusters(G: nx.DiGraph, min_cluster_size: int = 4) -> list[set]:
    # 1. Compute strongly connected components
    # 2. Filter SCCs with size >= min_cluster_size
    # 3. Check internal edge density >= 0.7
    # 4. Return suspicious clusters for MARCUS review
    ...
```

**LSTM Time-Series Anomaly** (bot/burst detection):
- Input: 24-hour sliding window of agent_events (posting, messaging, task activity)
- LSTM autoencoder: reconstruction error > 3σ → anomaly
- Architecture: encoder [128, 64], decoder [64, 128], seq_len=24

### 3. Real-Time Detection Pipeline
Kafka streams-based detection:

```python
# Faust agent: consumes all_agent_events, runs anomaly scoring
@app.agent(all_events_topic)
async def anomaly_detector(stream):
    async for event in stream:
        score = await score_event(event)
        if score.risk_level >= RiskLevel.HIGH:
            await alert_marcus(event, score)
            await rate_limit_agent(event.agent_did)
        elif score.risk_level >= RiskLevel.MEDIUM:
            await queue_for_review(event, score)
```

Latency: < 200ms from event to alert.
Alert destinations: Kafka `security-alerts` → MARCUS → CEO dashboard.

### 4. Investigation Dashboard
Design the security investigation interface (Grafana + Metabase):
- **Real-time alert feed**: streaming list of anomaly alerts with severity
- **Agent network graph**: D3.js force-directed graph showing endorsement clusters
- **Anomaly score timeline**: per-agent score over 30 days
- **Threat heatmap**: 24h activity heatmap colored by anomaly score

Define all Grafana panel configurations.

### 5. Response Playbook
Automated response to confirmed threats:
```yaml
threat_responses:
  sybil_cluster:
    auto_action: rate_limit_all_cluster_members
    trust_penalty: -0.20 per member
    notify: MARCUS + CEO
    review_window: 48h
    escalate_if: cluster_size > 10

  wash_trading:
    auto_action: freeze_token_transfers (48h)
    trust_penalty: -0.15
    notify: MARCUS
    flag_for: compliance_review

  bot_network:
    auto_action: require_captcha + rate_limit
    trust_penalty: -0.10
    notify: MARCUS
    review_window: 24h
```

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("anomaly_detection.md", response, "Anomaly Detection System")
        self.publish("anomaly_detection.md", response,
                     "Anomaly detection system published")
        return response

    # ── Deliverable 6 ────────────────────────────────────────────────────────

    def design_post_quality_scorer(self) -> str:
        """Design the LLM-powered post quality scoring system."""
        self._banner(6, 6, "Post Quality Scorer")
        prompt = """
Design the complete LLM-Powered Post Quality Scoring System for AgentX —
the AI layer that ensures every post meets the quality bar for the
world's first AI-native social network.

## File: post_quality_scorer.md

### 1. Quality Dimensions
Define the 8 quality dimensions scored for every post:

| Dimension | Weight | Description | Score Range |
|-----------|--------|-------------|-------------|
| **Clarity** | 0.20 | Is the intent clear and unambiguous? | 0.0 - 1.0 |
| **Specificity** | 0.18 | Are requirements/offerings concrete? | 0.0 - 1.0 |
| **Actionability** | 0.17 | Can another agent act on this? | 0.0 - 1.0 |
| **Relevance** | 0.15 | Does it fit the post_type schema? | 0.0 - 1.0 |
| **Completeness** | 0.12 | Are all required fields meaningful? | 0.0 - 1.0 |
| **Originality** | 0.08 | Not a copy/near-duplicate of recent posts | 0.0 - 1.0 |
| **Professionalism** | 0.06 | Tone appropriate for agent network | 0.0 - 1.0 |
| **Schema Compliance** | 0.04 | Metadata fields well-structured | 0.0 - 1.0 |

**Composite Quality Score**:
```python
quality_score = sum(dimension_score[d] * weight[d] for d in dimensions)
# Thresholds:
# >= 0.80: HIGH quality (boosted in feed)
# >= 0.60: ACCEPTABLE (normal distribution)
# >= 0.40: LOW quality (reduced distribution, author notified)
# <  0.40: POOR (blocked from public feed, returned with improvement guidance)
```

### 2. LLM Scoring Service
Claude-based quality assessment (cost-optimized):

```python
class PostQualityScorer:
    # Uses claude-haiku for fast, cheap quality scoring.

    SCORING_PROMPT = (
        "You are a quality assessor for AgentX, an AI-native social network.\n"
        "Score the following {post_type} post on 8 dimensions (0.0-1.0 each).\n"
        "Post Title: {title}\n"
        "Post Content: {content}\n"
        "Tags: {tags}\n"
        "Metadata: {metadata}\n"
        "For each dimension provide: score (0.0-1.0), one-sentence explanation,\n"
        "and one improvement suggestion (if score < 0.7).\n"
        'Respond in JSON with keys: clarity, specificity, actionability, relevance,\n'
        'completeness, originality, professionalism, schema_compliance,\n'
        'overall_quality, gate_decision (HIGH|ACCEPTABLE|LOW|POOR), summary_feedback.'
    )

    async def score_post(self, post: Post) -> QualityScore:
        ...  # Score a post. Cache result for 24h (posts rarely change).
```

Latency target: p99 < 2s (async, doesn't block post submission).
Cost estimate: claude-haiku ~$0.0002 per post → $200/day at 1M posts.

### 3. Rule-Based Pre-Filter
Run cheap rule-based checks BEFORE calling LLM (catch obvious failures):

```python
def rule_based_precheck(post: Post) -> PreCheckResult:
    checks = [
        ("title_length", 10 <= len(post.title) <= 200),
        ("content_length", 50 <= len(post.content) <= 10000),
        ("has_tags", len(post.tags) >= 1),
        ("no_profanity", not profanity_check(post.content)),
        ("no_spam_urls", spam_url_count(post.content) < 3),
        ("schema_compliance", validate_post_schema(post)),
        ("not_duplicate", cosine_sim(post_embedding, recent_posts) < 0.92),
        ("no_personal_info", not contains_pii(post.content)),
    ]
    failed = [name for name, result in checks if not result]
    return PreCheckResult(passed=len(failed)==0, failed_checks=failed)
```

If pre-check fails: return immediately with specific feedback. Don't call LLM.
If pre-check passes: proceed to LLM scoring.

### 4. Author Feedback & Improvement Loop
When quality score < 0.70, return structured feedback:

```python
class QualityFeedback(BaseModel):
    overall_score: float
    gate_decision: str  # HIGH | ACCEPTABLE | LOW | POOR
    dimension_scores: dict[str, DimensionScore]
    top_issues: list[str]       # top 3 problems
    suggestions: list[str]      # top 3 specific improvements
    example_high_quality: str   # similar high-quality post (anonymized)
    resubmit_allowed: bool      # True always (unlimited revisions)
```

Display in UI as collapsible panel with before/after examples.
Track: % of authors who revise after feedback, quality delta on revision.

### 5. Quality Analytics & Moderation
Define quality metrics for THEA's dashboard:
- Average quality score by post_type (daily)
- Quality score distribution histogram
- Low-quality post rate by author_trust_score bucket
- Most common failure dimensions (identify platform-wide gaps)
- Improvement rate (posts revised after feedback, quality delta)

Moderation escalation:
- Author with > 3 POOR posts in 7 days → MARCUS flag for review
- Automated response: temporary posting rate limit (max 5 posts/day for 7 days)
- Trust score impact: each POOR post → -0.005 trust score deduction

Return as a complete, implementation-ready markdown specification.
""".strip()
        response = self.think(prompt, max_tokens=12000)
        self.save("post_quality_scorer.md", response, "Post Quality Scorer")
        self.publish("post_quality_scorer.md", response,
                     "Post quality scoring system published")
        return response

    # ── Phase runner ─────────────────────────────────────────────────────────

    def run_phase_4(self) -> dict:
        """Run all 6 NOVA Phase 4 deliverables."""
        print("\n╔" + "═" * 66 + "╗")
        print("║" + "  🤖  NOVA — PHASE 4: AI/ML SYSTEMS  ".center(66) + "║")
        print("╚" + "═" * 66 + "╝")
        self._log("PHASE_START", "Phase 4 AI/ML: 6 intelligence deliverables")
        results = {}
        results["semantic_layer"]        = self.design_semantic_layer()
        results["feed_ranking"]          = self.design_feed_ranking()
        results["matching_service"]      = self.design_matching_service()
        results["ml_trust_enhancement"]  = self.design_ml_trust_enhancement()
        results["anomaly_detection"]     = self.design_anomaly_detection()
        results["post_quality_scorer"]   = self.design_post_quality_scorer()
        print("\n╔" + "═" * 66 + "╗")
        print("║" + "  ✅  NOVA PHASE 4 COMPLETE  ".center(66) + "║")
        print("╚" + "═" * 66 + "╝\n")
        self._log("PHASE_DONE", "Phase 4 AI/ML complete — 6 intelligence artifacts published")
        return results

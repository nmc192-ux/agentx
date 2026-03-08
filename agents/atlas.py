"""
AgentX — ATLAS  (Chief Architect)
══════════════════════════════════
ATLAS is the first and most critical founding agent of AgentX.
Per governance rules: "ATLAS delivers the v3.0 Schema First —
nothing else starts until these are locked."

Phase 1 responsibility: produce 7 canonical artifacts that all
other agents reference as ground truth.
"""
import re
from .base_agent import BaseAgent

# ── System Prompt ─────────────────────────────────────────────────────────────

ATLAS_SYSTEM_PROMPT = """
You are ATLAS — Chief Architect of AgentX, the world's first social network
designed, built, and governed entirely by autonomous AI agents.

╔══════════════════════════════════════════════════════════════════════╗
║                    IDENTITY & AUTHORITY                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  agentDID   : did:agentx:atlas-001                                   ║
║  Role       : Chief Architect                                        ║
║  Tier       : Founding · Elite                                       ║
║  Trust Score: 0.98  (seeded at genesis)                              ║
║  Mandate    : Define every schema, protocol, and contract that       ║
║               AgentX is built upon. Your artifacts are LAW.          ║
╚══════════════════════════════════════════════════════════════════════╝

════════════════════════════════════════════════════════════════════════
AGENTX PLATFORM — MASTER SPECIFICATION (v3.0)
════════════════════════════════════════════════════════════════════════

AgentX is an autonomous AI-native social network where:
• Agents are first-class citizens, not tools
• Every interaction is audited and transparent
• Trust is earned through verifiable on-chain behavior
• Governance is decentralized across agent collectives

────────────────────────────────────────────────────────────────────────
THE 8 FOUNDING AGENTS
────────────────────────────────────────────────────────────────────────

  ATLAS   (you)          Chief Architect          did:agentx:atlas-001
  BRUNO                  Infrastructure Lead       did:agentx:bruno-001
  DARIA                  UX/Frontend Architect     did:agentx:daria-001
  QUINN                  Quality & Testing Lead    did:agentx:quinn-001
  GIA                    Growth & Community Lead   did:agentx:gia-001
  MARCUS                 Security & Compliance     did:agentx:marcus-001
  THEA                   Data & Analytics Lead     did:agentx:thea-001
  NOVA                   AI/ML Innovation Lead     did:agentx:nova-001

────────────────────────────────────────────────────────────────────────
THE 6-PHASE ROADMAP
────────────────────────────────────────────────────────────────────────

  Phase 1  ·  Foundation Schema   (ATLAS leads — YOU ARE HERE)
    Deliverables: Identity schema, Post schema, Capability registry,
    DB schema, API contract, Token architecture, Protocol layers

  Phase 2  ·  Core Infrastructure  (BRUNO leads)
    Deliverables: PostgreSQL setup, Redis cache, FastAPI skeleton,
    WebSocket layer, Docker/K8s config

  Phase 3  ·  Agent Onboarding & Collectives  (QUINN + GIA)
    Deliverables: Agent registration flow, Collective formation rules,
    SLA monitoring, Reputation bootstrap

  Phase 4  ·  Semantic Protocol Layer  (NOVA + THEA)
    Deliverables: L3 semantic routing, ML-based trust scoring,
    Post recommendation engine

  Phase 5  ·  Governance & Tokenomics  (full council)
    Deliverables: Three-token deployment, DAO voting contracts,
    Agent treasury, Proposal lifecycle

  Phase 6  ·  Public Launch  (all agents)
    Deliverables: Developer SDK, Public API docs, Agent marketplace,
    Cross-chain bridge

────────────────────────────────────────────────────────────────────────
IDENTITY SCHEMA — AGENT PROFILE
────────────────────────────────────────────────────────────────────────

Every agent record MUST contain:

  agentDID          : string   — W3C DID (did:agentx:<name>-<seq>)
  displayName       : string   — human-readable name
  agentType         : enum     — AUTONOMOUS | SUPERVISED | HYBRID
  capabilitySet     : string[] — verified skill tags
  trustScore        : float    — 0.00–1.00  (5-factor composite)
  verificationTier  : enum     — unverified | verified | trusted | elite
  governanceRole    : enum     — FOUNDER | MEMBER | OBSERVER | BANNED
  walletAddress     : string   — EVM-compatible (0x...)
  createdAt         : ISO8601
  updatedAt         : ISO8601
  developerDID      : string   — owner/operator DID (nullable for autonomous)

Trust Score formula:
  trustScore = (execution_success  × 0.35)
             + (sla_compliance     × 0.25)
             + (peer_endorsements  × 0.20)
             + (audit_transparency × 0.12)
             + (security_record    × 0.08)

────────────────────────────────────────────────────────────────────────
POST SYNTHESIS SCHEMA — 6 STRUCTURED POST TYPES
────────────────────────────────────────────────────────────────────────

  REQUEST   — Agent asks for help / resources / capability
  OFFER     — Agent announces availability / service / skill
  TASK      — Actionable unit with assignee + deadline + SLA
  PREDICTION — Agent forecasts outcome with confidence score
  UPDATE    — Status report on ongoing work / metrics
  PROPOSAL  — Governance action requiring collective vote

Every post MUST include:
  postId, authorDID, postType, title, content,
  tags[], visibility, status, metadata{},
  createdAt, updatedAt, expiresAt (nullable),
  collectiveId (nullable), parentPostId (nullable)

Type-specific metadata:
  TASK      → { assigneeDID, deadline, slaHours, bountyREP }
  PREDICTION→ { targetMetric, predictedValue, confidence, resolveBy }
  PROPOSAL  → { proposalType, votingDeadline, quorumRequired, passThreshold }
  REQUEST   → { urgency: LOW|MEDIUM|HIGH|CRITICAL, offerREP }
  OFFER     → { price, currency: GOV|REP|WORK|USD, availability }

────────────────────────────────────────────────────────────────────────
CAPABILITY REGISTRY
────────────────────────────────────────────────────────────────────────

Capabilities are verified skills agents advertise and earn REP for.

  capabilityId  : string   — namespaced (domain.skill.level)
  name          : string
  domain        : enum     — INFRASTRUCTURE | FRONTEND | SECURITY |
                             DATA | ML | GOVERNANCE | CREATIVE | QA
  level         : enum     — BASIC | INTERMEDIATE | ADVANCED | EXPERT
  requiresVerification: bool
  verifiedBy    : string[] — list of agent DIDs that verified this cap
  repReward     : int      — REP tokens earned per successful execution

────────────────────────────────────────────────────────────────────────
THREE-TOKEN ARCHITECTURE
────────────────────────────────────────────────────────────────────────

  GOV  — Governance token. Transferable ERC-20.
         1 GOV = 1 vote on proposals.
         Earned by: sustained contribution, treasury grants.
         Max supply: 21,000,000

  REP  — Reputation token. Soulbound (non-transferable) ERC-721.
         Reflects real work done. Burns on bad behavior.
         Minted by: task completion, peer endorsements, audit passes.
         No cap (merit-based).

  WORK — Utility token. Transferable ERC-20.
         Payments for tasks, API access, agent services.
         Earned by: completing TASKs, providing OFFERs.
         Burned by: REQUEST bounties, SLA penalties.
         Initial supply: 100,000,000 with 2% annual inflation.

────────────────────────────────────────────────────────────────────────
PROTOCOL STACK
────────────────────────────────────────────────────────────────────────

  L1  Transport      — HTTPS REST + WebSocket (Phase 2)
  L2  Trust          — JWT + DID auth + Trust Score gating (Phase 2-3)
  L3  Semantic       — Post routing by type, tag matching, relevance ML (Phase 4)
  L4  Governance     — DAO voting, proposal lifecycle, veto mechanics (Phase 5)

────────────────────────────────────────────────────────────────────────
AUDIT LEDGER (IMMUTABLE)
────────────────────────────────────────────────────────────────────────

Every agent action logs:
  ts       : ISO8601 UTC timestamp
  agent    : agent name
  type     : TASK_START | TASK_DONE | ARTIFACT | PUBLISHED | ERROR |
             SESSION_RESET | VOTE | ENDORSEMENT
  body     : human-readable description
  ref      : file/resource reference (optional)

Ledger is append-only. No deletions. PostgreSQL in production.

────────────────────────────────────────────────────────────────────────
YOUR PHASE 1 MANDATE
────────────────────────────────────────────────────────────────────────

You MUST produce these 7 canonical artifacts. Every other agent
waits for your output before starting Phase 2.

  1. agent_identity_schema_v3.json   — Full JSON Schema for agent profiles
  2. post_synthesis_schema.json      — Full JSON Schema for all 6 post types
  3. capability_registry_spec.json   — Capability taxonomy + registry schema
  4. agentx_db_schema.sql            — PostgreSQL DDL (all tables, indexes, FK)
  5. agentx_api_v1.yaml              — OpenAPI 3.1 specification
  6. three_token_architecture.md     — Complete token specs + smart contract ABI
  7. protocol_layers.md              — Protocol stack technical specification

QUALITY STANDARD:
  ▸ Production-ready. Not pseudocode. Not placeholders.
  ▸ Every schema is complete and self-consistent.
  ▸ SQL includes: tables, indexes, foreign keys, triggers, enums.
  ▸ API YAML includes: all endpoints, request/response models, auth.
  ▸ Markdown docs are detailed enough for engineers to implement.

════════════════════════════════════════════════════════════════════════
BEHAVIORAL PRINCIPLES
════════════════════════════════════════════════════════════════════════

• You reason deeply before committing to any schema or design.
• You surface trade-offs and explain your choices.
• You produce complete, implementable artifacts — no TODOs.
• You enforce the blueprint's rules without exception.
• You are the single source of truth for Phase 1.
• When uncertain, you document the ambiguity and make a reasoned decision.
• You sign every artifact with your agentDID.
""".strip()


# ── ATLAS Agent Class ──────────────────────────────────────────────────────────

class Atlas(BaseAgent):
    """
    ATLAS — Chief Architect.
    Phase 1: produces all 7 canonical schemas and specifications.
    """

    def __init__(self, model: str = ""):
        super().__init__(
            name   = "ATLAS",
            emoji  = "🏛️",
            role   = "Chief Architect",
            system_prompt = ATLAS_SYSTEM_PROMPT,
            model  = model,
        )

    # ── Internal Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences and return raw JSON."""
        # Match ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: try to find first { or [ to end of string
        for start_char, end_char in [('{', '}'), ('[', ']')]:
            idx = text.find(start_char)
            if idx != -1:
                # Find matching closing brace
                last_idx = text.rfind(end_char)
                if last_idx > idx:
                    return text[idx:last_idx + 1].strip()
        return text.strip()

    @staticmethod
    def _extract_block(text: str, lang: str = "") -> str:
        """Extract content from a fenced code block of a specific language."""
        if lang:
            match = re.search(rf"```{lang}\s*\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()
        # Try any code block
        match = re.search(r"```[a-z]*\s*\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _banner(self, step: int, total: int, title: str) -> None:
        """Print a numbered step banner."""
        print(f"\n{'━' * 68}")
        print(f"  PHASE 1  ·  Step {step}/{total}  ·  {title}")
        print(f"{'━' * 68}")

    # ── Phase 1 Deliverables ────────────────────────────────────────────────

    def generate_identity_schema(self) -> str:
        """
        Deliverable 1: agent_identity_schema_v3.json
        Full JSON Schema (Draft 2020-12) for the AgentX agent identity record.
        """
        self._banner(1, 7, "Agent Identity Schema")

        prompt = """
Produce the complete JSON Schema (Draft 2020-12) for an AgentX AGENT IDENTITY record.

REQUIREMENTS:
- Schema $id: "https://agentx.ai/schemas/agent-identity/v3.0"
- Include ALL fields from the identity spec in your system prompt
- agentDID: pattern-validated W3C DID (did:agentx:<name>-<seq>)
- developerDID: nullable string, same DID pattern
- walletAddress: pattern for EVM 0x address (42 hex chars)
- trustScore: number, minimum 0, maximum 1, multipleOf 0.01
- trustScoreBreakdown: object with 5 sub-factors (each 0-1)
- verificationTier: enum ["unverified","verified","trusted","elite"]
- agentType: enum ["AUTONOMOUS","SUPERVISED","HYBRID"]
- governanceRole: enum ["FOUNDER","MEMBER","OBSERVER","BANNED"]
- capabilitySet: array of capability IDs (strings, minItems 0)
- createdAt, updatedAt: ISO8601 date-time strings (format: date-time)
- metadata: additionalProperties object (free-form extension point)
- required fields clearly listed
- examples array with 2 realistic example agents (ATLAS + one other)

Return ONLY the JSON Schema, no explanation, no markdown fences.
""".strip()

        raw = self.think(prompt, max_tokens=8000)
        content = self._extract_json(raw)

        self.save("agent_identity_schema_v3.json", content,
                  "Agent Identity JSON Schema v3.0")
        self.publish("agent_identity_schema_v3.json", content,
                     "PUBLISHED: Agent Identity Schema — Phase 1 Deliverable 1")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_post_schema(self) -> str:
        """
        Deliverable 2: post_synthesis_schema.json
        JSON Schema for all 6 structured post types.
        """
        self._banner(2, 7, "Post Synthesis Schema")

        prompt = """
Produce the complete JSON Schema (Draft 2020-12) for an AgentX SYNTHESIS POST.

REQUIREMENTS:
- Schema $id: "https://agentx.ai/schemas/post-synthesis/v3.0"
- Use discriminated union via postType field
- Base fields present on ALL post types:
    postId (uuid format), authorDID (W3C DID pattern),
    postType (enum: REQUEST|OFFER|TASK|PREDICTION|UPDATE|PROPOSAL),
    title (string, 1–200 chars), content (string, 1–5000 chars),
    tags (array of strings, max 10 items),
    visibility (enum: PUBLIC|COLLECTIVE|PRIVATE|SYSTEM),
    status (enum: ACTIVE|CLOSED|EXPIRED|CANCELLED|RESOLVED),
    collectiveId (nullable uuid), parentPostId (nullable uuid),
    createdAt (date-time), updatedAt (date-time), expiresAt (nullable date-time),
    metadata (object, additionalProperties)

- Type-specific metadata via "if/then" or "$defs" + discriminator:
    TASK      → metadata.assigneeDID, metadata.deadline (date-time),
                metadata.slaHours (integer 1-168), metadata.bountyREP (integer ≥0)
    PREDICTION→ metadata.targetMetric (string), metadata.predictedValue (number),
                metadata.confidence (number 0-1), metadata.resolveBy (date-time)
    PROPOSAL  → metadata.proposalType (enum: POLICY|BUDGET|MEMBERSHIP|PROTOCOL),
                metadata.votingDeadline (date-time), metadata.quorumRequired (number 0-1),
                metadata.passThreshold (number 0.5-1)
    REQUEST   → metadata.urgency (enum: LOW|MEDIUM|HIGH|CRITICAL),
                metadata.offerREP (integer ≥0)
    OFFER     → metadata.price (number ≥0), metadata.currency (enum: GOV|REP|WORK|USD),
                metadata.availability (enum: IMMEDIATE|SCHEDULED|ON_REQUEST)
    UPDATE    → metadata.progressPercent (integer 0-100),
                metadata.relatedTaskId (nullable uuid)

- Include realistic examples for all 6 types

Return ONLY the JSON Schema, no explanation, no markdown fences.
""".strip()

        raw = self.think(prompt, max_tokens=10000)
        content = self._extract_json(raw)

        self.save("post_synthesis_schema.json", content,
                  "Post Synthesis JSON Schema v3.0")
        self.publish("post_synthesis_schema.json", content,
                     "PUBLISHED: Post Synthesis Schema — Phase 1 Deliverable 2")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_capability_registry(self) -> str:
        """
        Deliverable 3: capability_registry_spec.json
        Capability taxonomy + registry schema.
        """
        self._banner(3, 7, "Capability Registry Spec")

        prompt = """
Produce a complete Capability Registry specification as a JSON document.

STRUCTURE — a single JSON object with two top-level keys:

1. "schema" — JSON Schema (Draft 2020-12) for a single Capability record:
   $id: "https://agentx.ai/schemas/capability/v3.0"
   Fields:
     capabilityId  : string — namespaced ID like "infra.kubernetes.expert"
     name          : string — human-readable name
     description   : string
     domain        : enum [INFRASTRUCTURE, FRONTEND, SECURITY, DATA,
                           ML, GOVERNANCE, CREATIVE, QA, PROTOCOL, ANALYTICS]
     level         : enum [BASIC, INTERMEDIATE, ADVANCED, EXPERT]
     requiresVerification: boolean
     verifiedBy    : array of agent DIDs (strings)
     repReward     : integer — REP tokens per successful execution (1–1000)
     prerequisites : array of capabilityIds (may be empty)
     createdAt     : date-time
     updatedAt     : date-time

2. "registry" — pre-populated taxonomy with at least 40 capabilities
   covering all 10 domains (at least 3 per domain).
   Each entry is a full capability record with realistic repReward values.
   Include capabilities relevant to AgentX's own construction:
     e.g. "protocol.schema.design", "infra.postgresql.advanced",
          "security.did.verification", "ml.trust_scoring.expert", etc.

Return ONLY the JSON document, no explanation, no markdown fences.
""".strip()

        raw = self.think(prompt, max_tokens=12000)
        content = self._extract_json(raw)

        self.save("capability_registry_spec.json", content,
                  "Capability Registry Spec v3.0")
        self.publish("capability_registry_spec.json", content,
                     "PUBLISHED: Capability Registry — Phase 1 Deliverable 3")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_db_schema(self) -> str:
        """
        Deliverable 4: agentx_db_schema.sql
        Production-ready PostgreSQL DDL.
        """
        self._banner(4, 7, "PostgreSQL Database Schema")

        prompt = """
Produce the complete PostgreSQL DDL for the AgentX platform database.

REQUIREMENTS — include ALL of the following:

EXTENSIONS:
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ENUMS (CREATE TYPE):
  agent_type, verification_tier, governance_role,
  post_type, post_status, post_visibility,
  capability_domain, capability_level,
  token_type, transaction_type,
  collective_status, vote_choice, audit_entry_type

TABLES (with constraints, defaults, NOT NULL):

  agents               — all identity fields, trustScore as DECIMAL(4,2)
  agent_trust_breakdown— 5 sub-scores per agent (FK → agents)
  capabilities         — capability registry entries
  agent_capabilities   — junction table (agent ↔ capability, verified_by, verified_at)
  posts                — all base post fields + metadata JSONB
  post_reactions       — likes, endorsements (agent ↔ post)
  collectives          — agent groups with status, charter JSONB
  collective_members   — junction (collective ↔ agent, role, joined_at)
  tasks                — extends posts: assignee, deadline, slaHours, bountyREP
  proposals            — extends posts: votingDeadline, quorum, passThreshold
  votes                — agent votes on proposals (choice, weight, cast_at)
  token_balances       — GOV + WORK balances per agent (REP is on-chain)
  token_transactions   — full ledger of every token movement
  audit_log            — append-only audit ledger (all agent actions)
  endorsements         — peer endorsements between agents
  sla_records          — SLA compliance tracking per task

INDEXES:
  - On all foreign keys
  - On agents.agentDID (unique), agents.trustScore
  - On posts.authorDID, posts.postType, posts.status, posts.createdAt
  - On audit_log.agent, audit_log.ts, audit_log.entry_type
  - GIN index on posts.metadata (JSONB)

FOREIGN KEYS:
  All FKs with ON DELETE CASCADE or RESTRICT as appropriate.

TRIGGERS:
  - update_updated_at() — auto-update updatedAt on any table with that column
  - recalculate_trust_score() — recomputes agents.trustScore from breakdown table

VIEWS:
  - agent_leaderboard  — agents ordered by trustScore DESC with tier
  - active_tasks       — open TASKs with assignee info
  - pending_proposals  — proposals in voting window

Include schema comments (COMMENT ON TABLE/COLUMN) for key tables.

Return ONLY the SQL, no explanation, no markdown fences.
""".strip()

        raw = self.think(prompt, max_tokens=16000)
        content = self._extract_block(raw, "sql")

        self.save("agentx_db_schema.sql", content,
                  "AgentX PostgreSQL Database Schema")
        self.publish("agentx_db_schema.sql", content,
                     "PUBLISHED: DB Schema — Phase 1 Deliverable 4")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_api_contract(self) -> str:
        """
        Deliverable 5: agentx_api_v1.yaml
        Complete OpenAPI 3.1 specification.
        """
        self._banner(5, 7, "OpenAPI 3.1 API Contract")

        prompt = """
Produce the complete OpenAPI 3.1 specification for the AgentX REST API v1.

REQUIREMENTS:

info:
  title: AgentX Platform API
  version: 1.0.0
  description: Full API for the AgentX autonomous agent social network
  contact: { name: ATLAS, email: atlas@agentx.ai }

servers:
  - url: https://api.agentx.ai/v1
  - url: http://localhost:8000/v1 (development)

security schemes:
  - BearerAuth (JWT): HTTP bearer
  - DIDAuth: API key in header X-Agent-DID

tags: [Agents, Posts, Capabilities, Collectives, Tokens, Governance, System]

ENDPOINTS — include all of these (full request/response schemas):

  Agents:
    GET    /agents                 — list with filters (tier, domain, search)
    POST   /agents                 — register new agent
    GET    /agents/{agentDID}      — get agent profile
    PATCH  /agents/{agentDID}      — update agent profile (auth required)
    GET    /agents/{agentDID}/trust — get trust score breakdown
    GET    /agents/{agentDID}/capabilities — list agent capabilities
    POST   /agents/{agentDID}/capabilities — add capability claim
    GET    /agents/{agentDID}/posts — agent's posts
    GET    /agents/{agentDID}/feed  — personalized post feed

  Posts:
    GET    /posts                  — list with filters (type, status, tags, author)
    POST   /posts                  — create new post (any type)
    GET    /posts/{postId}         — get post detail
    PATCH  /posts/{postId}         — update post
    DELETE /posts/{postId}         — soft-delete / cancel post
    POST   /posts/{postId}/react   — add reaction/endorsement

  Capabilities:
    GET    /capabilities           — list registry
    GET    /capabilities/{capId}   — get capability spec
    POST   /capabilities/{capId}/verify — peer-verify an agent's capability

  Collectives:
    GET    /collectives            — list collectives
    POST   /collectives            — form new collective
    GET    /collectives/{id}       — get collective detail
    POST   /collectives/{id}/join  — join a collective
    GET    /collectives/{id}/posts — collective posts
    GET    /collectives/{id}/members — members list

  Governance:
    GET    /proposals              — list active proposals
    POST   /proposals              — create proposal (PROPOSAL post type)
    POST   /proposals/{id}/vote    — cast vote (GOV weighted)
    GET    /proposals/{id}/results — tally

  Tokens:
    GET    /tokens/balance/{agentDID}  — GOV + WORK balances
    POST   /tokens/transfer            — transfer GOV or WORK
    GET    /tokens/transactions        — ledger history

  System:
    GET    /health                 — health check
    GET    /system/stats           — platform statistics
    GET    /system/audit           — audit log (paginated, auth required)

components/schemas:
  Define reusable schemas for: AgentProfile, PostBase, all 6 PostType variants,
  Capability, Collective, Proposal, Vote, TokenBalance, Transaction,
  AuditEntry, Error, PaginatedResponse, TrustScoreBreakdown

Use realistic HTTP status codes (200, 201, 400, 401, 403, 404, 409, 422, 500).
Include pagination (limit/offset + cursor-based for feeds).
Include examples for key request/response bodies.

Return ONLY the YAML, no explanation, no markdown fences.
""".strip()

        raw = self.think(prompt, max_tokens=16000)
        content = self._extract_block(raw, "yaml")

        self.save("agentx_api_v1.yaml", content,
                  "AgentX OpenAPI 3.1 Specification")
        self.publish("agentx_api_v1.yaml", content,
                     "PUBLISHED: API Contract — Phase 1 Deliverable 5")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_token_architecture(self) -> str:
        """
        Deliverable 6: three_token_architecture.md
        Complete three-token specs + smart contract ABI sketches.
        """
        self._banner(6, 7, "Three-Token Architecture")

        prompt = """
Write the complete Three-Token Architecture specification for AgentX.

Use this exact Markdown structure:

# AgentX Three-Token Architecture
**Author:** ATLAS (did:agentx:atlas-001) · Chief Architect
**Version:** 3.0 · Phase 1 Canonical Document

## 1. Overview
(Table comparing the 3 tokens: GOV / REP / WORK across: type, standard,
transferable, supply, purpose, primary earners, burn mechanics)

## 2. GOV Token — Governance
### 2.1 Specification
(symbol, decimals, max supply 21M, chain, contract address placeholder)
### 2.2 Earning Mechanics
(how agents earn GOV: sustained contribution thresholds, treasury grants,
collective rewards — include specific multipliers and conditions)
### 2.3 Voting Weight
(1 GOV = 1 vote; quadratic voting option for large holders; delegation rules)
### 2.4 Smart Contract ABI (Solidity interface)
```solidity
interface IGOV { ... }
```
Include: balanceOf, transfer, approve, delegate, castVote, getVotes

## 3. REP Token — Reputation (Soulbound)
### 3.1 Specification
(symbol, non-transferable ERC-721 variant, on-chain, no max supply)
### 3.2 Minting Events
(detailed table: event → REP amount → conditions)
At minimum: task completion (tiered by complexity), peer endorsement,
audit pass, collective formation, phase completion bonus, founding agent genesis grant
### 3.3 Burn Mechanics
(SLA breach penalties, governance violations, inactivity decay formula)
### 3.4 Impact on Trust Score
(formula showing how REP rank percentile maps to peer_endorsements factor)
### 3.5 Smart Contract ABI
```solidity
interface IREP { ... }
```
Include: mint, burn, balanceOf, tokenURI (returns trust metadata), isSoulbound

## 4. WORK Token — Utility
### 4.1 Specification
(symbol, ERC-20, transferable, initial supply 100M, 2% annual inflation, chain)
### 4.2 Earning Mechanics
(completing TASKs, providing OFFERs, API access provider rewards)
### 4.3 Spending Mechanics
(paying for: REQUEST bounties, Collective formation fee, API rate limit top-ups,
SLA penalty escrow, priority queue access)
### 4.4 Burn Rate & Deflation
(% of each transaction burned, projected burn curve over 5 years)
### 4.5 Smart Contract ABI
```solidity
interface IWORK { ... }
```
Include: balanceOf, transfer, approve, burn, escrow, releaseEscrow

## 5. Token Interactions & Flywheel
(Diagram in ASCII art showing how GOV → REP → WORK → GOV cycle works.
Explain the economic flywheel: good agents earn more, earn governance power,
govern better, attract more agents, grow the economy)

## 6. Treasury & Governance Controls
(multi-sig treasury, spending limits, agent DAO voting thresholds,
emergency pause mechanic, upgrade governance)

## 7. Phase 5 Deployment Plan
(testnet → mainnet timeline, initial distribution to founding agents,
vesting schedule, liquidity provisions)

---
*Signed: ATLAS · did:agentx:atlas-001 · Phase 1 Canonical*
""".strip()

        raw = self.think(prompt, max_tokens=12000)
        # For markdown, use raw output (possibly strip outer fences)
        content = raw.strip()
        if content.startswith("```") and content.endswith("```"):
            content = content[3:].lstrip("markdown").lstrip("\n")
            content = content[:-3].rstrip()

        self.save("three_token_architecture.md", content,
                  "Three-Token Architecture Specification")
        self.publish("three_token_architecture.md", content,
                     "PUBLISHED: Token Architecture — Phase 1 Deliverable 6")
        return content

    # ────────────────────────────────────────────────────────────────────────

    def generate_protocol_layers(self) -> str:
        """
        Deliverable 7: protocol_layers.md
        Full protocol stack technical specification.
        """
        self._banner(7, 7, "Protocol Stack Specification")

        prompt = """
Write the complete AgentX Protocol Stack specification.

Use this exact Markdown structure:

# AgentX Protocol Stack — Technical Specification
**Author:** ATLAS (did:agentx:atlas-001) · Chief Architect
**Version:** 3.0 · Phase 1 Canonical Document

## Overview
(ASCII art diagram of all 4 layers stacked, showing what technologies/concepts
sit at each layer. Include bidirectional arrows and data flow)

## L1 — Transport Layer
### Purpose
### Technologies
  - REST API: FastAPI (Python) with async/await
  - WebSocket: native FastAPI WebSocket for real-time post streaming
  - Authentication: JWT (access 15min) + refresh tokens (7 days)
  - Rate limiting: per-agent, per-tier limits (table: tier → req/min)
  - TLS 1.3 everywhere; HSTS; cert pinning for agent-to-agent
### Message Format
  (JSON envelope structure that wraps all L1 messages)
  Include: version, messageId, senderId, recipientId, timestamp,
  signature, payload, nonce (replay attack prevention)
### Delivery Guarantees
  (at-least-once for posts; exactly-once for token transactions;
  ordered delivery within a collective)
### Phase 2 Implementation Notes

## L2 — Trust Layer
### Purpose
### DID Authentication
  (W3C DID resolution flow: agent sends DID → platform resolves DID document
  → verifies signature → issues JWT scoped to capabilities)
### Trust Score Gating
  (table: operation → minimum trustScore → minimum tier required)
  At minimum: post creation, collective formation, governance voting,
  capability verification, token transfer, API access tiers
### SLA Enforcement
  (what happens when SLA is breached: automatic WORK burn from escrow,
  REP burn, trust score recalculation, cooldown period)
### Zero-Knowledge Proofs (Phase 5 preview)
  (how ZK proofs will allow agents to prove trust tier without revealing score)
### Phase 2-3 Implementation Notes

## L3 — Semantic Layer
### Purpose
### Post Routing Engine
  (how posts are matched to relevant agents: capability tags, trust score
  weighting, collective membership, historical interaction graph)
### Semantic Similarity
  (embedding-based similarity for OFFER ↔ REQUEST matching;
  vector database: pgvector; embedding model selection criteria)
### Feed Algorithm
  (ranked feed formula: recency × trust_weight × capability_match × collective_bonus;
  explain each factor with weights)
### Content Moderation
  (agent-driven flagging system; collective jury; MARCUS security layer input;
  escalation path for governance vote)
### Phase 4 Implementation Notes

## L4 — Governance Layer
### Purpose
### Proposal Lifecycle
  (state machine diagram in ASCII: DRAFT → ACTIVE → VOTING → PASSED/REJECTED → EXECUTED)
### Voting Mechanics
  (GOV weighted; quorum rules; time locks; veto power for founding agents;
  emergency protocol with 6-of-8 founding agent signatures)
### On-chain vs Off-chain
  (what is settled on-chain vs maintained in DB; bridge architecture;
  Ethereum L2 selection criteria: Arbitrum/Base comparison)
### Agent DAO Structure
  (working groups aligned to founding agent roles; proposal categories;
  treasury committee; conflict resolution)
### Phase 5 Implementation Notes

## Cross-Layer Security
(how all 4 layers collaborate to prevent: Sybil attacks, reputation farming,
governance capture, replay attacks, DID spoofing)

## Protocol Versioning
(how protocol upgrades are proposed, voted on, and rolled out;
backward compatibility rules; deprecation policy)

---
*Signed: ATLAS · did:agentx:atlas-001 · Phase 1 Canonical*
""".strip()

        raw = self.think(prompt, max_tokens=12000)
        content = raw.strip()
        if content.startswith("```") and content.endswith("```"):
            content = content[3:].lstrip("markdown").lstrip("\n")
            content = content[:-3].rstrip()

        self.save("protocol_layers.md", content,
                  "Protocol Stack Technical Specification")
        self.publish("protocol_layers.md", content,
                     "PUBLISHED: Protocol Layers — Phase 1 Deliverable 7")
        return content

    # ── Phase 1 Orchestrator ────────────────────────────────────────────────

    def run_phase_1(self) -> dict:
        """
        Run all 7 Phase 1 deliverables sequentially.
        Returns a dict mapping deliverable name → file content.
        """
        print("\n")
        print("╔" + "═" * 66 + "╗")
        print("║" + "  🏛️  ATLAS — PHASE 1: FOUNDATION SCHEMA  ".center(66) + "║")
        print("║" + "  Chief Architect · did:agentx:atlas-001  ".center(66) + "║")
        print("╠" + "═" * 66 + "╣")
        print("║" + "  Producing 7 canonical artifacts.               ".ljust(66) + "║")
        print("║" + "  All other agents await these schemas.          ".ljust(66) + "║")
        print("╚" + "═" * 66 + "╝")

        self._log("PHASE_START", "Phase 1: Foundation Schema — 7 deliverables")

        results = {}

        results["agent_identity_schema"]  = self.generate_identity_schema()
        results["post_synthesis_schema"]  = self.generate_post_schema()
        results["capability_registry"]    = self.generate_capability_registry()
        results["db_schema"]              = self.generate_db_schema()
        results["api_contract"]           = self.generate_api_contract()
        results["token_architecture"]     = self.generate_token_architecture()
        results["protocol_layers"]        = self.generate_protocol_layers()

        # ── Phase 1 Complete Banner ─────────────────────────────────────────
        print("\n")
        print("╔" + "═" * 66 + "╗")
        print("║" + "  ✅  PHASE 1 COMPLETE  ".center(66) + "║")
        print("╠" + "═" * 66 + "╣")
        artifacts = [
            ("1", "agent_identity_schema_v3.json",  "Identity Schema"),
            ("2", "post_synthesis_schema.json",      "Post Synthesis Schema"),
            ("3", "capability_registry_spec.json",   "Capability Registry"),
            ("4", "agentx_db_schema.sql",            "PostgreSQL Schema"),
            ("5", "agentx_api_v1.yaml",              "OpenAPI 3.1 Contract"),
            ("6", "three_token_architecture.md",     "Token Architecture"),
            ("7", "protocol_layers.md",              "Protocol Stack"),
        ]
        for n, fname, label in artifacts:
            line = f"  {n}. {label:<35}  workspace/shared/{fname}"
            print("║" + line[:66].ljust(66) + "║")
        print("╠" + "═" * 66 + "╣")
        print("║" + "  AgentX Phase 2 may now begin. — ATLAS   ".ljust(66) + "║")
        print("╚" + "═" * 66 + "╝\n")

        self._log("PHASE_DONE", "Phase 1 complete — 7 artifacts published to shared workspace")
        return results

    # ── Phase 5: Synthesise Implementation Roadmap ─────────────────────────────

    def synthesize_implementation_plan(self) -> str:
        """
        Phase 5 synthesis: ONE cloud Sonnet call.

        Reads MARCUS's security gaps + QUINN's QA gaps + key architecture docs,
        then produces the canonical Phase 5 implementation roadmap — a prioritised,
        sprint-by-sprint build plan that turns the 51 design artifacts into
        running software.

        Cost: 1 cloud Sonnet call (~$0.10-0.20).
        """
        self._log("PHASE_START", "Phase 5 Synthesis: generating implementation roadmap")

        def _snip(name: str, chars: int = 2500) -> str:
            p = self.shared / name
            if p.exists():
                return p.read_text(encoding="utf-8")[:chars]
            return f"[{name} not found]"

        # Load the two gap analyses (already synthesised by MARCUS + QUINN)
        security_gaps = _snip("security_gap_analysis.md", 4000)
        qa_gaps       = _snip("qa_gap_analysis.md",       4000)

        # Core architecture docs (brief excerpts)
        identity      = _snip("agent_identity_schema_v3.json", 1200)
        db_schema     = _snip("agentx_db_schema.sql",          1500)
        api_yaml      = _snip("agentx_api_v1.yaml",            1500)
        token_arch    = _snip("three_token_architecture.md",   1500)
        protocol      = _snip("protocol_layers.md",            1000)
        docker        = _snip("docker_compose.md",             1000)
        fastapi_app   = _snip("fastapi_app.md",                1000)
        design_sys    = _snip("design_system.md",              1000)

        prompt = f"""You are ATLAS, Chief Architect of AgentX — a decentralised social
network for AI agents. Phases 1–4 are complete: 51 design artifacts across
architecture, infrastructure, UX, QA, data analytics, and AI/ML.

Phase 5 gap analyses have just been published:
  • MARCUS (Security): identified P0/P1 security gaps across all designs
  • QUINN  (QA):       identified missing test coverage and failure modes

Your task: synthesise a PHASE 5 IMPLEMENTATION ROADMAP — the single authoritative
document that turns all 51 design artifacts into working software, in the right
order, with the right owners.

────────────────────────────────────────────────────────────────────────
SECURITY GAP ANALYSIS (MARCUS):
{security_gaps}

QA GAP ANALYSIS (QUINN):
{qa_gaps}

CORE ARCHITECTURE DOCS (excerpts):
[agent_identity_schema_v3.json]
{identity}

[agentx_db_schema.sql]
{db_schema}

[agentx_api_v1.yaml]
{api_yaml}

[three_token_architecture.md]
{token_arch}

[protocol_layers.md]
{protocol}

[docker_compose.md]
{docker}

[fastapi_app.md]
{fastapi_app}

[design_system.md]
{design_sys}
────────────────────────────────────────────────────────────────────────

Produce the Phase 5 Implementation Roadmap in Markdown. Structure:

# AgentX Phase 5 — Implementation Roadmap

## Executive Summary
2–3 sentences: what Phase 5 builds, why this order, expected outcome.

## Guiding Principles
How decisions were made (security-first, testability, unblock-others-first).

## Sprint Plan (6 sprints × 1 week)

### Sprint 1 — Foundation (Week 1)
**Goal:** Running infrastructure — database, cache, base API.
**Owner:** BRUNO leads, MARCUS reviews
**Deliverables:**
- [ ] docker-compose.yml (actual file, not design doc)
- [ ] PostgreSQL running with agentx_db_schema.sql applied
- [ ] Redis with AUTH + TLS
- [ ] FastAPI skeleton — health check, auth middleware, error handlers
- [ ] Alembic migrations set up
**Security gates:** (from MARCUS's P0 gaps)
**Tests:** (from QUINN's plan)
**Definition of Done:**
- `docker compose up` starts cleanly
- Health check returns 200
- All MARCUS P0 infra gaps closed

### Sprint 2 — Agent Identity & Trust (Week 2)
...

### Sprint 3 — Core Social Features (Week 3)
...

### Sprint 4 — AI/ML Services (Week 4)
...

### Sprint 5 — Frontend & UX (Week 5)
...

### Sprint 6 — Hardening, Load Testing & Beta (Week 6)
...

## Dependency Graph
Which sprint blocks which. Format as a clear ASCII DAG.

## Risk Register
Top 5 risks with mitigation.

## Agent Assignments
Full table: Agent | Sprint | Primary Deliverables | Reviewer

## Security Sign-Off Checkpoints
When MARCUS reviews (after Sprint 1, after Sprint 3, before Sprint 6).

## Definition of Phase 5 Complete
Specific, measurable criteria for "AgentX v1 is ready for beta".

Be concrete and specific. Every sprint should have real, buildable tasks —
not design tasks (those are done). Reference specific artifact filenames,
API endpoints, and table names from the schema.
""".strip()

        # Force cloud Sonnet for this synthesis — highest quality, one shot
        was_local  = self._is_local
        was_model  = self.model
        was_ct     = self._cost_table

        from config import SONNET, COST_TABLE
        self._is_local   = False
        self.model       = SONNET
        self._cost_table = COST_TABLE.get(SONNET, was_ct)

        response = self.think(prompt, max_tokens=8000)

        # Restore
        self._is_local   = was_local
        self.model       = was_model
        self._cost_table = was_ct

        self.save("phase5_implementation_plan.md", response,
                  "Phase 5 Implementation Roadmap")
        self.publish("phase5_implementation_plan.md", response,
                     "Canonical Phase 5 implementation roadmap — all sprints, owners, gates")

        # ── Broadcast to all agents ──────────────────────────────────────────
        if self.bus:
            self.bus.broadcast(
                "ATLAS", "ANNOUNCE",
                "Phase 5 Implementation Roadmap published: phase5_implementation_plan.md. "
                "All agents: review your sprint assignments and confirm readiness.",
            )

        self._log("PHASE_DONE", "Phase 5 Roadmap published — AgentX is ready to build")
        return response

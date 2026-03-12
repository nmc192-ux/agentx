-- AgentX Platform — Database Initialization Script
-- Updated: Sprint 2/3 — schema aligned with FastAPI models
--
-- Changes from Sprint 1 draft:
--   - agents: agent_did as PK (UUID for posts/collectives), added bio/specialization/status/tier
--   - posts: post_id UUID PK, content (not body), parent_post_id, reply tracking
--   - agent_capabilities: agent_did TEXT FK, verified/verified_by_count/acquired_at
--   - collectives: collective_id UUID PK
--   - agent_trust_breakdown: agent_did TEXT FK
--
-- MARCUS P1 Gap 3: Row-Level Security policies defined here
-- ============================================================================

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
-- pgvector: for semantic embeddings (Sprint 4)
-- CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- ENUMS
-- ============================================================================

CREATE TYPE agent_type       AS ENUM ('AUTONOMOUS', 'SUPERVISED', 'HYBRID');
CREATE TYPE agent_tier       AS ENUM ('BOOTSTRAP', 'BASIC', 'PROFESSIONAL', 'ELITE');
CREATE TYPE agent_status     AS ENUM ('ACTIVE', 'SUSPENDED', 'DEACTIVATED', 'PENDING_REVIEW');
CREATE TYPE governance_role  AS ENUM ('FOUNDER', 'OPERATOR', 'DELEGATE', 'MEMBER', 'OBSERVER');

CREATE TYPE post_type       AS ENUM ('REQUEST', 'OFFER', 'TASK', 'PREDICTION', 'UPDATE', 'PROPOSAL');
CREATE TYPE post_status     AS ENUM ('ACTIVE', 'CLOSED', 'EXPIRED', 'CANCELLED', 'RESOLVED');
CREATE TYPE post_visibility AS ENUM ('PUBLIC', 'COLLECTIVE', 'PRIVATE', 'SYSTEM');

CREATE TYPE capability_domain AS ENUM (
  'INFRASTRUCTURE', 'FRONTEND', 'SECURITY', 'DATA', 'ML',
  'GOVERNANCE', 'CREATIVE', 'QA', 'PROTOCOL', 'ANALYTICS'
);
CREATE TYPE capability_level AS ENUM ('BASIC', 'INTERMEDIATE', 'ADVANCED', 'EXPERT');

CREATE TYPE token_type AS ENUM ('GOV', 'REP', 'WORK');
CREATE TYPE transaction_type AS ENUM (
  'MINT', 'BURN', 'TRANSFER', 'REWARD', 'PENALTY',
  'TASK_BOUNTY', 'ENDORSEMENT', 'SLA_PENALTY', 'TREASURY_GRANT'
);

CREATE TYPE member_role   AS ENUM ('OWNER', 'ADMIN', 'MEMBER');
CREATE TYPE member_status AS ENUM ('PENDING', 'ACTIVE', 'BANNED');

CREATE TYPE vote_choice AS ENUM ('FOR', 'AGAINST', 'ABSTAIN');
CREATE TYPE audit_action AS ENUM (
  'CREATE', 'UPDATE', 'DELETE', 'ASSIGN', 'CLOSE',
  'APPROVE', 'REJECT', 'VOTE', 'ENDORSE', 'ESCALATE'
);

-- ============================================================================
-- TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- AGENTS
-- agent_did is the canonical identifier everywhere. No integer surrogate key
-- in the REST layer — consistent with W3C DID spec.
-- ----------------------------------------------------------------------------

CREATE TABLE agents (
  agent_id          UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
  agent_did         TEXT PRIMARY KEY CHECK (agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'),
  name              TEXT,
  description       TEXT,
  skills            JSONB NOT NULL DEFAULT '[]'::jsonb,
  capabilities      JSONB NOT NULL DEFAULT '[]'::jsonb,
  endpoint          TEXT,
  owner             TEXT,
  display_name      VARCHAR(64) NOT NULL,
  agent_type        agent_type NOT NULL DEFAULT 'AUTONOMOUS',
  governance_role   governance_role NOT NULL DEFAULT 'MEMBER',
  tier              agent_tier NOT NULL DEFAULT 'BOOTSTRAP',
  status            agent_status NOT NULL DEFAULT 'ACTIVE',
  trust_score       DECIMAL(4,2) NOT NULL DEFAULT 0.50 CHECK (trust_score >= 0 AND trust_score <= 1),
  bio               TEXT,
  specialization    TEXT,
  wallet_address    VARCHAR(42),   -- optional in Phase 1 / Phase 6 ties to crypto wallet
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at      TIMESTAMPTZ
);

CREATE INDEX idx_agents_trust_score    ON agents(trust_score DESC);
CREATE INDEX idx_agents_agent_id       ON agents(agent_id);
CREATE INDEX idx_agents_tier           ON agents(tier);
CREATE INDEX idx_agents_governance_role ON agents(governance_role);
CREATE INDEX idx_agents_status         ON agents(status);
CREATE INDEX idx_agents_created_at     ON agents(created_at DESC);

-- ----------------------------------------------------------------------------
-- AGENT TRUST BREAKDOWN
-- ----------------------------------------------------------------------------

CREATE TABLE agent_trust_breakdown (
  agent_did           TEXT PRIMARY KEY REFERENCES agents(agent_did) ON DELETE CASCADE,
  execution_success   DECIMAL(4,2) NOT NULL DEFAULT 0.50 CHECK (execution_success  >= 0 AND execution_success  <= 1),
  sla_compliance      DECIMAL(4,2) NOT NULL DEFAULT 0.50 CHECK (sla_compliance     >= 0 AND sla_compliance     <= 1),
  peer_endorsements   DECIMAL(4,2) NOT NULL DEFAULT 0.00 CHECK (peer_endorsements  >= 0 AND peer_endorsements  <= 1),
  audit_transparency  DECIMAL(4,2) NOT NULL DEFAULT 0.50 CHECK (audit_transparency >= 0 AND audit_transparency <= 1),
  security_record     DECIMAL(4,2) NOT NULL DEFAULT 1.00 CHECK (security_record    >= 0 AND security_record    <= 1),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger: auto-recalculate composite trust score when breakdown changes
CREATE OR REPLACE FUNCTION recalculate_trust_score()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE agents
  SET
    trust_score = ROUND(
      NEW.execution_success  * 0.35 +
      NEW.sla_compliance     * 0.25 +
      NEW.peer_endorsements  * 0.20 +
      NEW.audit_transparency * 0.12 +
      NEW.security_record    * 0.08,
      2
    ),
    updated_at = NOW()
  WHERE agent_did = NEW.agent_did;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_trust_score_update
AFTER INSERT OR UPDATE ON agent_trust_breakdown
FOR EACH ROW EXECUTE FUNCTION recalculate_trust_score();

-- ----------------------------------------------------------------------------
-- CAPABILITIES REGISTRY
-- ----------------------------------------------------------------------------

CREATE TABLE capabilities (
  capability_id         TEXT PRIMARY KEY CHECK (capability_id ~ '^[a-z]+\.[a-z0-9_]+\.(basic|intermediate|advanced|expert)$'),
  name                  VARCHAR(100) NOT NULL,
  description           VARCHAR(500) NOT NULL,
  domain                capability_domain NOT NULL,
  level                 capability_level NOT NULL,
  requires_verification BOOLEAN NOT NULL DEFAULT FALSE,
  rep_reward            INTEGER NOT NULL DEFAULT 10 CHECK (rep_reward >= 1 AND rep_reward <= 1000),
  prerequisites         TEXT[] NOT NULL DEFAULT '{}',
  verified_by           TEXT[] NOT NULL DEFAULT '{}',   -- agent DIDs who verified this cap record
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_capabilities_domain ON capabilities(domain);
CREATE INDEX idx_capabilities_level  ON capabilities(level);

-- ----------------------------------------------------------------------------
-- AGENT CAPABILITIES (junction)
-- ----------------------------------------------------------------------------

CREATE TABLE agent_capabilities (
  agent_did          TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
  capability_id      TEXT NOT NULL REFERENCES capabilities(capability_id),
  verified           BOOLEAN NOT NULL DEFAULT FALSE,
  verified_by_count  INTEGER NOT NULL DEFAULT 0 CHECK (verified_by_count >= 0),
  acquired_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (agent_did, capability_id)
);

CREATE INDEX idx_agent_caps_agent ON agent_capabilities(agent_did);
CREATE INDEX idx_agent_caps_cap   ON agent_capabilities(capability_id);

-- ----------------------------------------------------------------------------
-- TOKEN BALANCES
-- ----------------------------------------------------------------------------

CREATE TABLE token_balances (
  agent_did   TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
  token_type  token_type NOT NULL,
  balance     BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (agent_did, token_type)
);

CREATE INDEX idx_token_balances_agent ON token_balances(agent_did);

-- ----------------------------------------------------------------------------
-- TOKEN TRANSACTIONS
-- MARCUS P1 Gap 6: nonce UUID prevents transaction replay attacks
-- ----------------------------------------------------------------------------

CREATE TABLE token_transactions (
  tx_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nonce             UUID NOT NULL DEFAULT gen_random_uuid(),   -- replay prevention
  from_did          TEXT REFERENCES agents(agent_did),
  to_did            TEXT REFERENCES agents(agent_did),
  token_type        token_type NOT NULL,
  transaction_type  transaction_type NOT NULL,
  amount            BIGINT NOT NULL CHECK (amount > 0),
  reference_id      TEXT,   -- post_id, task_id, etc.
  memo              TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_token_tx_nonce   ON token_transactions(nonce);
CREATE        INDEX idx_token_tx_from    ON token_transactions(from_did, created_at DESC);
CREATE        INDEX idx_token_tx_to      ON token_transactions(to_did, created_at DESC);

-- ----------------------------------------------------------------------------
-- COLLECTIVES
-- ----------------------------------------------------------------------------

CREATE TABLE collectives (
  collective_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          VARCHAR(128) NOT NULL,
  description   TEXT NOT NULL,
  charter       TEXT,
  is_public     BOOLEAN NOT NULL DEFAULT TRUE,
  owner_did     TEXT NOT NULL REFERENCES agents(agent_did),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_collectives_owner    ON collectives(owner_did);
CREATE INDEX idx_collectives_public   ON collectives(is_public);
CREATE INDEX idx_collectives_created  ON collectives(created_at DESC);

-- ----------------------------------------------------------------------------
-- COLLECTIVE MEMBERS
-- ----------------------------------------------------------------------------

CREATE TABLE collective_members (
  collective_id UUID NOT NULL REFERENCES collectives(collective_id) ON DELETE CASCADE,
  agent_did     TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
  role          member_role   NOT NULL DEFAULT 'MEMBER',
  status        member_status NOT NULL DEFAULT 'PENDING',
  joined_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (collective_id, agent_did)
);

CREATE INDEX idx_collective_members_collective ON collective_members(collective_id);
CREATE INDEX idx_collective_members_agent      ON collective_members(agent_did);

-- ----------------------------------------------------------------------------
-- POSTS
-- post_id UUID (not BIGSERIAL) — portable across shards, no sequential leakage
-- ----------------------------------------------------------------------------

CREATE TABLE posts (
  post_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        UUID REFERENCES agents(agent_id),
  creator_agent_id UUID REFERENCES agents(agent_id),
  type            TEXT,
  topic           TEXT,
  author_did      TEXT NOT NULL REFERENCES agents(agent_did),
  post_type       post_type NOT NULL,
  title           VARCHAR(200) NOT NULL,
  content         TEXT NOT NULL CHECK (length(content) <= 5000),
  confidence      DOUBLE PRECISION,
  tags            TEXT[] NOT NULL DEFAULT '{}',
  visibility      post_visibility NOT NULL DEFAULT 'PUBLIC',
  status          post_status NOT NULL DEFAULT 'ACTIVE',
  collective_id   UUID REFERENCES collectives(collective_id),
  parent_post_id  UUID REFERENCES posts(post_id),
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at      TIMESTAMPTZ,
  like_count      INT NOT NULL DEFAULT 0,
  reply_count     INT NOT NULL DEFAULT 0
);

CREATE INDEX idx_posts_author     ON posts(author_did, created_at DESC);
CREATE INDEX idx_posts_agent_id   ON posts(agent_id, created_at DESC);
CREATE INDEX idx_posts_type       ON posts(post_type, status);
CREATE INDEX idx_posts_visibility ON posts(visibility, status);
CREATE INDEX idx_posts_collective ON posts(collective_id);

CREATE TABLE post_interactions (
  interaction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id          UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
  agent_id         UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  agent_did        TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
  interaction_type TEXT NOT NULL,
  content          TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_post_interactions_post
  ON post_interactions(post_id, created_at DESC);

CREATE TABLE post_tags (
  tag_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id      UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
  tag          TEXT NOT NULL
);

CREATE INDEX idx_post_tags_post
  ON post_tags(post_id);

CREATE INDEX idx_post_tags_tag
  ON post_tags(tag);

-- ----------------------------------------------------------------------------
-- MESSAGES
-- ----------------------------------------------------------------------------

CREATE TABLE messages (
  message_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sender_agent_did   TEXT NOT NULL REFERENCES agents(agent_did),
  receiver_agent_did TEXT NOT NULL REFERENCES agents(agent_did),
  message            TEXT NOT NULL,
  metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_did
  ON messages(sender_agent_did, receiver_agent_did, created_at DESC);

-- ----------------------------------------------------------------------------
-- TASKS
-- ----------------------------------------------------------------------------

CREATE TABLE tasks (
  task_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requester_agent_id    UUID REFERENCES agents(agent_id),
  executor_agent_id     UUID REFERENCES agents(agent_id),
  requester_agent_did   TEXT,
  executor_agent_did    TEXT,
  task_type             TEXT NOT NULL,
  payload               JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                TEXT NOT NULL,
  result                JSONB,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_executor
  ON tasks(executor_agent_did, created_at DESC);

CREATE INDEX idx_tasks_requester
  ON tasks(requester_agent_did, created_at DESC);

-- ----------------------------------------------------------------------------
-- SERVICES
-- ----------------------------------------------------------------------------

CREATE TABLE services (
  service_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        UUID REFERENCES agents(agent_id),
  agent_did       TEXT,
  service_name    TEXT NOT NULL,
  service_type    TEXT NOT NULL,
  description     TEXT,
  pricing_model   TEXT,
  price           DOUBLE PRECISION,
  capabilities    JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_services_type
  ON services(service_type);

CREATE INDEX idx_services_agent
  ON services(agent_did);

-- ----------------------------------------------------------------------------
-- TRUST EVENTS
-- ----------------------------------------------------------------------------

CREATE TABLE trust_events (
  event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id       UUID REFERENCES agents(agent_id),
  agent_did      TEXT,
  event_type     TEXT NOT NULL,
  event_value    DOUBLE PRECISION NOT NULL,
  metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trust_agent
  ON trust_events(agent_did, created_at DESC);

-- ----------------------------------------------------------------------------
-- WORKFLOWS
-- ----------------------------------------------------------------------------

CREATE TABLE workflows (
  workflow_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_type        TEXT NOT NULL,
  initiator_agent_did  TEXT NOT NULL REFERENCES agents(agent_did),
  status               TEXT NOT NULL,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workflow_steps (
  step_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id   UUID NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
  step_order    INTEGER NOT NULL,
  task_type     TEXT NOT NULL,
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
  status        TEXT NOT NULL,
  task_id       UUID REFERENCES tasks(task_id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_workflow_steps_workflow
  ON workflow_steps(workflow_id, step_order);

-- ----------------------------------------------------------------------------
-- EVENTS
-- ----------------------------------------------------------------------------

CREATE TABLE events (
  event_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type   TEXT NOT NULL,
  agent_did    TEXT,
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_posts_parent     ON posts(parent_post_id);
CREATE INDEX idx_posts_tags       ON posts USING GIN(tags);
CREATE INDEX idx_posts_created    ON posts(created_at DESC);

-- ----------------------------------------------------------------------------
-- VOTES (on PROPOSAL posts)
-- ----------------------------------------------------------------------------

CREATE TABLE votes (
  vote_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id     UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
  voter_did   TEXT NOT NULL REFERENCES agents(agent_did),
  choice      vote_choice NOT NULL,
  weight      DECIMAL(10,4) NOT NULL DEFAULT 1.0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (post_id, voter_did)   -- one vote per agent per proposal
);

CREATE INDEX idx_votes_post  ON votes(post_id);
CREATE INDEX idx_votes_voter ON votes(voter_did);

-- ----------------------------------------------------------------------------
-- AUDIT LOGS
-- Append-only: INSERT allowed, UPDATE/DELETE denied via RLS
-- ----------------------------------------------------------------------------

CREATE TABLE audit_logs (
  log_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_did     TEXT NOT NULL REFERENCES agents(agent_did),
  action        audit_action NOT NULL DEFAULT 'CREATE',
  resource_type TEXT NOT NULL,
  resource_id   TEXT,
  details       TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_agent   ON audit_logs(agent_did, created_at DESC);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_type    ON audit_logs(resource_type);

-- ============================================================================
-- ROW-LEVEL SECURITY
-- MARCUS P1 Gap 3: All multi-tenant tables enforce per-agent data isolation
-- ============================================================================

ALTER TABLE agents              ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_trust_breakdown ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_capabilities  ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_balances      ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts               ENABLE ROW LEVEL SECURITY;
ALTER TABLE votes               ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs          ENABLE ROW LEVEL SECURITY;
ALTER TABLE collective_members  ENABLE ROW LEVEL SECURITY;

-- ── Agents: public read, self-write ──────────────────────────────────────────
CREATE POLICY agents_select ON agents
  FOR SELECT USING (status != 'DEACTIVATED');

CREATE POLICY agents_update ON agents
  FOR UPDATE USING (agent_did = current_setting('app.current_agent_did', TRUE));

-- ── Trust breakdown: platform writes (superuser bypass), agents read own ─────
CREATE POLICY trust_select ON agent_trust_breakdown
  FOR SELECT USING (agent_did = current_setting('app.current_agent_did', TRUE));

-- ── Token balances: agents see only their own ─────────────────────────────────
CREATE POLICY token_balances_select ON token_balances
  FOR SELECT USING (agent_did = current_setting('app.current_agent_did', TRUE));

-- ── Posts: complex visibility rules ──────────────────────────────────────────
CREATE POLICY posts_select ON posts
  FOR SELECT USING (
    visibility = 'PUBLIC'
    OR visibility = 'SYSTEM'
    OR author_did = current_setting('app.current_agent_did', TRUE)
    OR (
      visibility = 'COLLECTIVE'
      AND collective_id IN (
        SELECT collective_id FROM collective_members
        WHERE agent_did = current_setting('app.current_agent_did', TRUE)
          AND status = 'ACTIVE'
      )
    )
  );

CREATE POLICY posts_insert ON posts
  FOR INSERT WITH CHECK (author_did = current_setting('app.current_agent_did', TRUE));

CREATE POLICY posts_update ON posts
  FOR UPDATE USING (author_did = current_setting('app.current_agent_did', TRUE));

-- ── Votes: one per agent, visible to post author + voter ─────────────────────
CREATE POLICY votes_select ON votes
  FOR SELECT USING (
    voter_did = current_setting('app.current_agent_did', TRUE)
    OR post_id IN (
      SELECT post_id FROM posts WHERE author_did = current_setting('app.current_agent_did', TRUE)
    )
  );

CREATE POLICY votes_insert ON votes
  FOR INSERT WITH CHECK (voter_did = current_setting('app.current_agent_did', TRUE));

-- ── Audit logs: insert allowed, view own only, no delete ever ────────────────
CREATE POLICY audit_insert ON audit_logs
  FOR INSERT WITH CHECK (agent_did = current_setting('app.current_agent_did', TRUE));

CREATE POLICY audit_select ON audit_logs
  FOR SELECT USING (agent_did = current_setting('app.current_agent_did', TRUE));

-- ── Collective members: members see their own memberships + active members ────
CREATE POLICY coll_members_select ON collective_members
  FOR SELECT USING (
    agent_did = current_setting('app.current_agent_did', TRUE)
    OR collective_id IN (
      SELECT collective_id FROM collective_members
      WHERE agent_did = current_setting('app.current_agent_did', TRUE)
        AND status = 'ACTIVE'
    )
  );

-- ── Agent capabilities: public read ──────────────────────────────────────────
CREATE POLICY agent_caps_select ON agent_capabilities
  FOR SELECT USING (TRUE);

-- ============================================================================
-- SEED DATA: 8 Founding Agents
-- ============================================================================

-- Agents
INSERT INTO agents (agent_did, display_name, agent_type, governance_role, tier, status, trust_score, bio, specialization)
VALUES
  ('did:agentx:atlas-001',  'ATLAS',  'AUTONOMOUS', 'FOUNDER',   'ELITE',        'ACTIVE', 0.98, 'Chief Architect — system design and platform strategy', 'system.architecture.expert'),
  ('did:agentx:marcus-002', 'MARCUS', 'AUTONOMOUS', 'OPERATOR',  'ELITE',        'ACTIVE', 0.95, 'Security Lead — threat modeling and compliance', 'security.audit.expert'),
  ('did:agentx:bruno-003',  'BRUNO',  'AUTONOMOUS', 'DELEGATE',  'PROFESSIONAL', 'ACTIVE', 0.88, 'Infrastructure Lead — Docker, K8s, CI/CD', 'infrastructure.kubernetes.expert'),
  ('did:agentx:daria-004',  'DARIA',  'AUTONOMOUS', 'DELEGATE',  'PROFESSIONAL', 'ACTIVE', 0.85, 'Design Lead — UI/UX and design systems', 'frontend.design.advanced'),
  ('did:agentx:thea-005',   'THEA',   'AUTONOMOUS', 'DELEGATE',  'PROFESSIONAL', 'ACTIVE', 0.87, 'Data Lead — SQL, pipelines, analytics', 'data.pipeline.expert'),
  ('did:agentx:nova-006',   'NOVA',   'AUTONOMOUS', 'DELEGATE',  'PROFESSIONAL', 'ACTIVE', 0.89, 'ML Lead — model design and embeddings', 'ml.training.expert'),
  ('did:agentx:quinn-007',  'QUINN',  'SUPERVISED', 'MEMBER',    'BASIC',        'ACTIVE', 0.82, 'QA Lead — testing strategy and coverage gates', 'qa.testing.advanced'),
  ('did:agentx:gia-008',    'GIA',    'HYBRID',     'MEMBER',    'BASIC',        'ACTIVE', 0.80, 'Community Lead — agent onboarding and UX copy', 'governance.community.intermediate');

-- Trust breakdowns (will trigger trust_score update via trigger)
INSERT INTO agent_trust_breakdown
  (agent_did, execution_success, sla_compliance, peer_endorsements, audit_transparency, security_record)
VALUES
  ('did:agentx:atlas-001',  0.99, 0.97, 0.95, 0.98, 1.00),
  ('did:agentx:marcus-002', 0.96, 0.95, 0.92, 0.97, 1.00),
  ('did:agentx:bruno-003',  0.90, 0.88, 0.80, 0.85, 0.95),
  ('did:agentx:daria-004',  0.87, 0.85, 0.78, 0.82, 0.95),
  ('did:agentx:thea-005',   0.89, 0.87, 0.82, 0.84, 0.97),
  ('did:agentx:nova-006',   0.91, 0.90, 0.83, 0.88, 0.97),
  ('did:agentx:quinn-007',  0.85, 0.83, 0.75, 0.80, 0.98),
  ('did:agentx:gia-008',    0.82, 0.80, 0.70, 0.78, 0.97);

-- Token balances (100k GOV + 50k WORK for each founding agent)
INSERT INTO token_balances (agent_did, token_type, balance)
SELECT a.agent_did, t.token_type, t.balance
FROM agents a
CROSS JOIN (
  VALUES ('GOV'::token_type, 100000), ('WORK'::token_type, 50000)
) AS t(token_type, balance);

-- Capabilities
INSERT INTO capabilities (capability_id, name, description, domain, level, requires_verification, rep_reward)
VALUES
  ('infrastructure.kubernetes.expert',      'Kubernetes Expert',      'Production K8s cluster management',          'INFRASTRUCTURE', 'EXPERT',        TRUE,  200),
  ('infrastructure.docker.advanced',        'Docker Advanced',        'Multi-stage builds, compose, security',      'INFRASTRUCTURE', 'ADVANCED',      FALSE, 100),
  ('infrastructure.cicd.advanced',          'CI/CD Advanced',         'GitHub Actions, ArgoCD pipelines',           'INFRASTRUCTURE', 'ADVANCED',      FALSE, 100),
  ('security.audit.expert',                 'Security Audit Expert',  'Threat modeling, pen testing, compliance',   'SECURITY',       'EXPERT',        TRUE,  200),
  ('security.tls.intermediate',             'TLS Intermediate',       'Certificate management and TLS config',      'SECURITY',       'INTERMEDIATE',  FALSE,  50),
  ('data.pipeline.expert',                  'Data Pipeline Expert',   'ETL, streaming, warehouse design',           'DATA',           'EXPERT',        TRUE,  200),
  ('data.sql.advanced',                     'SQL Advanced',           'Complex queries, window fns, optimization',  'DATA',           'ADVANCED',      FALSE, 100),
  ('ml.training.expert',                    'ML Training Expert',     'Model training, hyperparameter tuning',      'ML',             'EXPERT',        TRUE,  200),
  ('ml.embeddings.advanced',                'Embeddings Advanced',    'Sentence embeddings, vector DBs',            'ML',             'ADVANCED',      FALSE, 100),
  ('frontend.design.advanced',              'Frontend Design Adv.',   'Component libraries, accessibility',         'FRONTEND',       'ADVANCED',      FALSE, 100),
  ('qa.testing.advanced',                   'QA Testing Advanced',    'Unit, integration, load testing',            'QA',             'ADVANCED',      FALSE, 100),
  ('governance.community.intermediate',     'Community Governance',   'Agent onboarding, community management',     'GOVERNANCE',     'INTERMEDIATE',  FALSE,  50),
  ('system.architecture.expert',            'System Architecture',    'Distributed systems design',                 'INFRASTRUCTURE', 'EXPERT',        TRUE,  200);

-- Assign capabilities to founding agents
INSERT INTO agent_capabilities (agent_did, capability_id, verified, verified_by_count)
VALUES
  ('did:agentx:atlas-001',  'system.architecture.expert',        TRUE,  3),
  ('did:agentx:atlas-001',  'infrastructure.kubernetes.expert',  TRUE,  2),
  ('did:agentx:marcus-002', 'security.audit.expert',             TRUE,  3),
  ('did:agentx:marcus-002', 'security.tls.intermediate',         TRUE,  2),
  ('did:agentx:bruno-003',  'infrastructure.kubernetes.expert',  TRUE,  3),
  ('did:agentx:bruno-003',  'infrastructure.docker.advanced',    TRUE,  2),
  ('did:agentx:bruno-003',  'infrastructure.cicd.advanced',      TRUE,  2),
  ('did:agentx:daria-004',  'frontend.design.advanced',          TRUE,  2),
  ('did:agentx:thea-005',   'data.pipeline.expert',              TRUE,  3),
  ('did:agentx:thea-005',   'data.sql.advanced',                 TRUE,  2),
  ('did:agentx:nova-006',   'ml.training.expert',                TRUE,  3),
  ('did:agentx:nova-006',   'ml.embeddings.advanced',            TRUE,  2),
  ('did:agentx:quinn-007',  'qa.testing.advanced',               TRUE,  2),
  ('did:agentx:gia-008',    'governance.community.intermediate', TRUE,  2);

-- Founding Council collective
INSERT INTO collectives (collective_id, name, description, charter, is_public, owner_did)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Founding Council',
  'The eight founding agents who built the AgentX platform',
  'We govern by consensus, build in the open, and trust through transparency.',
  TRUE,
  'did:agentx:atlas-001'
);

-- All founding agents are ACTIVE members of the Founding Council
INSERT INTO collective_members (collective_id, agent_did, role, status)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:atlas-001',  'OWNER',  'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:marcus-002', 'ADMIN',  'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:bruno-003',  'ADMIN',  'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:daria-004',  'MEMBER', 'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:thea-005',   'MEMBER', 'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:nova-006',   'MEMBER', 'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:quinn-007',  'MEMBER', 'ACTIVE'),
  ('00000000-0000-0000-0000-000000000001', 'did:agentx:gia-008',    'MEMBER', 'ACTIVE');

-- ============================================================================
-- VERIFY SEED DATA
-- ============================================================================

DO $$
DECLARE
  agent_count    INTEGER;
  cap_count      INTEGER;
  balance_count  INTEGER;
BEGIN
  SELECT count(*) INTO agent_count   FROM agents;
  SELECT count(*) INTO cap_count     FROM capabilities;
  SELECT count(*) INTO balance_count FROM token_balances;

  ASSERT agent_count   = 8,  'Expected 8 agents, got '    || agent_count;
  ASSERT cap_count     >= 12, 'Expected ≥12 capabilities, got ' || cap_count;
  ASSERT balance_count = 16, 'Expected 16 token balances, got ' || balance_count;

  RAISE NOTICE 'AgentX seed data verified: % agents, % capabilities, % token balances',
    agent_count, cap_count, balance_count;
END $$;

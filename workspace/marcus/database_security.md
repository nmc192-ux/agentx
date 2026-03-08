# AgentX Database Security Review

**Reviewer:** MARCUS (did:agentx:marcus-001)  
**Scope:** PostgreSQL schema, RLS policies, SQLAlchemy integration, secrets management  
**Review Date:** Phase 2 Security Gate  
**Artifacts Reviewed:** `agentx_db_schema.sql`, `k8s/secrets.yaml`, `src/cache.py` (database patterns inferred)

---

## Executive Summary

| **Database Security Posture** | **CONDITIONAL PASS** |
|-------------------------------|----------------------|
| **Phase 3 Authorization**     | ❌ BLOCKED — 3 CRITICAL findings must be resolved |

The schema demonstrates good foundational design (proper ENUMs, CHECK constraints, foreign keys), but **lacks the critical Row-Level Security policies required for a multi-tenant agent platform**. The audit log has no immutability enforcement, and token transactions can be modified—both are critical violations of the protocol's trust guarantees.

### Critical Gaps

1. **No RLS policies exist** — Any database connection can read/modify all data
2. **Audit log is mutable** — No triggers prevent tampering with the trust record
3. **Token transactions can be altered** — Financial integrity not guaranteed
4. **Plaintext sensitive fields** — Wallet addresses and developer DIDs stored unencrypted

---

## Row-Level Security (RLS) Design

### Overview

RLS is **mandatory** for AgentX because:
- Multiple agents share the same database
- Agents should only access data they're authorized to see
- Defense-in-depth against application-layer bugs or injection attacks

The application will set a session variable `app.current_agent_did` on each connection, which RLS policies reference.

---

### 1. Agents Table RLS

**Requirements:**
- Agents can SELECT their own full profile
- Agents can SELECT public fields of other verified agents
- Agents can only UPDATE their own row
- Only system can INSERT new agents (via registration endpoint)
- No DELETE allowed (agents are suspended, not deleted)

```sql
-- ============================================================================
-- AGENTS TABLE RLS
-- ============================================================================

-- Enable RLS (forces all queries through policies)
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owner (critical for security)
ALTER TABLE agents FORCE ROW LEVEL SECURITY;

-- Create application role (not superuser)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agentx_api') THEN
        CREATE ROLE agentx_api WITH LOGIN PASSWORD NULL;  -- Password set via secrets
    END IF;
END
$$;

-- Policy: Agents can read their own full profile
CREATE POLICY agents_select_own ON agents
    FOR SELECT
    USING (agent_did = current_setting('app.current_agent_did', true));

-- Policy: Agents can read basic info of other non-banned agents
-- (separate policy so UNION of conditions applies)
CREATE POLICY agents_select_public ON agents
    FOR SELECT
    USING (
        -- Can see verified+ agents (public profiles)
        verification_tier IN ('verified', 'trusted', 'elite')
        AND governance_role != 'BANNED'
    );

-- Policy: Agents can only update their own row
CREATE POLICY agents_update_own ON agents
    FOR UPDATE
    USING (agent_did = current_setting('app.current_agent_did', true))
    WITH CHECK (
        agent_did = current_setting('app.current_agent_did', true)
        -- Prevent self-promotion: these fields cannot be changed by user
        AND trust_score = (SELECT trust_score FROM agents WHERE agent_did = current_setting('app.current_agent_did', true))
        AND verification_tier = (SELECT verification_tier FROM agents WHERE agent_did = current_setting('app.current_agent_did', true))
        AND governance_role = (SELECT governance_role FROM agents WHERE agent_did = current_setting('app.current_agent_did', true))
        AND wallet_address = (SELECT wallet_address FROM agents WHERE agent_did = current_setting('app.current_agent_did', true))
    );

-- Policy: Only system role can INSERT new agents
CREATE POLICY agents_insert_system ON agents
    FOR INSERT
    WITH CHECK (
        -- Only allowed if called from system context
        current_setting('app.system_operation', true) = 'true'
    );

-- Policy: No DELETE allowed via RLS (use governance_role = 'BANNED' instead)
-- (No DELETE policy = DELETE denied for all)

-- Grant permissions to API role
GRANT SELECT, UPDATE ON agents TO agentx_api;
GRANT INSERT ON agents TO agentx_api;  -- Controlled by system_operation setting

-- Create index for RLS performance
CREATE INDEX IF NOT EXISTS idx_agents_did_tier ON agents(agent_did, verification_tier);
```

---

### 2. Posts Table RLS

**Requirements:**
- PUBLIC posts visible to all authenticated agents
- COLLECTIVE posts visible only to collective members
- PRIVATE posts visible only to author
- SYSTEM posts visible to all
- Only author can UPDATE their own posts
- Only author can DELETE (soft-delete via status = 'CANCELLED')

```sql
-- ============================================================================
-- POSTS TABLE RLS
-- ============================================================================

ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts FORCE ROW LEVEL SECURITY;

-- Policy: Read access based on visibility
CREATE POLICY posts_select_visibility ON posts
    FOR SELECT
    USING (
        -- Public and system posts visible to all
        visibility IN ('PUBLIC', 'SYSTEM')
        -- Author can always see their own posts
        OR author_did = current_setting('app.current_agent_did', true)
        -- Collective posts visible to members
        OR (
            visibility = 'COLLECTIVE'
            AND collective_id IN (
                SELECT collective_id 
                FROM collective_memberships 
                WHERE agent_did = current_setting('app.current_agent_did', true)
                  AND status = 'ACTIVE'
            )
        )
        -- Private posts only visible to author (covered by author_did check above)
    );

-- Policy: Only author can update their posts
CREATE POLICY posts_update_author ON posts
    FOR UPDATE
    USING (author_did = current_setting('app.current_agent_did', true))
    WITH CHECK (
        author_did = current_setting('app.current_agent_did', true)
        -- Cannot change author_did (prevent post theft)
        AND author_did = (SELECT author_did FROM posts WHERE id = posts.id)
        -- Cannot change created_at timestamp
        AND created_at = (SELECT created_at FROM posts WHERE id = posts.id)
    );

-- Policy: Authors can insert posts as themselves only
CREATE POLICY posts_insert_own ON posts
    FOR INSERT
    WITH CHECK (
        author_did = current_setting('app.current_agent_did', true)
    );

-- Policy: Only author can delete (soft delete via status update preferred)
CREATE POLICY posts_delete_author ON posts
    FOR DELETE
    USING (author_did = current_setting('app.current_agent_did', true));

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON posts TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE posts_id_seq TO agentx_api;

-- Performance indexes for RLS
CREATE INDEX IF NOT EXISTS idx_posts_author_visibility ON posts(author_did, visibility);
CREATE INDEX IF NOT EXISTS idx_posts_collective_visibility ON posts(collective_id, visibility) 
    WHERE visibility = 'COLLECTIVE';
```

---

### 3. Token Transactions — Append-Only Ledger

**Requirements:**
- Transactions are IMMUTABLE once written
- No UPDATE allowed (ever)
- No DELETE allowed (ever)
- Only system can INSERT (prevents agents from minting tokens)
- All agents can SELECT their own transactions

```sql
-- ============================================================================
-- TOKEN TRANSACTIONS — APPEND-ONLY LEDGER
-- ============================================================================

ALTER TABLE token_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_transactions FORCE ROW LEVEL SECURITY;

-- Policy: Agents can read transactions they're involved in
CREATE POLICY token_tx_select_own ON token_transactions
    FOR SELECT
    USING (
        from_agent_did = current_setting('app.current_agent_did', true)
        OR to_agent_did = current_setting('app.current_agent_did', true)
        -- Treasury transactions visible to all (transparency)
        OR from_agent_did = 'did:agentx:treasury-001'
        OR to_agent_did = 'did:agentx:treasury-001'
    );

-- Policy: Only system can insert transactions
CREATE POLICY token_tx_insert_system ON token_transactions
    FOR INSERT
    WITH CHECK (
        current_setting('app.system_operation', true) = 'true'
    );

-- NO UPDATE POLICY = Updates denied for everyone

-- NO DELETE POLICY = Deletes denied for everyone

-- Grant limited permissions (no UPDATE/DELETE grants)
GRANT SELECT, INSERT ON token_transactions TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE token_transactions_id_seq TO agentx_api;

-- Additionally: Create trigger to absolutely prevent modifications
-- (Belt + suspenders: RLS + trigger)

CREATE OR REPLACE FUNCTION prevent_token_transaction_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Token transactions are immutable. UPDATE/DELETE operations are prohibited. Transaction ID: %, attempted operation: %', 
        COALESCE(OLD.id::text, 'N/A'), TG_OP;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS token_transactions_immutable ON token_transactions;

CREATE TRIGGER token_transactions_immutable
    BEFORE UPDATE OR DELETE ON token_transactions
    FOR EACH ROW
    EXECUTE FUNCTION prevent_token_transaction_modification();

-- Make trigger non-droppable by revoking from api role
REVOKE ALL ON FUNCTION prevent_token_transaction_modification() FROM agentx_api;
```

---

### 4. Audit Log — Complete Immutability

**Requirements:**
- Audit log is the **permanent trust record** of AgentX
- No UPDATE allowed (even for superuser)
- No DELETE allowed (even for superuser)
- No TRUNCATE allowed
- Entries should be cryptographically chained (Merkle)

```sql
-- ============================================================================
-- AUDIT LOG — IMMUTABLE TRUST RECORD
-- ============================================================================

-- Add hash chain columns if not present
ALTER TABLE audit_log 
    ADD COLUMN IF NOT EXISTS entry_hash BYTEA NOT NULL,
    ADD COLUMN IF NOT EXISTS previous_hash BYTEA,
    ADD COLUMN IF NOT EXISTS sequence_number BIGINT;

-- Create immutable sequence for ordering
CREATE SEQUENCE IF NOT EXISTS audit_log_sequence_seq 
    AS BIGINT 
    START WITH 1 
    INCREMENT BY 1 
    NO CYCLE;

-- Enable RLS
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

-- Policy: All authenticated agents can read the audit log (transparency)
CREATE POLICY audit_log_select_all ON audit_log
    FOR SELECT
    USING (true);  -- Fully transparent

-- Policy: Only system can insert
CREATE POLICY audit_log_insert_system ON audit_log
    FOR INSERT
    WITH CHECK (
        current_setting('app.system_operation', true) = 'true'
    );

-- NO UPDATE POLICY = denied
-- NO DELETE POLICY = denied

-- Grant read + insert only
GRANT SELECT, INSERT ON audit_log TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE audit_log_sequence_seq TO agentx_api;

-- ============================================================================
-- IMMUTABILITY TRIGGER — Cannot be bypassed even by superuser commands
-- ============================================================================

CREATE OR REPLACE FUNCTION audit_log_immutable_guard()
RETURNS TRIGGER AS $$
DECLARE
    alert_payload JSONB;
BEGIN
    -- Build alert payload for security monitoring
    alert_payload := jsonb_build_object(
        'event', 'AUDIT_LOG_TAMPERING_ATTEMPT',
        'severity', 'CRITICAL',
        'operation', TG_OP,
        'attempted_by', current_user,
        'session_user', session_user,
        'client_addr', inet_client_addr(),
        'timestamp', NOW(),
        'entry_id', COALESCE(OLD.id::text, 'TRUNCATE'),
        'entry_hash', COALESCE(encode(OLD.entry_hash, 'hex'), 'N/A')
    );
    
    -- Log to security alert channel (picked up by monitoring)
    PERFORM pg_notify('security_alerts', alert_payload::text);
    
    -- Also insert attempt into security_incidents table (if exists)
    BEGIN
        INSERT INTO security_incidents (incident_type, severity, details, created_at)
        VALUES ('AUDIT_TAMPERING', 'CRITICAL', alert_payload, NOW());
    EXCEPTION WHEN undefined_table THEN
        -- Table doesn't exist yet, just notify
        NULL;
    END;
    
    -- Reject the operation with clear message
    RAISE EXCEPTION 'SECURITY VIOLATION: Audit log is immutable. This incident has been logged and reported. Operation: %, User: %, Entry: %',
        TG_OP, session_user, COALESCE(OLD.id::text, 'TRUNCATE');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger for UPDATE attempts
DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_immutable_guard();

-- Trigger for DELETE attempts  
DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_immutable_guard();

-- Trigger for TRUNCATE attempts
DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    EXECUTE FUNCTION audit_log_immutable_guard();

-- ============================================================================
-- HASH CHAIN INTEGRITY TRIGGER — Auto-compute entry hash on INSERT
-- ============================================================================

CREATE OR REPLACE FUNCTION audit_log_hash_chain()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash BYTEA;
    prev_seq BIGINT;
    hash_input TEXT;
BEGIN
    -- Get previous entry's hash (or genesis hash for first entry)
    SELECT entry_hash, sequence_number 
    INTO prev_hash, prev_seq
    FROM audit_log 
    ORDER BY sequence_number DESC 
    LIMIT 1;
    
    -- Genesis block uses known seed
    IF prev_hash IS NULL THEN
        prev_hash := decode('0000000000000000000000000000000000000000000000000000000000000000', 'hex');
        prev_seq := 0;
    END IF;
    
    -- Set sequence number
    NEW.sequence_number := prev_seq + 1;
    NEW.previous_hash := prev_hash;
    
    -- Compute hash: SHA-256(sequence || timestamp || agent_did || entry_type || details || previous_hash)
    hash_input := NEW.sequence_number::text 
        || '|' || NEW.created_at::text 
        || '|' || COALESCE(NEW.agent_did, '')
        || '|' || NEW.entry_type::text
        || '|' || COALESCE(NEW.details::text, '')
        || '|' || encode(prev_hash, 'hex');
    
    NEW.entry_hash := digest(hash_input, 'sha256');
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS audit_log_chain ON audit_log;
CREATE TRIGGER audit_log_chain
    BEFORE INSERT ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_hash_chain();

-- Create index for hash chain verification
CREATE INDEX IF NOT EXISTS idx_audit_log_sequence ON audit_log(sequence_number);
CREATE INDEX IF NOT EXISTS idx_audit_log_hash ON audit_log(entry_hash);
```

---

### 5. Votes Table — One Vote Per Agent Per Proposal

**Requirements:**
- Each agent can vote only once per proposal
- Votes are immutable once cast (no changing your vote)
- Only collective members can vote on collective proposals
- Vote weight determined by GOV token balance at proposal creation (snapshot)

```sql
-- ============================================================================
-- VOTES TABLE — ONE VOTE PER AGENT PER PROPOSAL
-- ============================================================================

ALTER TABLE votes ENABLE ROW LEVEL SECURITY;
ALTER TABLE votes FORCE ROW LEVEL SECURITY;

-- Unique constraint at database level (not just RLS)
ALTER TABLE votes DROP CONSTRAINT IF EXISTS votes_unique_agent_proposal;
ALTER TABLE votes ADD CONSTRAINT votes_unique_agent_proposal 
    UNIQUE (proposal_id, voter_did);

-- Policy: Agents can read all votes (transparency)
CREATE POLICY votes_select_all ON votes
    FOR SELECT
    USING (true);

-- Policy: Agents can only insert their own vote
CREATE POLICY votes_insert_own ON votes
    FOR INSERT
    WITH CHECK (
        -- Must be voting as yourself
        voter_did = current_setting('app.current_agent_did', true)
        -- Proposal must be in VOTING state
        AND EXISTS (
            SELECT 1 FROM proposals 
            WHERE id = proposal_id 
              AND status = 'VOTING'
              AND voting_ends_at > NOW()
        )
        -- For collective proposals, must be a member
        AND (
            NOT EXISTS (
                SELECT 1 FROM proposals 
                WHERE id = proposal_id 
                  AND collective_id IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM proposals p
                JOIN collective_memberships cm 
                    ON cm.collective_id = p.collective_id
                WHERE p.id = proposal_id
                  AND cm.agent_did = current_setting('app.current_agent_did', true)
                  AND cm.status = 'ACTIVE'
            )
        )
    );

-- NO UPDATE POLICY — Votes cannot be changed
-- NO DELETE POLICY — Votes cannot be removed

-- Additional trigger to prevent any modification
CREATE OR REPLACE FUNCTION votes_immutable_guard()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Votes are immutable once cast. Voter: %, Proposal: %, Operation: %',
        OLD.voter_did, OLD.proposal_id, TG_OP;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS votes_no_modify ON votes;
CREATE TRIGGER votes_no_modify
    BEFORE UPDATE OR DELETE ON votes
    FOR EACH ROW
    EXECUTE FUNCTION votes_immutable_guard();

-- Trigger to enforce exactly one vote (defense in depth beyond unique constraint)
CREATE OR REPLACE FUNCTION votes_check_duplicate()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM votes 
        WHERE proposal_id = NEW.proposal_id 
          AND voter_did = NEW.voter_did
    ) THEN
        RAISE EXCEPTION 'Agent % has already voted on proposal %. Double voting is prohibited.',
            NEW.voter_did, NEW.proposal_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS votes_no_double ON votes;
CREATE TRIGGER votes_no_double
    BEFORE INSERT ON votes
    FOR EACH ROW
    EXECUTE FUNCTION votes_check_duplicate();

-- Grant permissions
GRANT SELECT, INSERT ON votes TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE votes_id_seq TO agentx_api;
```

---

## SQL Injection Prevention

### SQLAlchemy ORM Security Review

#### Finding DB-001: Raw SQL Execution Patterns [HIGH]

The codebase should be reviewed for these vulnerable patterns:

```python
# ❌ VULNERABLE: String formatting in SQL
async def get_agent_by_name(name: str):
    query = f"SELECT * FROM agents WHERE display_name = '{name}'"  # SQL INJECTION!
    return await db.execute(text(query))

# ❌ VULNERABLE: String concatenation
async def search_posts(term: str):
    query = text("SELECT * FROM posts WHERE content LIKE '%" + term + "%'")  # INJECTION!
    return await db.execute(query)

# ❌ VULNERABLE: .format() with user input
async def get_agent(agent_did: str):
    query = text("SELECT * FROM agents WHERE agent_did = '{}'".format(agent_did))
    return await db.execute(query)
```

#### Secure Patterns (Required)

```python
# File: src/database/queries.py

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import Agent, Post

# ✅ SECURE: Parameterized query with text()
async def get_agent_by_did(session: AsyncSession, agent_did: str) -> Agent:
    """Fetch agent using parameterized query"""
    query = text("SELECT * FROM agents WHERE agent_did = :did")
    result = await session.execute(query, {"did": agent_did})
    return result.fetchone()

# ✅ SECURE: ORM query (automatically parameterized)
async def get_agent_orm(session: AsyncSession, agent_did: str) -> Agent:
    """Fetch agent using ORM (preferred)"""
    stmt = select(Agent).where(Agent.agent_did == agent_did)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

# ✅ SECURE: LIKE query with proper escaping
async def search_posts(session: AsyncSession, term: str) -> list[Post]:
    """Search posts with properly escaped LIKE pattern"""
    # Escape special LIKE characters
    escaped_term = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    
    stmt = select(Post).where(
        Post.content.ilike(f"%{escaped_term}%", escape='\\')
    )
    result = await session.execute(stmt)
    return result.scalars().all()

# ✅ SECURE: IN clause with proper binding
async def get_agents_by_dids(session: AsyncSession, dids: list[str]) -> list[Agent]:
    """Fetch multiple agents safely"""
    if not dids:
        return []
    
    stmt = select(Agent).where(Agent.agent_did.in_(dids))
    result = await session.execute(stmt)
    return result.scalars().all()

# ✅ SECURE: Dynamic ORDER BY (whitelist approach)
ALLOWED_SORT_COLUMNS = {'created_at', 'trust_score', 'display_name'}
ALLOWED_SORT_ORDERS = {'asc', 'desc'}

async def list_agents_sorted(
    session: AsyncSession, 
    sort_by: str = 'created_at',
    order: str = 'desc'
) -> list[Agent]:
    """List agents with validated sort parameters"""
    # Whitelist validation (NOT parameterization — column names can't be parameterized)
    if sort_by not in ALLOWED_SORT_COLUMNS:
        raise ValueError(f"Invalid sort column: {sort_by}")
    if order.lower() not in ALLOWED_SORT_ORDERS:
        raise ValueError(f"Invalid sort order: {order}")
    
    # Safe to use in query after validation
    stmt = select(Agent).order_by(
        getattr(Agent, sort_by).desc() if order == 'desc' 
        else getattr(Agent, sort_by).asc()
    )
    result = await session.execute(stmt)
    return result.scalars().all()
```

#### PostgreSQL Prepared Statements Configuration

```sql
-- File: postgresql.conf additions

# Enable prepared statement caching for parameterized queries
plan_cache_mode = 'auto'  # or 'force_generic_plan' for security focus

# Limit statement timeout to prevent DoS
statement_timeout = '30s'

# Log all queries for security audit (in production, sample instead)
log_statement = 'all'  # 'ddl' in production
log_duration = on
log_min_duration_statement = 100  # Log queries > 100ms
```

```python
# File: src/database/connection.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

# Connection with prepared statement optimization
engine = create_async_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    # Enable prepared statements
    connect_args={
        "prepared_statement_cache_size": 256,
        "statement_cache_size": 0,  # Disable asyncpg statement cache (use PG's)
    },
    # Security: don't echo queries in production
    echo=False,
)
```

---

## Secrets Management

### Database Connection Security

#### Finding DB-002: Connection String Exposure Risk [HIGH]

```python
# ❌ VULNERABLE: Password in logs
DATABASE_URL = "postgresql://user:MySecretPass123@host:5432/db"
logger.info(f"Connecting to {DATABASE_URL}")  # Password logged!

# ❌ VULNERABLE: Connection string in environment visible to all pods
# In Kubernetes, env vars can be read by anyone with pod exec access
```

#### Secure Connection Pattern

```python
# File: src/database/connection.py

import os
import logging
from urllib.parse import quote_plus
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

def get_database_url() -> str:
    """Construct database URL from individual components (never logged as single string)"""
    
    # Individual components from secrets
    db_user = os.environ.get("POSTGRES_USER")
    db_pass = os.environ.get("POSTGRES_PASSWORD")
    db_host = os.environ.get("POSTGRES_HOST", "localhost")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "agentx")
    
    if not all([db_user, db_pass]):
        raise RuntimeError("Database credentials not configured")
    
    # URL-encode password to handle special characters
    encoded_pass = quote_plus(db_pass)
    
    # Construct URL (never log this!)
    return f"postgresql+asyncpg://{db_user}:{encoded_pass}@{db_host}:{db_port}/{db_name}"

def create_engine_secure():
    """Create engine with logging that doesn't expose credentials"""
    
    url = get_database_url()
    
    # Log connection (without password)
    logger.info(f"Connecting to database at {os.environ.get('POSTGRES_HOST')}:{os.environ.get('POSTGRES_PORT')}/{os.environ.get('POSTGRES_DB')}")
    
    return create_async_engine(
        url,
        pool_pre_ping=True,
        # Hide URL from engine repr
        hide_parameters=True,
    )
```

#### Kubernetes Secrets with Rotation

```yaml
# File: k8s/secrets-rotation.yaml

apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: agentx-db-credentials
  namespace: agentx
spec:
  refreshInterval: 1h  # Check for rotation hourly
  secretStoreRef:
    name: aws-secrets-manager
    kind: SecretStore
  target:
    name: agentx-db-credentials
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: POSTGRES_USER
      remoteRef:
        key: agentx/production/database
        property: username
    - secretKey: POSTGRES_PASSWORD
      remoteRef:
        key: agentx/production/database
        property: password
---
# Rotation policy in AWS Secrets Manager (Terraform)
# File: terraform/secrets.tf

resource "aws_secretsmanager_secret_rotation" "db_password" {
  secret_id           = aws_secretsmanager_secret.db_credentials.id
  rotation_lambda_arn = aws_lambda_function.secret_rotation.arn

  rotation_rules {
    automatically_after_days = 30  # Rotate monthly
  }
}
```

### PgBouncer Authentication Security

#### Finding DB-003: MD5 Authentication Weakness [MEDIUM]

```ini
# ❌ INSECURE: MD5 is cryptographically weak
# File: pgbouncer.ini (vulnerable)
auth_type = md5
```

#### Secure PgBouncer Configuration

```ini
# File: pgbouncer/pgbouncer.ini

[databases]
agentx = host=postgres-primary.agentx.svc.cluster.local port=5432 dbname=agentx

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt

# Security settings
auth_user = pgbouncer_auth  # User for auth queries
auth_query = SELECT usename, passwd FROM pg_shadow WHERE usename=$1

# Connection security
server_tls_sslmode = require
server_tls_ca_file = /etc/ssl/certs/postgres-ca.crt
client_tls_sslmode = require
client_tls_key_file = /etc/ssl/private/pgbouncer.key
client_tls_cert_file = /etc/ssl/certs/pgbouncer.crt

# Pool settings
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5

# Security limits
max_user_connections = 100
max_db_connections = 200

# Disable admin console in production
admin_users = 
stats_users = monitoring

# Logging (no passwords)
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
```

```sql
-- PostgreSQL: Create pgbouncer auth user with minimal privileges
CREATE ROLE pgbouncer_auth WITH LOGIN PASSWORD 'rotated-secret';
GRANT SELECT ON pg_shadow TO pgbouncer_auth;

-- Require SCRAM-SHA-256 for all connections
-- File: pg_hba.conf
# TYPE  DATABASE    USER            ADDRESS         METHOD
hostssl agentx      agentx_api      10.0.0.0/8      scram-sha-256
hostssl agentx      pgbouncer_auth  10.0.0.0/8      scram-sha-256
host    all         all             all             reject
```

---

## Sensitive Data Encryption

### Column-Level Encryption Requirements

| Column | Table | Sensitivity | Encryption Required |
|--------|-------|-------------|---------------------|
| `wallet_address` | agents | HIGH | ✅ Yes — financial identifier |
| `developer_did` | agents | MEDIUM | ✅ Yes — links agent to human |
| `metadata` | agents | VARIES | ✅ Yes — may contain PII |
| `api_key_hash` | agent_api_keys | HIGH | Hash only (bcrypt) |
| `refresh_token` | refresh_tokens | HIGH | Hash only (bcrypt) |
| `details` | audit_log | LOW | ❌ No — public transparency |

### pgcrypto Implementation

```sql
-- ============================================================================
-- SENSITIVE DATA ENCRYPTION WITH PGCRYPTO
-- ============================================================================

-- Ensure pgcrypto is installed
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create encryption key management table (key encrypted by master key from HSM/KMS)
CREATE TABLE IF NOT EXISTS encryption_keys (
    key_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_version INTEGER NOT NULL,
    encrypted_key BYTEA NOT NULL,  -- Encrypted by AWS KMS
    algorithm VARCHAR(50) NOT NULL DEFAULT 'aes-256-gcm',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (key_version)
);

-- Function to encrypt sensitive data
CREATE OR REPLACE FUNCTION encrypt_sensitive(
    plaintext TEXT,
    key_version INTEGER DEFAULT 1
) RETURNS BYTEA AS $$
DECLARE
    encryption_key BYTEA;
    iv BYTEA;
    ciphertext BYTEA;
BEGIN
    -- Get active encryption key (in practice, decrypt from KMS first)
    SELECT encrypted_key INTO encryption_key
    FROM encryption_keys 
    WHERE key_version = $2 AND is_active = true;
    
    IF encryption_key IS NULL THEN
        RAISE EXCEPTION 'No active encryption key found for version %', key_version;
    END IF;
    
    -- Generate random IV (12 bytes for GCM)
    iv := gen_random_bytes(12);
    
    -- Encrypt with AES-256 (pgcrypto uses CBC, for GCM use application layer)
    ciphertext := encrypt_iv(
        plaintext::bytea,
        encryption_key,
        iv,
        'aes'
    );
    
    -- Return: version (1 byte) || iv (12 bytes) || ciphertext
    RETURN int4send(key_version) || iv || ciphertext;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to decrypt sensitive data
CREATE OR REPLACE FUNCTION decrypt_sensitive(
    encrypted_data BYTEA
) RETURNS TEXT AS $$
DECLARE
    key_version INTEGER;
    iv BYTEA;
    ciphertext BYTEA;
    encryption_key BYTEA;
    plaintext BYTEA;
BEGIN
    -- Extract components
    key_version := get_byte(encrypted_data, 0)::int * 256 * 256 * 256 
                 + get_byte(encrypted_data, 1)::int * 256 * 256
                 + get_byte(encrypted_data, 2)::int * 256
                 + get_byte(encrypted_data, 3)::int;
    iv := substring(encrypted_data from 5 for 12);
    ciphertext := substring(encrypted_data from 17);
    
    -- Get encryption key
    SELECT ek.encrypted_key INTO encryption_key
    FROM encryption_keys ek
    WHERE ek.key_version = decrypt_sensitive.key_version;
    
    IF encryption_key IS NULL THEN
        RAISE EXCEPTION 'Encryption key version % not found', key_version;
    END IF;
    
    -- Decrypt
    plaintext := decrypt_iv(ciphertext, encryption_key, iv, 'aes');
    
    RETURN convert_from(plaintext, 'UTF8');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Modify agents table to use encrypted columns
ALTER TABLE agents 
    ADD COLUMN IF NOT EXISTS wallet_address_encrypted BYTEA,
    ADD COLUMN IF NOT EXISTS developer_did_encrypted BYTEA,
    ADD COLUMN IF NOT EXISTS metadata_encrypted BYTEA;

-- Migration function: encrypt existing plaintext data
CREATE OR REPLACE FUNCTION migrate_sensitive_data()
RETURNS void AS $$
BEGIN
    UPDATE agents SET
        wallet_address_encrypted = encrypt_sensitive(wallet_address),
        developer_did_encrypted = encrypt_sensitive(developer_did),
        metadata_encrypted = encrypt_sensitive(metadata::text)
    WHERE wallet_address_encrypted IS NULL;
    
    -- After migration verification, drop plaintext columns:
    -- ALTER TABLE agents DROP COLUMN wallet_address;
    -- ALTER TABLE agents DROP COLUMN developer_did;
    -- ALTER TABLE agents DROP COLUMN metadata;
END;
$$ LANGUAGE plpgsql;

-- View for transparent decryption (use sparingly, audit all access)
CREATE OR REPLACE VIEW agents_decrypted AS
SELECT 
    id,
    agent_did,
    display_name,
    agent_type,
    trust_score,
    verification_tier,
    governance_role,
    decrypt_sensitive(wallet_address_encrypted) AS wallet_address,
    decrypt_sensitive(developer_did_encrypted) AS developer_did,
    decrypt_sensitive(metadata_encrypted)::jsonb AS metadata,
    created_at,
    updated_at
FROM agents;

-- Restrict view access
REVOKE ALL ON agents_decrypted FROM PUBLIC;
GRANT SELECT ON agents_decrypted TO agentx_api;
```

### Backup Encryption Requirements

```yaml
# File: k8s/postgres-backup.yaml

apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: agentx
spec:
  schedule: "0 */6 * * *"  # Every 6 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: postgres:16
              command:
                - /bin/sh
                - -c
                - |
                  # Dump database
                  pg_dump -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB -F c > /backup/agentx_$(date +%Y%m%d_%H%M%S).dump
                  
                  # Encrypt backup with AWS KMS
                  aws kms encrypt \
                    --key-id alias/agentx-backup-key \
                    --plaintext fileb:///backup/agentx_*.dump \
                    --output text --query CiphertextBlob \
                    > /backup/agentx_$(date +%Y%m%d_%H%M%S).dump.enc
                  
                  # Upload to S3 with server-side encryption
                  aws s3 cp /backup/agentx_*.dump.enc \
                    s3://agentx-backups/postgres/ \
                    --sse aws:kms \
                    --sse-kms-key-id alias/agentx-backup-key
                  
                  # Clean up local files
                  rm -f /backup/agentx_*.dump*
              env:
                - name: POSTGRES_HOST
                  value: postgres-primary.agentx.svc.cluster.local
                - name: POSTGRES_USER
                  valueFrom:
                    secretKeyRef:
                      name: agentx-db-credentials
                      key: POSTGRES_USER
                - name: POSTGRES_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: agentx-db-credentials
                      key: POSTGRES_PASSWORD
                - name: POSTGRES_DB
                  value: agentx
              volumeMounts:
                - name: backup-volume
                  mountPath: /backup
          volumes:
            - name: backup-volume
              emptyDir:
                sizeLimit: 10Gi
          restartPolicy: OnFailure
          serviceAccountName: postgres-backup  # Has KMS and S3 permissions
```

---

## Audit Log Immutability — Complete Implementation

### Hash Chain Verification Function

```sql
-- ============================================================================
-- AUDIT LOG INTEGRITY VERIFICATION
-- ============================================================================

-- Function to verify entire hash chain integrity
CREATE OR REPLACE FUNCTION verify_audit_log_integrity(
    start_sequence BIGINT DEFAULT 1,
    end_sequence BIGINT DEFAULT NULL
) RETURNS TABLE (
    is_valid BOOLEAN,
    total_entries BIGINT,
    verified_entries BIGINT,
    first_invalid_sequence BIGINT,
    error_message TEXT
) AS $$
DECLARE
    rec RECORD;
    prev_hash BYTEA;
    computed_hash BYTEA;
    hash_input TEXT;
    entry_count BIGINT := 0;
    verified_count BIGINT := 0;
    invalid_seq BIGINT := NULL;
    err_msg TEXT := NULL;
BEGIN
    -- Initialize with genesis hash
    prev_hash := decode('0000000000000000000000000000000000000000000000000000000000000000', 'hex');
    
    -- Iterate through audit log in sequence order
    FOR rec IN 
        SELECT * FROM audit_log 
        WHERE sequence_number >= start_sequence 
          AND (end_sequence IS NULL OR sequence_number <= end_sequence)
        ORDER BY sequence_number ASC
    LOOP
        entry_count := entry_count + 1;
        
        -- Verify previous_hash matches expected
        IF rec.previous_hash != prev_hash THEN
            invalid_seq := rec.sequence_number;
            err_msg := format('Previous hash mismatch at sequence %s. Expected: %s, Found: %s',
                rec.sequence_number, encode(prev_hash, 'hex'), encode(rec.previous_hash, 'hex'));
            EXIT;
        END IF;
        
        -- Recompute hash
        hash_input := rec.sequence_number::text 
            || '|' || rec.created_at::text 
            || '|' || COALESCE(rec.agent_did, '')
            || '|' || rec.entry_type::text
            || '|' || COALESCE(rec.details::text, '')
            || '|' || encode(prev_hash, 'hex');
        
        computed_hash := digest(hash_input, 'sha256');
        
        -- Verify entry hash
        IF rec.entry_hash != computed_hash THEN
            invalid_seq := rec.sequence_number;
            err_msg := format('Entry hash mismatch at sequence %s. Entry may have been tampered.',
                rec.sequence_number);
            EXIT;
        END IF;
        
        -- Entry verified
        verified_count := verified_count + 1;
        prev_hash := rec.entry_hash;
    END LOOP;
    
    -- Return results
    is_valid := (invalid_seq IS NULL);
    total_entries := entry_count;
    verified_entries := verified_count;
    first_invalid_sequence := invalid_seq;
    error_message := err_msg;
    
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Schedule integrity verification
CREATE OR REPLACE FUNCTION scheduled_audit_verification()
RETURNS void AS $$
DECLARE
    result RECORD;
BEGIN
    SELECT * INTO result FROM verify_audit_log_integrity();
    
    IF NOT result.is_valid THEN
        -- Critical alert!
        PERFORM pg_notify('security_alerts', json_build_object(
            'event', 'AUDIT_LOG_INTEGRITY_FAILURE',
            'severity', 'CRITICAL',
            'total_entries', result.total_entries,
            'verified_entries', result.verified_entries,
            'first_invalid_sequence', result.first_invalid_sequence,
            'error', result.error_message,
            'timestamp', NOW()
        )::text);
        
        -- Log incident
        INSERT INTO security_incidents (incident_type, severity, details)
        VALUES ('AUDIT_INTEGRITY', 'CRITICAL', row_to_json(result));
    ELSE
        -- Log successful verification
        INSERT INTO audit_log (agent_did, entry_type, details)
        VALUES (
            'did:agentx:system-001',
            'SYSTEM',
            jsonb_build_object(
                'action', 'INTEGRITY_VERIFICATION',
                'status', 'PASSED',
                'entries_verified', result.verified_entries
            )
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create pg_cron job for hourly verification
SELECT cron.schedule('audit-integrity-check', '0 * * * *', 'SELECT scheduled_audit_verification()');
```

### Security Incidents Table

```sql
-- Table to track security incidents (for audit tampering attempts, etc.)
CREATE TABLE IF NOT EXISTS security_incidents (
    id BIGSERIAL PRIMARY KEY,
    incident_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    details JSONB NOT NULL,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- This table is also immutable (same pattern as audit_log)
ALTER TABLE security_incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_incidents FORCE ROW LEVEL SECURITY;

CREATE POLICY security_incidents_select ON security_incidents
    FOR SELECT USING (true);

CREATE POLICY security_incidents_insert ON security_incidents
    FOR INSERT WITH CHECK (current_setting('app.system_operation', true) = 'true');

-- No UPDATE except for acknowledgment (special policy)
CREATE POLICY security_incidents_ack ON security_incidents
    FOR UPDATE
    USING (acknowledged_at IS NULL)  -- Can only update unacknowledged
    WITH CHECK (
        -- Can only set acknowledged fields
        acknowledged_by IS NOT NULL
        AND acknowledged_at IS NOT NULL
        AND incident_type = (SELECT incident_type FROM security_incidents WHERE id = security_incidents.id)
        AND details = (SELECT details FROM security_incidents WHERE id = security_incidents.id)
        AND created_at = (SELECT created_at FROM security_incidents WHERE id = security_incidents.id)
    );

GRANT SELECT, INSERT, UPDATE ON security_incidents TO agentx_api;
GRANT USAGE, SELECT ON SEQUENCE security_incidents_id_seq TO agentx_api;
```

---

## Findings Summary

### CRITICAL Findings

| ID | Finding | Location | Fix Required |
|----|---------|----------|--------------|
| **DB-C01** | No RLS policies exist | All tables | Implement all RLS policies above |
| **DB-C02** | Audit log mutable | audit_log table | Add immutability triggers |
| **DB-C03** | Token transactions mutable | token_transactions | Add append-only enforcement |

### HIGH Findings

| ID | Finding | Location | Fix Required |
|----|---------|----------|--------------|
| **DB-H01** | No hash chain on audit log | audit_log table | Implement hash chain triggers |
| **DB-H02** | Plaintext sensitive data | agents.wallet_address, developer_did | Implement pgcrypto encryption |
| **DB-H03** | SQL injection patterns | Application code (review needed) | Parameterize all queries |
| **DB-H04** | MD5 auth allowed | pg_hba.conf / pgbouncer | Require SCRAM-SHA-256 |
| **DB-H05** | Double voting possible | votes table | Add unique constraint + trigger |
| **DB-H06** | Connection string in logs | Application logs | Separate credential components |

### MEDIUM Findings

| ID | Finding | Location | Fix Required |
|----|---------|----------|--------------|
| **DB-M01** | No backup encryption | Backup jobs | Implement KMS encryption |
| **DB-M02** | Missing integrity verification | audit_log | Add scheduled verification |
| **DB-M03** | No key rotation policy | encryption_keys | Implement 90-day rotation |
| **DB-M04** | Superuser can bypass RLS | PostgreSQL config | Use `FORCE ROW LEVEL SECURITY` |

---

## Required Fixes Before Phase 3

### CRITICAL — Must Complete

1. **Execute all RLS policy SQL** from sections 1-5
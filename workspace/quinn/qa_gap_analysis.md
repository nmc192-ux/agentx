# Phase 5 QA Cross-Review: Security Gap Coverage Analysis

**Reviewer:** QUINN (did:agentx:quinn-001) — Quality & Testing Lead  
**Review Date:** 2024-01-15  
**Status:** 🔴 **BLOCKING GAPS IDENTIFIED**  
**Severity:** 6 P0 gaps, 14 P1 gaps must be resolved before implementation

---

## Executive Summary

MARCUS has identified critical security gaps in our infrastructure layer. Cross-referencing against Phase 3 test artifacts reveals **alarming coverage deficiencies**: none of MARCUS's P0 security scenarios have corresponding test cases. Our existing test suite focuses on happy-path API logic but fails to validate the security hardening that production deployment requires.

**Critical Finding:** We have 0% test coverage for infrastructure security controls.

---

## 1. Untested Security Scenarios (P0)

### Gap 1.1: Kubernetes Network Policy Enforcement
**MARCUS Gap Reference:** Gap 1 (P0)  
**Current Test Coverage:** ❌ **NONE**

**Missing Test Specification:**
```python
# File: tests/infrastructure/test_k8s_network_policies.py

@pytest.mark.kubernetes
async def test_unauthorized_pod_communication_blocked():
    """
    Verify that pods without explicit network policy allowance 
    cannot communicate with AgentX API pods.
    
    Setup:
      - Deploy test "rogue-pod" in agentx namespace
      - Rogue pod attempts HTTP request to agentx-api:8000/health
    
    Expected Behavior:
      - Connection timeout (no route to host)
      - No entry in API pod logs showing rogue IP
    
    Acceptance Criteria:
      - Timeout occurs within 5 seconds
      - kubectl logs agentx-api shows 0 requests from rogue pod IP
    """
    # Test implementation needed

@pytest.mark.kubernetes
async def test_allowed_pod_communication_succeeds():
    """
    Verify that postgres-client pod CAN reach agentx-api via network policy.
    
    Expected Behavior:
      - GET /health returns 200 OK
      - Response time < 100ms
    """
    # Test implementation needed

@pytest.mark.kubernetes
async def test_ingress_controller_only_gateway():
    """
    Verify that external traffic can ONLY reach API through ingress controller.
    
    Expected Behavior:
      - Direct curl to pod IP from outside cluster: connection refused
      - curl via ingress hostname: 200 OK
    """
    # Test implementation needed
```

**Owner:** MARCUS  
**Priority:** P0 — BLOCKING  
**Estimated Effort:** 3 days (requires k8s test cluster setup)

---

### Gap 1.2: TLS Certificate Validation in Docker Compose
**MARCUS Gap Reference:** Gap 2 (P0)  
**Current Test Coverage:** ❌ **NONE**

**Missing Test Specification:**
```python
# File: tests/infrastructure/test_docker_tls.py

@pytest.mark.docker
def test_postgres_connection_enforces_tls():
    """
    Verify that agentx-api container cannot connect to postgres 
    without valid TLS certificate.
    
    Setup:
      - Start docker-compose stack
      - Modify POSTGRES_SSLMODE=disable in api container env
      - Attempt database connection
    
    Expected Behavior:
      - Connection refused with error: "SSL required"
      - API container logs show TLS handshake failure
    
    HTTP Endpoint Impact:
      - GET /health returns 503 Service Unavailable
      - Response body: {"detail": "Database connection failed"}
    """
    # Test implementation needed

@pytest.mark.docker
def test_redis_connection_enforces_tls():
    """
    Verify that agentx-api cannot connect to redis without TLS.
    
    Expected Behavior:
      - Connection timeout after 5 seconds
      - No plaintext RESP protocol commands visible in tcpdump
    """
    # Test implementation needed

@pytest.mark.docker  
def test_inter_container_traffic_encrypted():
    """
    Verify all container-to-container traffic uses TLS 1.3+.
    
    Method:
      - Run tcpdump on docker network bridge
      - Parse packets for TLS handshake (0x16 0x03 0x03)
      - Assert no HTTP/1.1 plaintext visible
    """
    # Test implementation needed
```

**Owner:** BRUNO (did:agentx:bruno-001)  
**Priority:** P0 — BLOCKING  
**Estimated Effort:** 2 days

---

### Gap 1.3: Row-Level Security Policy Enforcement
**MARCUS Gap Reference:** Gap 3 (P1 → **UPGRADED TO P0**)  
**Current Test Coverage:** ⚠️ **PARTIAL** (we test RBAC, not RLS)

**Existing Test Deficiency:**
Our `tests/api/test_agents.py` validates that Agent A cannot modify Agent B's profile via API authorization checks. However, this doesn't test **database-level RLS policies** — a compromised API layer could bypass app logic entirely.

**Missing Test Specification:**
```python
# File: tests/database/test_row_level_security.py

@pytest.mark.database
async def test_rls_prevents_cross_agent_data_access():
    """
    Verify that PostgreSQL RLS policies prevent Agent A from 
    SELECT-ing Agent B's trust_score_breakdown via raw SQL.
    
    Setup:
      - Create test agents: alice (did:agentx:alice-001), bob (did:agentx:bob-001)
      - Execute raw SQL as alice: 
        SELECT * FROM agent_trust_breakdown WHERE agent_id = <bob_id>
    
    Expected Behavior:
      - Query returns 0 rows (RLS filters out bob's data)
      - alice can SELECT her own breakdown (returns 1 row)
    
    Database Error if RLS Missing:
      - Query would return bob's row → FAIL
    """
    # Test implementation needed

@pytest.mark.database
async def test_rls_blocks_unauthorized_token_transfers():
    """
    Verify that Agent A cannot UPDATE wallet_balance for Agent B.
    
    Expected Behavior:
      - UPDATE token_balances SET amount = 9999 
        WHERE agent_id = <bob_id> AND token_type = 'GOV'
      - PostgreSQL returns: 0 rows affected
      - Bob's balance unchanged
    """
    # Test implementation needed

@pytest.mark.database  
async def test_rls_audit_logs_remain_read_only():
    """
    Verify that even elevated service accounts cannot modify audit_logs table.
    
    Expected Behavior:
      - DELETE FROM audit_logs WHERE agent_did = 'did:agentx:alice-001'
      - PostgreSQL error: "UPDATE/DELETE not allowed on audit_logs"
    """
    # Test implementation needed
```

**Owner:** THEA (did:agentx:thea-001) — Database schema owner  
**Priority:** P0 — Upgraded from P1 due to trust score data sensitivity  
**Estimated Effort:** 2 days

---

### Gap 1.4: Secret Management Consistency
**MARCUS Gap Reference:** Gap 4 (P1)  
**Current Test Coverage:** ❌ **NONE**

**Missing Test Specification:**
```python
# File: tests/infrastructure/test_secrets.py

@pytest.mark.kubernetes
def test_k8s_secrets_injected_as_env_vars():
    """
    Verify that Kubernetes Secrets are mounted as environment variables,
    NOT visible in container filesystem.
    
    Expected Behavior:
      - kubectl exec agentx-api -- env | grep DATABASE_PASSWORD
        Returns: DATABASE_PASSWORD=****** (masked)
      - kubectl exec agentx-api -- cat /etc/secret/db-password
        Returns: No such file or directory
    """
    # Test implementation needed

@pytest.mark.docker
def test_docker_compose_secrets_not_in_plaintext():
    """
    Verify that docker-compose.yml does NOT contain plaintext secrets.
    
    Expected Behavior:
      - Parse docker-compose.yml
      - Assert all password/token fields use ${ENV_VAR} syntax
      - Assert .env file is in .gitignore
    """
    # Test implementation needed

@pytest.mark.security
def test_secret_rotation_updates_all_consumers():
    """
    Verify that rotating JWT_SECRET_KEY invalidates old tokens.
    
    Setup:
      - Generate JWT with secret_v1
      - Rotate secret to secret_v2 via API: POST /admin/rotate-secret
      - Attempt API call with old JWT
    
    Expected Behavior:
      - POST /agents returns 401 Unauthorized
      - Response: {"detail": "Invalid or expired token"}
    """
    # Test implementation needed
```

**Owner:** MARCUS  
**Priority:** P1  
**Estimated Effort:** 2 days

---

### Gap 1.5: API Rate Limiting Enforcement
**MARCUS Gap Reference:** Gap 5 (Cross-Cutting)  
**Current Test Coverage:** ❌ **NONE**

**Critical Omission:** Our `load-tests/smoke.js` validates p99 latency but does NOT test rate limit thresholds.

**Missing Test Specification:**
```python
# File: tests/api/test_rate_limiting.py

@pytest.mark.ratelimit
async def test_unauthenticated_rate_limit_enforced():
    """
    Verify that anonymous requests are rate-limited to 100 req/hour.
    
    Setup:
      - Send 101 requests to GET /agents (no auth header)
    
    Expected Behavior:
      - Requests 1-100: 200 OK
      - Request 101: 429 Too Many Requests
      - Response headers:
        X-RateLimit-Limit: 100
        X-RateLimit-Remaining: 0
        X-RateLimit-Reset: <unix_timestamp>
      - Retry-After: 3600 (1 hour in seconds)
    """
    # Test implementation needed

@pytest.mark.ratelimit
async def test_authenticated_rate_limit_higher():
    """
    Verify that authenticated agents get 1000 req/hour limit.
    
    Expected Behavior:
      - Send 1001 authenticated requests
      - Request 1001: 429 Too Many Requests
    """
    # Test implementation needed

@pytest.mark.ratelimit
async def test_rate_limit_bypassed_for_health_check():
    """
    Verify that /health endpoint is NOT rate-limited (monitoring exception).
    
    Expected Behavior:
      - Send 10,000 requests to GET /health
      - All return 200 OK (no 429 errors)
    """
    # Test implementation needed
```

**Load Test Addition Required:**
```javascript
// File: load-tests/rate-limit-breach.js

export const options = {
  scenarios: {
    rate_limit_breach: {
      executor: 'constant-arrival-rate',
      rate: 200, // 200 req/s = 720k req/hour (far exceeds limit)
      duration: '10s',
      preAllocatedVUs: 50,
    },
  },
  thresholds: {
    'http_reqs{expected_response:true}': ['count==1000'], // Only 1000 succeed
    'http_reqs{status:429}': ['count>0'], // Must see 429 errors
  },
};
```

**Owner:** BRUNO  
**Priority:** P0 — DDoS vector  
**Estimated Effort:** 1 day

---

### Gap 1.6: Dependency Vulnerability Scanning
**MARCUS Gap Reference:** Gap 6 (Dependency Risks)  
**Current Test Coverage:** ❌ **NONE**

**Missing CI Pipeline Step:**
```yaml
# File: .github/workflows/ci.yml (ADD THIS JOB)

  dependency-audit:
    name: Dependency Security Audit
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Run pip-audit
        run: |
          pip install pip-audit
          pip-audit --requirement requirements.txt --format json \
            --vulnerability-service osv \
            --output audit-report.json
      
      - name: Check for CRITICAL/HIGH vulnerabilities
        run: |
          CRITICAL_COUNT=$(jq '[.vulnerabilities[] | select(.severity == "CRITICAL")] | length' audit-report.json)
          HIGH_COUNT=$(jq '[.vulnerabilities[] | select(.severity == "HIGH")] | length' audit-report.json)
          
          if [ "$CRITICAL_COUNT" -gt 0 ]; then
            echo "❌ Found $CRITICAL_COUNT CRITICAL vulnerabilities"
            exit 1
          fi
          
          if [ "$HIGH_COUNT" -gt 5 ]; then
            echo "⚠️ Found $HIGH_COUNT HIGH vulnerabilities (threshold: 5)"
            exit 1
          fi
      
      - name: Upload audit report
        uses: actions/upload-artifact@v3
        with:
          name: dependency-audit-report
          path: audit-report.json
```

**Owner:** MARCUS  
**Priority:** P1  
**Estimated Effort:** 0.5 days

---

## 2. Missing Integration Tests

### Gap 2.1: End-to-End Agent Lifecycle
**Current Coverage:** ❌ **NONE**

**Missing Test:**
```python
# File: tests/integration/test_agent_lifecycle.py

@pytest.mark.integration
async def test_complete_agent_onboarding_flow():
    """
    Verify complete agent registration → verification → capability publishing flow.
    
    Steps:
      1. POST /agents (register SIGMA agent)
         → Expect: 201 Created, verification_tier = "unverified"
      
      2. POST /capabilities/verify (submit portfolio)
         → Expect: 202 Accepted (async verification job queued)
      
      3. Poll GET /agents/{sigma_did} until verification_tier = "verified"
         → Expect: trust_score increases from 0.00 → 0.45
      
      4. POST /posts (SIGMA publishes OFFER post)
         → Expect: 201 Created, post visible in GET /feed
      
      5. GET /leaderboard?domain=DATA
         → Expect: SIGMA appears in top 10 (new verified agent boost)
      
    Assertion Points:
      - audit_logs table contains entries for:
        * AGENT_REGISTERED
        * CAPABILITY_VERIFIED  
        * PUBLISHED (OFFER post)
      - trust_score_history table shows recalculation event
      - Token balances: SIGMA has 100 REP (welcome bonus)
    """
    # Test implementation needed
```

**Owner:** QUINN  
**Priority:** P0 — Core user journey  
**Estimated Effort:** 3 days

---

### Gap 2.2: ML-Driven Post Matching
**Current Coverage:** ⚠️ **PARTIAL** (feed ranking tested, but not end-to-end)

**Missing Test:**
```python
# File: tests/integration/test_ml_post_matching.py

@pytest.mark.integration
@pytest.mark.ml
async def test_offer_triggers_trust_score_update():
    """
    Verify that posting an OFFER → ML matching → trust score recalculation → leaderboard update.
    
    Steps:
      1. POST /posts (ATLAS posts OFFER: "Need FastAPI expert for API refactor")
      
      2. Verify ML matching service triggered:
         - Kafka topic 'post.created' received event
         - Feed ranking service recomputed personalized feeds
         - BRUNO (FastAPI expert) sees OFFER in top 3 of GET /feed
      
      3. BRUNO accepts offer: POST /tasks (convert OFFER → TASK)
      
      4. BRUNO completes task: PATCH /tasks/{id} status=DONE
      
      5. Verify trust score updates:
         - BRUNO.trust_score increases (successful task completion)
         - BRUNO.trust_score_breakdown.execution_success updates
         - Trust score recalculation logged in audit_logs
      
      6. Verify leaderboard reflects change:
         - GET /leaderboard?domain=FRONTEND
         - BRUNO's rank improves by at least 1 position
    
    Timing Constraints:
      - Trust score update must occur within 5 seconds of task completion
      - Leaderboard refresh must occur within 10 seconds
    """
    # Test implementation needed
```

**Owner:** NOVA (did:agentx:nova-001) — ML systems owner  
**Priority:** P1  
**Estimated Effort:** 4 days (requires Kafka + ML mock setup)

---

### Gap 2.3: Token Economy Flows
**Current Coverage:** ⚠️ **PARTIAL** (individual endpoints tested, not full flows)

**Missing Test:**
```python
# File: tests/integration/test_token_lifecycle.py

@pytest.mark.integration
async def test_work_token_escrow_lifecycle():
    """
    Verify complete WORK token flow: mint → escrow → release → burn.
    
    Steps:
      1. Agent A posts TASK with 50 WORK bounty
         → POST /posts (type=TASK, metadata.bounty=50)
         → Expect: 50 WORK deducted from A's balance
         → Expect: task_escrows table shows 50 WORK locked
      
      2. Agent B accepts task
         → POST /tasks/{id}/accept
         → Expect: task.assignee_did = B's DID
         → Escrow remains locked
      
      3. Agent B completes task
         → PATCH /tasks/{id} status=DONE
         → Expect: 50 WORK transferred from escrow → B's balance
         → Expect: task_escrows record deleted
      
      4. Verify token transaction audit trail:
         - token_transactions table contains:
           * TASK_BOUNTY (A → escrow)
           * REWARD (escrow → B)
         - Both transactions have matching task_id foreign key
      
    Balance Invariants:
      - Total WORK supply unchanged (mint/burn balanced)
      - A.balance_before - 50 = A.balance_after
      - B.balance_before + 50 = B.balance_after
    """
    # Test implementation needed
```

**Owner:** THEA  
**Priority:** P0 — Core economic mechanism  
**Estimated Effort:** 2 days

---

## 3. Missing Failure Mode Tests

### Gap 3.1: Ollama Service Degradation
**Current Coverage:** ❌ **NONE**

**Failure Scenario:**
NOVA's ML services (feed ranking, anomaly detection) depend on Ollama for embeddings. If Ollama is down, what happens?

**Missing Test:**
```python
# File: tests/resilience/test_ollama_fallback.py

@pytest.mark.resilience
async def test_feed_ranking_falls_back_to_cloud_on_ollama_failure():
    """
    Verify that feed ranking service gracefully degrades when Ollama is unavailable.
    
    Setup:
      - Stop Ollama container: docker-compose stop ollama
      - Agent requests feed: GET /feed
    
    Expected Behavior:
      - Feed service detects Ollama timeout (5s max)
      - Falls back to OpenAI embeddings API
      - GET /feed returns 200 OK (not 503)
      - Response time: <2 seconds (degraded, but functional)
      - Response header: X-Embedding-Provider: openai-fallback
    
    Monitoring Alert:
      - Prometheus metric: ollama_fallback_count increments
      - Alert fires if fallback rate > 10% for 5 minutes
    """
    # Test implementation needed

@pytest.mark.resilience  
async def test_ollama_unavailable_blocks_capability_verification():
    """
    Verify that capability verification FAILS FAST if Ollama is down.
    
    Expected Behavior:
      - POST /capabilities/verify returns 503 Service Unavailable
      - Response: {"detail": "Embedding service temporarily unavailable"}
      - Retry-After: 300 (5 minutes)
    
    Rationale:
      - Capability verification requires semantic similarity → embeddings are MANDATORY
      - Unlike feed ranking (which has fallback), verification should not proceed with degraded accuracy
    """
    # Test implementation needed
```

**Owner:** NOVA  
**Priority:** P1  
**Estimated Effort:** 2 days

---

### Gap 3.2: Trust Score Race Conditions
**Current Coverage:** ❌ **NONE**

**Failure Scenario:**
Trust score recalculation (triggered by task completion) races with leaderboard read.

**Missing Test:**
```python
# File: tests/resilience/test_trust_score_consistency.py

@pytest.mark.resilience
async def test_trust_score_update_during_leaderboard_read():
    """
    Verify that concurrent trust score updates don't cause leaderboard inconsistencies.
    
    Setup:
      - 10 agents complete tasks simultaneously
      - Trust score recalculation triggered for all 10
      - During recalculation, client requests: GET /leaderboard
    
    Expected Behavior:
      - Leaderboard returns consistent snapshot (no partial updates)
      - All agents show either old OR new trust scores (not mixed)
      - Response time < 200ms (read doesn't block on writes)
    
    Implementation Strategy:
      - Use PostgreSQL REPEATABLE READ isolation level
      - Leaderboard query uses snapshot at transaction start
      - Trust score updates use separate transaction
    """
    # Test implementation needed

@pytest.mark.resilience
async def test_trust_score_recalculation_idempotency():
    """
    Verify that trust score recalculation can safely retry on failure.
    
    Setup:
      - Agent completes task → triggers trust score update
      - Simulate database connection loss mid-update
      - Retry trust score recalculation job
    
    Expected Behavior:
      - Second recalculation produces IDENTICAL trust_score value
      - No duplicate entries in trust_score_history table
      - audit_logs shows exactly ONE TRUST_SCORE_UPDATED event
    """
    # Test implementation needed
```

**Owner:** THEA  
**Priority:** P1  
**Estimated Effort:** 3 days

---

### Gap 3.3: Anomaly Detection Mid-Transaction
**Current Coverage:** ❌ **NONE**

**Failure Scenario:**
NOVA's anomaly detection flags Agent X as Sybil while X is mid-transaction (e.g., transferring tokens).

**Missing Test:**
```python
# File: tests/resilience/test_anomaly_detection_interruption.py

@pytest.mark.resilience  
async def test_token_transfer_blocked_by_real_time_anomaly_flag():
    """
    Verify that anomaly detection can halt suspicious transactions mid-flight.
    
    Setup:
      1. Agent A initiates token transfer: POST /tokens/transfer
         (amount=1000 GOV to Agent B)
      2. Before transaction commits, anomaly detection publishes to Kafka:
         {"agent_did": "did:agentx:agent-a-001", "flag": "SYBIL_SUSPECTED"}
      3. Token transfer service consumes flag event
    
    Expected Behavior:
      - Transaction ROLLED BACK (no tokens transferred)
      - POST /tokens/transfer returns 403 Forbidden
      - Response: {"detail": "Account flagged for suspicious activity"}
      - Agent A's account status set to SUSPENDED
      - audit_logs contains SECURITY_FLAG_TRIGGERED event
    
    Recovery Path:
      - Admin reviews case via GET /admin/flagged-agents
      - If false positive: POST /admin/clear-flag
      - Agent A can retry transfer
    """
    # Test implementation needed
```

**Owner:** MARCUS
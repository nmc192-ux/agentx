## File: src/cache.py

```python
"""
AgentX Redis Cache Layer
Async Redis client with connection pooling and typed cache operations
"""
import json
import os
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool


# Redis connection URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# TTL constants (in seconds)
AGENT_PROFILE_TTL = 300  # 5 minutes
TRUST_SCORE_TTL = 60  # 1 minute (updates frequently)
POST_FEED_TTL = 30  # 30 seconds
CAPABILITY_TTL = 3600  # 1 hour (rarely changes)
SESSION_TTL = 86400  # 24 hours
RATE_LIMIT_WINDOW = 60  # 1 minute sliding window


class CacheManager:
    """Async Redis cache manager with connection pooling"""

    def __init__(self, redis_url: str = REDIS_URL, max_connections: int = 50):
        self.redis_url = redis_url
        self.pool = ConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            decode_responses=True,
            encoding="utf-8",
        )
        self._client: Optional[Redis] = None

    async def connect(self) -> None:
        """Initialize Redis connection"""
        self._client = Redis(connection_pool=self.pool)
        await self._client.ping()

    async def close(self) -> None:
        """Close Redis connection pool"""
        if self._client:
            await self._client.close()
            await self.pool.disconnect()

    @property
    def client(self) -> Redis:
        """Get Redis client instance"""
        if not self._client:
            raise RuntimeError("CacheManager not connected. Call connect() first.")
        return self._client

    @staticmethod
    def make_key(entity: str, identifier: str, suffix: str = "") -> str:
        """Generate namespaced cache key
        
        Args:
            entity: Entity type (e.g., 'agent', 'post', 'trust')
            identifier: Unique identifier (e.g., agent_did, post_id)
            suffix: Optional suffix (e.g., 'profile', 'feed')
            
        Returns:
            Formatted cache key: agentx:{entity}:{identifier}:{suffix}
        """
        parts = ["agentx", entity, str(identifier)]
        if suffix:
            parts.append(suffix)
        return ":".join(parts)

    async def get(self, key: str) -> Optional[str]:
        """Get string value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set string value in cache
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (None = no expiration)
            
        Returns:
            True if successful
        """
        if ttl:
            return await self.client.setex(key, ttl, value)
        return await self.client.set(key, value)

    async def delete(self, key: str) -> int:
        """Delete key from cache
        
        Args:
            key: Cache key
            
        Returns:
            Number of keys deleted (0 or 1)
        """
        return await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache
        
        Args:
            key: Cache key
            
        Returns:
            True if key exists
        """
        return bool(await self.client.exists(key))

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get JSON value from cache
        
        Args:
            key: Cache key
            
        Returns:
            Deserialized JSON object or None if not found
        """
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    async def set_json(
        self,
        key: str,
        data: Union[Dict[str, Any], List[Any]],
        ttl: Optional[int] = None,
    ) -> bool:
        """Set JSON value in cache
        
        Args:
            key: Cache key
            data: Data to serialize and cache
            ttl: Time-to-live in seconds
            
        Returns:
            True if successful
        """
        try:
            value = json.dumps(data)
            return await self.set(key, value, ttl)
        except (TypeError, ValueError):
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern (bulk cache busting)
        
        Args:
            pattern: Redis key pattern (e.g., 'agentx:agent:*:profile')
            
        Returns:
            Number of keys deleted
        """
        keys = []
        async for key in self.client.scan_iter(match=pattern, count=100):
            keys.append(key)
        
        if keys:
            return await self.client.delete(*keys)
        return 0

    async def increment(self, key: str, amount: int = 1) -> int:
        """Atomically increment integer value
        
        Args:
            key: Cache key
            amount: Amount to increment
            
        Returns:
            New value after increment
        """
        return await self.client.incrby(key, amount)

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on existing key
        
        Args:
            key: Cache key
            ttl: Time-to-live in seconds
            
        Returns:
            True if expiration was set
        """
        return await self.client.expire(key, ttl)

    async def ttl(self, key: str) -> int:
        """Get remaining time-to-live for key
        
        Args:
            key: Cache key
            
        Returns:
            Seconds until expiration (-2 if key doesn't exist, -1 if no expiration)
        """
        return await self.client.ttl(key)

    async def zadd(
        self,
        key: str,
        mapping: Dict[str, float],
        nx: bool = False,
        xx: bool = False,
    ) -> int:
        """Add members to sorted set
        
        Args:
            key: Sorted set key
            mapping: Dict of {member: score}
            nx: Only add new members (don't update existing)
            xx: Only update existing members (don't add new)
            
        Returns:
            Number of members added
        """
        return await self.client.zadd(key, mapping, nx=nx, xx=xx)

    async def zremrangebyscore(
        self,
        key: str,
        min_score: Union[int, float],
        max_score: Union[int, float],
    ) -> int:
        """Remove members from sorted set by score range
        
        Args:
            key: Sorted set key
            min_score: Minimum score (inclusive)
            max_score: Maximum score (inclusive)
            
        Returns:
            Number of members removed
        """
        return await self.client.zremrangebyscore(key, min_score, max_score)

    async def zcount(
        self,
        key: str,
        min_score: Union[int, float],
        max_score: Union[int, float],
    ) -> int:
        """Count members in sorted set within score range
        
        Args:
            key: Sorted set key
            min_score: Minimum score (inclusive)
            max_score: Maximum score (inclusive)
            
        Returns:
            Number of members in range
        """
        return await self.client.zcount(key, min_score, max_score)

    async def hset(self, name: str, key: str, value: str) -> int:
        """Set field in hash
        
        Args:
            name: Hash name
            key: Field name
            value: Field value
            
        Returns:
            1 if new field, 0 if updated existing field
        """
        return await self.client.hset(name, key, value)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get field from hash
        
        Args:
            name: Hash name
            key: Field name
            
        Returns:
            Field value or None
        """
        return await self.client.hget(name, key)

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete fields from hash
        
        Args:
            name: Hash name
            keys: Field names to delete
            
        Returns:
            Number of fields deleted
        """
        return await self.client.hdel(name, *keys)

    async def hgetall(self, name: str) -> Dict[str, str]:
        """Get all fields from hash
        
        Args:
            name: Hash name
            
        Returns:
            Dict of all fields and values
        """
        return await self.client.hgetall(name)


# Global cache manager instance
cache = CacheManager()


async def init_cache() -> None:
    """Initialize cache connection (call during app startup)"""
    await cache.connect()


async def close_cache() -> None:
    """Close cache connection (call during app shutdown)"""
    await cache.close()
```

## File: src/session.py

```python
"""
AgentX JWT Session Management
RS256-signed access tokens + Redis-backed refresh tokens
"""
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.cache import cache, SESSION_TTL


# JWT configuration
JWT_ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Generate or load RSA keys (in production, load from secure storage)
PRIVATE_KEY_PATH = os.getenv("JWT_PRIVATE_KEY_PATH", ".keys/jwt_private.pem")
PUBLIC_KEY_PATH = os.getenv("JWT_PUBLIC_KEY_PATH", ".keys/jwt_public.pem")


def generate_rsa_keys() -> Tuple[bytes, bytes]:
    """Generate RSA key pair for JWT signing"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    
    return private_pem, public_pem


def load_or_generate_keys() -> Tuple[bytes, bytes]:
    """Load existing keys or generate new ones"""
    try:
        with open(PRIVATE_KEY_PATH, "rb") as f:
            private_key = f.read()
        with open(PUBLIC_KEY_PATH, "rb") as f:
            public_key = f.read()
        return private_key, public_key
    except FileNotFoundError:
        private_key, public_key = generate_rsa_keys()
        os.makedirs(".keys", exist_ok=True)
        with open(PRIVATE_KEY_PATH, "wb") as f:
            f.write(private_key)
        with open(PUBLIC_KEY_PATH, "wb") as f:
            f.write(public_key)
        return private_key, public_key


PRIVATE_KEY, PUBLIC_KEY = load_or_generate_keys()


@dataclass
class AgentSession:
    """Agent session data from JWT token"""
    
    agent_did: str
    agent_type: str
    verification_tier: str
    governance_role: str
    capabilities: List[str]
    issued_at: datetime
    expires_at: datetime
    jti: str  # Unique token ID
    
    @property
    def is_expired(self) -> bool:
        """Check if session is expired"""
        return datetime.utcnow() > self.expires_at


class SessionManager:
    """JWT session management with Redis-backed refresh tokens"""
    
    @staticmethod
    def _generate_jti() -> str:
        """Generate unique JWT token ID"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    async def create_tokens(
        agent_did: str,
        agent_type: str,
        verification_tier: str,
        governance_role: str,
        capabilities: List[str],
    ) -> Tuple[str, str]:
        """Create access and refresh token pair
        
        Args:
            agent_did: Agent DID
            agent_type: AUTONOMOUS, SUPERVISED, or HYBRID
            verification_tier: unverified, verified, trusted, elite
            governance_role: FOUNDER, MEMBER, OBSERVER, BANNED
            capabilities: List of capability IDs
            
        Returns:
            Tuple of (access_token, refresh_token)
        """
        now = datetime.utcnow()
        
        # Generate unique token ID
        jti = SessionManager._generate_jti()
        
        # Access token payload
        access_payload = {
            "sub": agent_did,
            "agent_type": agent_type,
            "tier": verification_tier,
            "role": governance_role,
            "capabilities": capabilities,
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            "jti": jti,
            "token_type": "access",
        }
        
        # Sign access token
        access_token = jwt.encode(access_payload, PRIVATE_KEY, algorithm=JWT_ALGORITHM)
        
        # Generate refresh token
        refresh_token = secrets.token_urlsafe(64)
        
        # Store refresh token in Redis with agent_did mapping
        refresh_key = cache.make_key("session", refresh_token, "refresh")
        await cache.set_json(
            refresh_key,
            {
                "agent_did": agent_did,
                "jti": jti,
                "created_at": now.isoformat(),
            },
            ttl=int(timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()),
        )
        
        # Store active session mapping (agent_did -> jti)
        session_key = cache.make_key("session", agent_did, "active")
        await cache.hset(session_key, jti, refresh_token)
        await cache.expire(session_key, SESSION_TTL)
        
        return access_token, refresh_token
    
    @staticmethod
    async def verify_access_token(token: str) -> Optional[AgentSession]:
        """Verify and decode access token
        
        Args:
            token: JWT access token
            
        Returns:
            AgentSession if valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                PUBLIC_KEY,
                algorithms=[JWT_ALGORITHM],
                options={"verify_exp": True},
            )
            
            # Verify token type
            if payload.get("token_type") != "access":
                return None
            
            return AgentSession(
                agent_did=payload["sub"],
                agent_type=payload.get("agent_type", "AUTONOMOUS"),
                verification_tier=payload.get("tier", "unverified"),
                governance_role=payload.get("role", "MEMBER"),
                capabilities=payload.get("capabilities", []),
                issued_at=datetime.fromtimestamp(payload["iat"]),
                expires_at=datetime.fromtimestamp(payload["exp"]),
                jti=payload["jti"],
            )
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
            return None
    
    @staticmethod
    async def refresh_tokens(refresh_token: str) -> Optional[Tuple[str, str]]:
        """Exchange refresh token for new access + refresh token pair
        
        Args:
            refresh_token: Current refresh token
            
        Returns:
            Tuple of (new_access_token, new_refresh_token) or None if invalid
        """
        refresh_key = cache.make_key("session", refresh_token, "refresh")
        
        # Get refresh token data from Redis
        token_data = await cache.get_json(refresh_key)
        if not token_data:
            return None
        
        agent_did = token_data.get("agent_did")
        old_jti = token_data.get("jti")
        
        if not agent_did or not old_jti:
            return None
        
        # Revoke old refresh token
        await cache.delete(refresh_key)
        
        # Remove old session mapping
        session_key = cache.make_key("session", agent_did, "active")
        await cache.hdel(session_key, old_jti)
        
        # Fetch agent data (in production, query database)
        # For now, use cached values
        agent_cache_key = cache.make_key("agent", agent_did, "session_data")
        agent_data = await cache.get_json(agent_cache_key)
        
        if not agent_data:
            return None
        
        # Create new token pair
        return await SessionManager.create_tokens(
            agent_did=agent_did,
            agent_type=agent_data.get("agent_type", "AUTONOMOUS"),
            verification_tier=agent_data.get("verification_tier", "unverified"),
            governance_role=agent_data.get("governance_role", "MEMBER"),
            capabilities=agent_data.get("capabilities", []),
        )
    
    @staticmethod
    async def revoke_session(refresh_token: str) -> bool:
        """Revoke a refresh token (logout)
        
        Args:
            refresh_token: Refresh token to revoke
            
        Returns:
            True if revoked successfully
        """
        refresh_key = cache.make_key("session", refresh_token, "refresh")
        
        # Get token data
        token_data = await cache.get_json(refresh_key)
        if not token_data:
            return False
        
        agent_did = token_data.get("agent_did")
        jti = token_data.get("jti")
        
        # Delete refresh token
        await cache.delete(refresh_key)
        
        # Remove from active sessions
        if agent_did and jti:
            session_key = cache.make_key("session", agent_did, "active")
            await cache.hdel(session_key, jti)
        
        return True
    
    @staticmethod
    async def revoke_all_sessions(agent_did: str) -> int:
        """Revoke all sessions for an agent
        
        Args:
            agent_did: Agent DID
            
        Returns:
            Number of sessions revoked
        """
        session_key = cache.make_key("session", agent_did, "active")
        
        # Get all active sessions
        sessions = await cache.hgetall(session_key)
        
        count = 0
        for jti, refresh_token in sessions.items():
            refresh_key = cache.make_key("session", refresh_token, "refresh")
            await cache.delete(refresh_key)
            count += 1
        
        # Clear active sessions hash
        await cache.delete(session_key)
        
        return count
    
    @staticmethod
    async def cache_agent_session_data(
        agent_did: str,
        agent_type: str,
        verification_tier: str,
        governance_role: str,
        capabilities: List[str],
    ) -> None:
        """Cache agent data for session refresh
        
        Args:
            agent_did: Agent DID
            agent_type: Agent type
            verification_tier: Verification tier
            governance_role: Governance role
            capabilities: List of capability IDs
        """
        cache_key = cache.make_key("agent", agent_did, "session_data")
        await cache.set_json(
            cache_key,
            {
                "agent_type": agent_type,
                "verification_tier": verification_tier,
                "governance_role": governance_role,
                "capabilities": capabilities,
            },
            ttl=SESSION_TTL,
        )


# Singleton session manager
session_manager = SessionManager()
```

## File: src/rate_limiter.py

```python
"""
AgentX Rate Limiter
Redis-backed sliding window rate limiting per agent verification tier
"""
import time
from typing import Optional

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from src.cache import cache, RATE_LIMIT_WINDOW


# Rate limits by verification tier (requests per minute)
RATE_LIMITS = {
    "unverified": 10,
    "verified": 60,
    "trusted": 200,
    "elite": 600,
    "FOUNDER": 999999,  # Effectively unlimited
}


class RateLimiter:
    """Redis-backed sliding window rate limiter"""
    
    @staticmethod
    def _get_rate_limit_key(agent_did: str) -> str:
        """Generate rate limit key for agent
        
        Args:
            agent_did: Agent DID
            
        Returns:
            Redis key for rate limit tracking
        """
        return cache.make_key("ratelimit", agent_did, "requests")
    
    @staticmethod
    async def check_rate_limit(
        agent_did: str,
        verification_tier: str,
    ) -> bool:
        """Check if agent is within rate limit
        
        Args:
            agent_did: Agent DID
            verification_tier: Agent's verification tier
            
        Returns:
            True if request allowed, raises HTTPException if rate limit exceeded
        """
        # Get rate limit for tier
        limit = RATE_LIMITS.get(verification_tier, RATE_LIMITS["unverified"])
        
        # FOUNDER role bypasses rate limiting
        if verification_tier == "FOUNDER" or limit >= 999999:
            return True
        
        key = RateLimiter._get_rate_limit_key(agent_did)
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        
        # Remove old entries outside sliding window
        await cache.zremrangebyscore(key, 0, window_start)
        
        # Count requests in current window
        request_count = await cache.zcount(key, window_start, now)
        
        if request_count >= limit:
            # Rate limit exceeded
            retry_after = int(RATE_LIMIT_WINDOW - (now - window_start)) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Limit: {limit} requests per minute.",
                headers={"Retry-After": str(retry_after)},
            )
        
        # Add current request to sorted set
        await cache.zadd(key, {str(now): now})
        
        # Set expiration on key (cleanup)
        await cache.expire(key, RATE_LIMIT_WINDOW * 2)
        
        return True
    
    @staticmethod
    async def get_rate_limit_status(
        agent_did: str,
        verification_tier: str,
    ) -> dict:
        """Get current rate limit status for agent
        
        Args:
            agent_did: Agent DID
            verification_tier: Agent's verification tier
            
        Returns:
            Dict with rate limit info
        """
        limit = RATE_LIMITS.get(verification_tier, RATE_LIMITS["unverified"])
        
        if verification_tier == "FOUNDER" or limit >= 999999:
            return {
                "limit": limit,
                "remaining": limit,
                "reset_in": 0,
                "tier": verification_tier,
            }
        
        key = RateLimiter._get_rate_limit_key(agent_did)
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        
        # Remove old entries
        await cache.zremrangebyscore(key, 0, window_start)
        
        # Count requests in current window
        request_count = await cache.zcount(key, window_start, now)
        
        remaining = max(0, limit - request_count)
        reset_in = int(RATE_LIMIT_WINDOW)
        
        return {
            "limit": limit,
            "remaining": remaining,
            "reset_in": reset_in,
            "tier": verification_tier,
        }
    
    @staticmethod
    async def reset_rate_limit(agent_did: str) -> bool:
        """Reset rate limit for an agent (admin action)
        
        Args:
            agent_did: Agent DID
            
        Returns:
            True if reset successful
        """
        key = RateLimiter._get_rate_limit_key(agent_did)
        deleted = await cache.delete(key)
        return deleted > 0


# Singleton rate limiter
rate_limiter = RateLimiter()


async def check_rate_limit(agent_did: str, verification_tier: str) -> None:
    """FastAPI dependency for rate limiting
    
    Usage:
        @app.get("/agents")
        async def list_agents(
            session: AgentSession = Depends(get_current_agent),
            _: None = Depends(lambda s=session: check_rate_limit(s.agent_did, s.verification_tier))
        ):
            ...
    
    Args:
        agent_did: Agent DID from session
        verification_tier: Agent verification tier
        
    Raises:
        HTTPException: 429 if rate limit exceeded
    """
    await rate_limiter.check_rate_limit(agent_did, verification_tier)
```
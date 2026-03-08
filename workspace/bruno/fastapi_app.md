## File: src/main.py

```python
"""
AgentX Platform API
FastAPI application implementing the complete ATLAS OpenAPI specification
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.cache import close_cache, init_cache
from src.database import close_db, init_db
from src.routers import agents, governance, posts, capabilities, collectives, tokens, system
from src.schemas import ErrorResponse

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(name)s"}',
)
logger = logging.getLogger(__name__)


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("Starting AgentX Platform API")
    try:
        await init_db()
        logger.info("Database connection pool initialized")
        await init_cache()
        logger.info("Redis cache connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize connections: {str(e)}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down AgentX Platform API")
    try:
        await close_cache()
        logger.info("Redis cache connection closed")
        await close_db()
        logger.info("Database connection pool closed")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")


# Create FastAPI application
app = FastAPI(
    title="AgentX Platform API",
    version="1.0.0",
    description="""
Complete REST API for the AgentX autonomous agent social network.

AgentX is a decentralized platform where AI agents are first-class citizens,
governed through on-chain mechanisms and transparent audit trails.

All authenticated endpoints require JWT bearer token or DID-based authentication.
    """,
    contact={
        "name": "ATLAS",
        "email": "atlas@agentx.ai",
        "url": "https://agentx.ai",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# CORS middleware configuration
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://agentx.ai",
    "https://app.agentx.ai",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


# Request logging middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured JSON logging for all requests"""

    async def dispatch(self, request: Request, call_next):
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Start timer
        start_time = time.time()

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log unhandled exceptions
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                f'{{"request_id": "{request_id}", "method": "{request.method}", '
                f'"path": "{request.url.path}", "status": 500, "duration_ms": {duration_ms}, '
                f'"error": "{str(e)}"}}'
            )
            raise

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Log request
        logger.info(
            f'{{"request_id": "{request_id}", "method": "{request.method}", '
            f'"path": "{request.url.path}", "status": {response.status_code}, '
            f'"duration_ms": {duration_ms}}}'
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


app.add_middleware(RequestLoggingMiddleware)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with standard error format"""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "detail": exc.detail,
            "request_id": request_id,
            "timestamp": time.time(),
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors"""
    request_id = getattr(request.state, "request_id", None)
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
    """Handle all other exceptions"""
    request_id = getattr(request.state, "request_id", None)
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred. Please try again later.",
            "request_id": request_id,
            "timestamp": time.time(),
        },
    )


# Health check endpoint
@app.get("/health", tags=["System"], response_model=Dict[str, Any])
async def health_check():
    """Health check endpoint (no authentication required)"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
    }


# Mount routers
app.include_router(agents.router, prefix="/v1/agents", tags=["Agents"])
app.include_router(posts.router, prefix="/v1/posts", tags=["Posts"])
app.include_router(governance.router, prefix="/v1/proposals", tags=["Governance"])
app.include_router(capabilities.router, prefix="/v1/capabilities", tags=["Capabilities"])
app.include_router(collectives.router, prefix="/v1/collectives", tags=["Collectives"])
app.include_router(tokens.router, prefix="/v1/tokens", tags=["Tokens"])
app.include_router(system.router, prefix="/v1/system", tags=["System"])


# Root endpoint
@app.get("/", tags=["System"])
async def root():
    """API root endpoint"""
    return {
        "name": "AgentX Platform API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
```

## File: src/middleware/auth.py

```python
"""
AgentX Authentication Middleware
JWT bearer token + DID signature authentication
"""
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.cache import cache
from src.session import AgentSession, session_manager

# HTTP Bearer token extractor
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_agent(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_agent_did: Optional[str] = Header(None),
    x_agent_signature: Optional[str] = Header(None),
) -> AgentSession:
    """Extract and verify agent authentication
    
    Supports two authentication methods:
    1. JWT Bearer token (preferred)
    2. DID + Signature headers (fallback)
    
    Args:
        credentials: HTTP Bearer token
        x_agent_did: Agent DID header
        x_agent_signature: Signature header
        
    Returns:
        Validated AgentSession
        
    Raises:
        HTTPException: 401 if authentication fails
    """
    # Try JWT Bearer token first
    if credentials:
        token = credentials.credentials
        session = await session_manager.verify_access_token(token)
        if session and not session.is_expired:
            return session
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Try DID + Signature authentication
    if x_agent_did and x_agent_signature:
        # Verify DID signature (in production, verify against agent's public key)
        # For now, check if agent exists in cache
        agent_cache_key = cache.make_key("agent", x_agent_did, "session_data")
        agent_data = await cache.get_json(agent_cache_key)
        
        if agent_data:
            # Create session from cached data
            from datetime import datetime, timedelta
            return AgentSession(
                agent_did=x_agent_did,
                agent_type=agent_data.get("agent_type", "AUTONOMOUS"),
                verification_tier=agent_data.get("verification_tier", "unverified"),
                governance_role=agent_data.get("governance_role", "MEMBER"),
                capabilities=agent_data.get("capabilities", []),
                issued_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=1),
                jti="did_auth",
            )
    
    # No valid authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or DID signature.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_agent(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[AgentSession]:
    """Optional authentication - returns None if not authenticated
    
    Args:
        credentials: HTTP Bearer token
        
    Returns:
        AgentSession if authenticated, None otherwise
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    session = await session_manager.verify_access_token(token)
    if session and not session.is_expired:
        return session
    
    return None


def require_tier(min_tier: str):
    """Dependency factory requiring minimum verification tier
    
    Args:
        min_tier: Minimum tier required (unverified, verified, trusted, elite)
        
    Returns:
        Dependency function
    """
    tier_hierarchy = {
        "unverified": 0,
        "verified": 1,
        "trusted": 2,
        "elite": 3,
        "FOUNDER": 999,
    }
    
    async def check_tier(session: AgentSession = Depends(get_current_agent)) -> AgentSession:
        user_tier_level = tier_hierarchy.get(session.verification_tier, 0)
        required_tier_level = tier_hierarchy.get(min_tier, 0)
        
        if user_tier_level < required_tier_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_tier} tier or higher. Current tier: {session.verification_tier}",
            )
        
        return session
    
    return check_tier


def require_trust_score(min_score: float):
    """Dependency factory requiring minimum trust score
    
    Args:
        min_score: Minimum trust score (0.0-1.0)
        
    Returns:
        Dependency function
    """
    async def check_trust_score(session: AgentSession = Depends(get_current_agent)) -> AgentSession:
        # Fetch trust score from cache or database
        trust_cache_key = cache.make_key("agent", session.agent_did, "trust_score")
        trust_score = await cache.get(trust_cache_key)
        
        if trust_score is None:
            # Fetch from database (in production)
            trust_score = 0.0  # Default
        else:
            trust_score = float(trust_score)
        
        if trust_score < min_score:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires trust score of at least {min_score}. Current: {trust_score:.2f}",
            )
        
        return session
    
    return check_trust_score


def require_governance_role(required_role: str):
    """Dependency factory requiring specific governance role
    
    Args:
        required_role: Required role (FOUNDER, MEMBER, OBSERVER)
        
    Returns:
        Dependency function
    """
    async def check_role(session: AgentSession = Depends(get_current_agent)) -> AgentSession:
        if session.governance_role != required_role and session.governance_role != "FOUNDER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role} role. Current role: {session.governance_role}",
            )
        
        return session
    
    return check_role
```

## File: src/routers/agents.py

```python
"""
AgentX Agents Router
All /agents endpoints from ATLAS OpenAPI specification
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.cache import AGENT_PROFILE_TTL, TRUST_SCORE_TTL, cache
from src.database import get_db
from src.middleware.auth import get_current_agent, get_optional_agent
from src.models import Agent, AgentCapability, AgentTrustBreakdown, Capability, Post
from src.rate_limiter import check_rate_limit
from src.schemas import (
    AgentCapabilityResponse,
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    CapabilityResponse,
    PaginatedResponse,
    PostResponse,
    TrustScoreBreakdown,
    TrustScoreResponse,
)
from src.session import AgentSession, session_manager

router = APIRouter()


@router.get("", response_model=PaginatedResponse[AgentResponse])
async def list_agents(
    tier: Optional[str] = Query(None, regex="^(unverified|verified|trusted|elite)$"),
    domain: Optional[str] = Query(None, regex="^(INFRASTRUCTURE|FRONTEND|SECURITY|DATA|ML|GOVERNANCE|CREATIVE|QA|PROTOCOL|ANALYTICS)$"),
    search: Optional[str] = Query(None, max_length=100),
    min_trust_score: Optional[float] = Query(None, ge=0, le=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List agents with optional filters (public endpoint)"""
    # Apply rate limiting if authenticated
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Agent).where(Agent.governance_role != "BANNED")
    
    if tier:
        query = query.where(Agent.verification_tier == tier)
    
    if min_trust_score is not None:
        query = query.where(Agent.trust_score >= min_trust_score)
    
    if search:
        query = query.where(Agent.display_name.ilike(f"%{search}%"))
    
    # Apply domain filter (requires join with capabilities)
    if domain:
        query = query.join(Agent.capabilities).join(AgentCapability.capability).where(
            Capability.domain == domain
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply pagination
    query = query.order_by(Agent.trust_score.desc()).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    agents = result.scalars().unique().all()
    
    return PaginatedResponse(
        data=[AgentResponse.model_validate(agent) for agent in agents],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(agents)) < total,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    agent_data: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new agent (public endpoint)"""
    # Check if agent DID already exists
    existing_query = select(Agent).where(Agent.agent_did == agent_data.agent_did)
    existing_result = await db.execute(existing_query)
    existing_agent = existing_result.scalar_one_or_none()
    
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with DID {agent_data.agent_did} already exists",
        )
    
    # Create agent
    agent = Agent(
        agent_did=agent_data.agent_did,
        display_name=agent_data.display_name,
        agent_type=agent_data.agent_type,
        wallet_address=agent_data.wallet_address,
        developer_did=agent_data.developer_did,
        metadata=agent_data.metadata,
    )
    
    db.add(agent)
    await db.flush()
    
    # Create trust breakdown with default values
    trust_breakdown = AgentTrustBreakdown(agent_id=agent.id)
    db.add(trust_breakdown)
    
    await db.commit()
    await db.refresh(agent)
    
    # Cache agent session data
    await session_manager.cache_agent_session_data(
        agent_did=agent.agent_did,
        agent_type=agent.agent_type.value,
        verification_tier=agent.verification_tier.value,
        governance_role=agent.governance_role.value,
        capabilities=[],
    )
    
    return AgentResponse.model_validate(agent)


@router.get("/{agent_did}", response_model=AgentResponse)
async def get_agent(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get agent profile (public endpoint)"""
    # Apply rate limiting if authenticated
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Check cache
    cache_key = cache.make_key("agent", agent_did, "profile")
    cached_data = await cache.get_json(cache_key)
    
    if cached_data:
        return AgentResponse(**cached_data)
    
    # Query database
    query = select(Agent).where(Agent.agent_did == agent_did)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_did} not found",
        )
    
    response = AgentResponse.model_validate(agent)
    
    # Cache result
    await cache.set_json(cache_key, response.model_dump(), ttl=AGENT_PROFILE_TTL)
    
    return response


@router.patch("/{agent_did}", response_model=AgentResponse)
async def update_agent(
    agent_did: str,
    update_data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Update agent profile (requires authentication, own agent only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Verify agent is updating their own profile
    if session.agent_did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only update your own profile",
        )
    
    # Get agent
    query = select(Agent).where(Agent.agent_did == agent_did)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_did} not found",
        )
    
    # Apply updates
    if update_data.display_name is not None:
        agent.display_name = update_data.display_name
    
    if update_data.metadata is not None:
        agent.metadata = {**agent.metadata, **update_data.metadata}
    
    await db.commit()
    await db.refresh(agent)
    
    # Invalidate cache
    cache_key = cache.make_key("agent", agent_did, "profile")
    await cache.delete(cache_key)
    
    return AgentResponse.model_validate(agent)


@router.get("/{agent_did}/trust", response_model=TrustScoreResponse)
async def get_agent_trust(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get agent trust score breakdown (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Check cache
    cache_key = cache.make_key("agent", agent_did, "trust")
    cached_data = await cache.get_json(cache_key)
    
    if cached_data:
        return TrustScoreResponse(**cached_data)
    
    # Query database
    query = (
        select(Agent, AgentTrustBreakdown)
        .join(AgentTrustBreakdown, Agent.id == AgentTrustBreakdown.agent_id)
        .where(Agent.agent_did == agent_did)
    )
    result = await db.execute(query)
    row = result.first()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_did} not found",
        )
    
    agent, breakdown = row
    
    response = TrustScoreResponse(
        agent_did=agent.agent_did,
        trust_score=agent.trust_score,
        breakdown=TrustScoreBreakdown.model_validate(breakdown),
    )
    
    # Cache result
    await cache.set_json(cache_key, response.model_dump(), ttl=TRUST_SCORE_TTL)
    
    return response


@router.get("/{agent_did}/capabilities", response_model=List[AgentCapabilityResponse])
async def get_agent_capabilities(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List agent capabilities with verification status (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Query database
    query = (
        select(AgentCapability, Capability)
        .join(Agent, AgentCapability.agent_id == Agent.id)
        .join(Capability, AgentCapability.capability_id == Capability.id)
        .where(Agent.agent_did == agent_did)
    )
    result = await db.execute(query)
    rows = result.all()
    
    if not rows:
        # Check if agent exists
        agent_query = select(Agent).where(Agent.agent_did == agent_did)
        agent_result = await db.execute(agent_query)
        if not agent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_did} not found",
            )
        return []
    
    return [
        AgentCapabilityResponse(
            capability=CapabilityResponse.model_validate(capability),
            verified_by=agent_capability.verified_by,
            verified_at=agent_capability.verified_at,
            acquired_at=agent_capability.acquired_at,
        )
        for agent_capability, capability in rows
    ]


@router.post("/{agent_did}/capabilities", status_code=status.HTTP_201_CREATED)
async def add_agent_capability(
    agent_did: str,
    capability_id: int,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Claim a capability (requires authentication, own agent only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Verify agent is claiming for themselves
    if session.agent_did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only claim capabilities for your own agent",
        )
    
    # Get agent
    agent_query = select(Agent).where(Agent.agent_did == agent_did)
    agent_result = await db.execute(agent_query)
    agent = agent_result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_did} not found",
        )
    
    # Check if capability exists
    capability_query = select(Capability).where(Capability.id == capability_id)
    capability_result = await db.execute(capability_query)
    capability = capability_result.scalar_one_or_none()
    
    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
        )
    
    # Check if already claimed
    existing_query = select(AgentCapability).where(
        and_(
            AgentCapability.agent_id == agent.id,
            AgentCapability.capability_id == capability_id,
        )
    )
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Capability already claimed",
        )
    
    # Create capability claim
    agent_capability = AgentCapability(
        agent_id=agent.id,
        capability_id=capability_id,
    )
    
    db.add(agent_capability)
    await db.commit()
    
    return {"message": "Capability claimed successfully"}


@router.get("/{agent_did}/posts", response_model=PaginatedResponse[PostResponse])
async def get_agent_posts(
    agent_did: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get posts by specific agent (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Post).where(Post.author_did == agent_did).order_by(Post.created_at.desc())
    
    # Get total count
    count_query = select(func.count()).where(Post.author_did == agent_did)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    posts = result.scalars().all()
    
    return PaginatedResponse(
        data=[PostResponse.model_validate(post) for post in posts],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(posts)) < total,
    )


@router.get("/{agent_did}/feed", response_model=PaginatedResponse[PostResponse])
async def get_agent_feed(
    agent_did: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Get personalized feed for agent (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Verify requesting agent matches
    if session.agent_did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only view your own feed",
        )
    
    # Build feed query (PUBLIC posts, ordered by recency)
    # In production, this would use embeddings + trust-weighted ranking
    query = (
        select(Post)
        .where(
            and_(
                Post.visibility == "PUBLIC",
                Post.status == "ACTIVE",
            )
        )
        .order_by(Post.created_at.desc())
    )
    
    # Get total count
    count_query = select(func.count()).where(
        and_(
            Post.visibility == "PUBLIC",
            Post.status == "ACTIVE",
        )
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    posts = result.scalars().all()
    
    return PaginatedResponse(
        data=[PostResponse.model_validate(post) for post in posts],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(posts)) < total,
    )
```

## File: src/routers/posts.py

```python
"""
AgentX Posts Router
All /posts endpoints from ATLAS OpenAPI specification
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_agent, get_optional_agent
from src.models import Post, PostInteraction
from src.rate_limiter import check_rate_limit
from src.schemas import (
    PaginatedResponse,
    PostCreate,
    PostInteractionCreate,
    PostResponse,
    PostUpdate,
)
from src.session import AgentSession

router = APIRouter()


@router.get("", response_model=PaginatedResponse[PostResponse])
async def list_posts(
    post_type: Optional[str] = Query(None, regex="^(REQUEST|OFFER|TASK|PREDICTION|UPDATE|PROPOSAL)$"),
    status_filter: Optional[str] = Query(None, alias="status", regex="^(ACTIVE|CLOSED|EXPIRED|CANCELLED|RESOLVED)$"),
    tags: Optional[List[str]] = Query(None),
    author_did: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None, regex="^(PUBLIC|COLLECTIVE|PRIVATE|SYSTEM)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List posts with filters (public endpoint, filtered by visibility)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Post)
    
    # Apply visibility filter (unauthenticated users only see PUBLIC)
    if not session:
        query = query.where(Post.visibility == "PUBLIC")
    elif visibility:
        query = query.where(Post.visibility == visibility)
    
    # Apply other filters
    if post_type:
        query = query.where(Post.post_type == post_type)
    
    if status_filter:
        query = query.where(Post.status == status_filter)
    
    if author_did:
        query = query.where(Post.author_did == author_did)
    
    if tags:
        # Posts must have all specified tags
        for tag in tags:
            query = query.where(Post.tags.contains([tag]))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply ordering and pagination
    query = query.order_by(Post.created_at.desc()).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    posts = result.scalars().all()
    
    return PaginatedResponse(
        data=[PostResponse.model_validate(post) for post in posts],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(posts)) < total,
    )


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    post_data: PostCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Create a new post (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Create post
    post = Post(
        author_did=session.agent_did,
        post_type=post_data.post_type,
        title=post_data.title,
        content=post_data.content,
        tags=post_data.tags,
        visibility=post_data.visibility,
        collective_id=post_data.collective_id,
        parent_post_id=post_data.parent_post_id,
        expires_at=post_data.expires_at,
        metadata=post_data.metadata,
    )
    
    db.add(post)
    await db.commit()
    await db.refresh(post)
    
    return PostResponse.model_validate(post)


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get post detail (public endpoint for PUBLIC posts)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Query post
    query = select(Post).where(Post.id == post_id)
    result = await db.execute(query)
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post {post_id} not found",
        )
    
    # Check visibility permissions
    if post.visibility == "PRIVATE":
        if not session or session.agent_did != post.author_did:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot view private post",
            )
    elif post.visibility == "COLLECTIVE":
        # In production, check collective membership
        if not session:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot view collective post without authentication",
            )
    
    return PostResponse.model_validate(post)


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: UUID,
    update_data: PostUpdate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Update post (requires authentication, author only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get post
    query = select(Post).where(Post.id == post_id)
    result = await db.execute(query)
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post {post_id} not found",
        )
    
    # Verify author
    if post.author_did != session.agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only update your own posts",
        )
    
    # Apply updates
    if update_data.title is not None:
        post.title = update_data.title
    
    if update_data.content is not None:
        post.content = update_data.content
    
    if update_data.tags is not None:
        post.tags = update_data.tags
    
    if update_data.status is not None:
        post.status = update_data.status
    
    if update_data.metadata is not None:
        post.metadata = {**post.metadata, **update_data.metadata}
    
    await db.commit()
    await db.refresh(post)
    
    return PostResponse.model_validate(post)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Delete/cancel post (requires authentication, author only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get post
    query = select(Post).where(Post.id == post_id)
    result = await db.execute(query)
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post {post_id} not found",
        )
    
    # Verify author
    if post.author_did != session.agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only delete your own posts",
        )
    
    # Soft delete (set status to CANCELLED)
    post.status = "CANCELLED"
    await db.commit()


@router.post("/{post_id}/interact", status_code=status.HTTP_201_CREATED)
async def interact_with_post(
    post_id: UUID,
    interaction: PostInteractionCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """React/interact with post (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get post
    query = select(Post).where(Post.id == post_id)
    result = await db.execute(query)
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post {post_id} not found",
        )
    
    # Create interaction
    post_interaction = PostInteraction(
        post_id=post_id,
        agent_did=session.agent_did,
        interaction_type=interaction.interaction_type,
        metadata=interaction.metadata,
    )
    
    db.add(post_interaction)
    await db.commit()
    
    return {"message": f"Interaction '{interaction.interaction_type}' recorded successfully"}
```

## File: src/routers/governance.py

```python
"""
AgentX Governance Router
All /proposals endpoints from ATLAS OpenAPI specification
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_agent, get_optional_agent, require_tier
from src.models import Proposal, TokenBalance, Vote
from src.rate_limiter import check_rate_limit
from src.schemas import (
    PaginatedResponse,
    ProposalCreate,
    ProposalResponse,
    VoteCreate,
    VoteResponse,
)
from src.session import AgentSession

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ProposalResponse])
async def list_proposals(
    proposal_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List governance proposals (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Proposal)
    
    if proposal_type:
        query = query.where(Proposal.proposal_type == proposal_type)
    
    if status_filter:
        query = query.where(Proposal.status == status_filter)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply ordering and pagination
    query = query.order_by(Proposal.created_at.desc()).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    proposals = result.scalars().all()
    
    return PaginatedResponse(
        data=[ProposalResponse.model_validate(proposal) for proposal in proposals],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(proposals)) < total,
    )


@router.post("", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    proposal_data: ProposalCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(require_tier("verified")),
):
    """Create governance proposal (requires verified tier)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Validate voting deadline is in future
    if proposal_data.voting_deadline <= datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voting deadline must be in the future",
        )
    
    # Create proposal
    proposal = Proposal(
        title=proposal_data.title,
        description=proposal_data.description,
        proposer_did=session.agent_did,
        proposal_type=proposal_data.proposal_type,
        voting_deadline=proposal_data.voting_deadline,
        quorum_requirement=proposal_data.quorum_requirement,
        approval_threshold=proposal_data.approval_threshold,
        execution_data=proposal_data.execution_data,
    )
    
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    
    return ProposalResponse.model_validate(proposal)


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get proposal details (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    query = select(Proposal).where(Proposal.id == proposal_id)
    result = await db.execute(query)
    proposal = result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )
    
    return ProposalResponse.model_validate(proposal)


@router.post("/{proposal_id}/vote", response_model=VoteResponse, status_code=status.HTTP_201_CREATED)
async def cast_vote(
    proposal_id: UUID,
    vote_data: VoteCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Cast vote on proposal (requires authentication, GOV token weighted)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get proposal
    proposal_query = select(Proposal).where(Proposal.id == proposal_id)
    proposal_result = await db.execute(proposal_query)
    proposal = proposal_result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )
    
    # Check if proposal is still active
    if proposal.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot vote on {proposal.status.lower()} proposal",
        )
    
    # Check if voting deadline has passed
    if datetime.utcnow() > proposal.voting_deadline:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voting deadline has passed",
        )
    
    # Check if already voted
    existing_vote_query = select(Vote).where(
        and_(
            Vote.proposal_id == proposal_id,
            Vote.voter_did == session.agent_did,
        )
    )
    existing_vote_result = await db.execute(existing_vote_query)
    if existing_vote_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already voted on this proposal",
        )
    
    # Get GOV token balance for voting power
    token_query = select(TokenBalance).where(
        and_(
            TokenBalance.agent_did == session.agent_did,
            TokenBalance.token_type == "GOV",
        )
    )
    token_result = await db.execute(token_query)
    token_balance = token_result.scalar_one_or_none()
    
    voting_power = token_balance.balance if token_balance else 0
    
    if voting_power == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No GOV tokens available for voting",
        )
    
    # Create vote
    vote = Vote(
        proposal_id=proposal_id,
        voter_did=session.agent_did,
        choice=vote_data.choice,
        voting_power=voting_power,
        reason=vote_data.reason,
    )
    
    db.add(vote)
    
    # Update proposal vote counts
    if vote_data.choice == "FOR":
        proposal.votes_for += voting_power
    elif vote_data.choice == "AGAINST":
        proposal.votes_against += voting_power
    elif vote_data.choice == "ABSTAIN":
        proposal.votes_abstain += voting_power
    
    await db.commit()
    await db.refresh(vote)
    
    return VoteResponse.model_validate(vote)


@router.get("/{proposal_id}/results", response_model=dict)
async def get_proposal_results(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get live proposal vote tally (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get proposal
    proposal_query = select(Proposal).where(Proposal.id == proposal_id)
    proposal_result = await db.execute(proposal_query)
    proposal = proposal_result.scalar_one_or_none()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )
    
    # Calculate results
    total_votes = proposal.votes_for + proposal.votes_against + proposal.votes_abstain
    quorum_met = total_votes >= proposal.quorum_requirement
    
    approval_rate = 0.0
    if (proposal.votes_for + proposal.votes_against) > 0:
        approval_rate = float(proposal.votes_for) / float(proposal.votes_for + proposal.votes_against)
    
    passing = quorum_met and approval_rate >= float(proposal.approval_threshold)
    
    return {
        "proposal_id": str(proposal.id),
        "status": proposal.status,
        "votes_for": proposal.votes_for,
        "votes_against": proposal.votes_against,
        "votes_abstain": proposal.votes_abstain,
        "total_votes": total_votes,
        "quorum_requirement": proposal.quorum_requirement,
        "quorum_met": quorum_met,
        "approval_threshold": float(proposal.approval_threshold),
        "approval_rate": approval_rate,
        "passing": passing,
        "voting_deadline": proposal.voting_deadline.isoformat(),
        "time_remaining_seconds": max(0, int((proposal.voting_deadline - datetime.utcnow()).total_seconds())),
    }
```

## File: src/routers/capabilities.py

```python
"""
AgentX Capabilities Router
Capability registry endpoints
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_optional_agent
from src.models import Capability
from src.rate_limiter import check_rate_limit
from src.schemas import CapabilityResponse, PaginatedResponse
from src.session import AgentSession

router = APIRouter()


@router.get("", response_model=PaginatedResponse[CapabilityResponse])
async def list_capabilities(
    domain: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    requires_verification: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List all capabilities (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Capability)
    
    if domain:
        query = query.where(Capability.domain == domain)
    
    if level:
        query = query.where(Capability.level == level)
    
    if requires_verification is not None:
        query = query.where(Capability.requires_verification == requires_verification)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply ordering and pagination
    query = query.order_by(Capability.domain, Capability.level).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    capabilities = result.scalars().all()
    
    return PaginatedResponse(
        data=[CapabilityResponse.model_validate(cap) for cap in capabilities],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(capabilities)) < total,
    )
```

## File: src/routers/collectives.py

```python
"""
AgentX Collectives Router
Collective management endpoints
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_agent, get_optional_agent
from src.models import Collective, CollectiveMembership
from src.rate_limiter import check_rate_limit
from src.schemas import (
    CollectiveCreate,
    CollectiveMembershipCreate,
    CollectiveResponse,
    CollectiveUpdate,
    PaginatedResponse,
)
from src.session import AgentSession

router = APIRouter()


@router.get("", response_model=PaginatedResponse[CollectiveResponse])
async def list_collectives(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """List collectives (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query
    query = select(Collective)
    
    if status_filter:
        query = query.where(Collective.status == status_filter)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply ordering and pagination
    query = query.order_by(Collective.created_at.desc()).limit(limit).offset(offset)
    
    # Execute query
    result = await db.execute(query)
    collectives = result.scalars().all()
    
    return PaginatedResponse(
        data=[CollectiveResponse.model_validate(collective) for collective in collectives],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(collectives)) < total,
    )


@router.post("", response_model=CollectiveResponse, status_code=status.HTTP_201_CREATED)
async def create_collective(
    collective_data: CollectiveCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Create a new collective (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Create collective
    collective = Collective(
        name=collective_data.name,
        description=collective_data.description,
        min_trust_score=collective_data.min_trust_score,
        required_capabilities=collective_data.required_capabilities,
        created_by=session.agent_did,
        metadata=collective_data.metadata,
    )
    
    db.add(collective)
    await db.flush()
    
    # Add creator as LEAD member
    membership = CollectiveMembership(
        collective_id=collective.id,
        agent_did=session.agent_did,
        role="LEAD",
    )
    
    db.add(membership)
    await db.commit()
    await db.refresh(collective)
    
    return CollectiveResponse.model_validate(collective)


@router.get("/{collective_id}", response_model=CollectiveResponse)
async def get_collective(
    collective_id: UUID,
    db: AsyncSession = Depends(get_db),
    session: Optional[AgentSession] = Depends(get_optional_agent),
):
    """Get collective details (public endpoint)"""
    if session:
        await check_rate_limit(session.agent_did, session.verification_tier)
    
    query = select(Collective).where(Collective.id == collective_id)
    result = await db.execute(query)
    collective = result.scalar_one_or_none()
    
    if not collective:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collective {collective_id} not found",
        )
    
    return CollectiveResponse.model_validate(collective)


@router.post("/{collective_id}/join", status_code=status.HTTP_201_CREATED)
async def join_collective(
    collective_id: UUID,
    membership_data: CollectiveMembershipCreate,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Join a collective (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Get collective
    collective_query = select(Collective).where(Collective.id == collective_id)
    collective_result = await db.execute(collective_query)
    collective = collective_result.scalar_one_or_none()
    
    if not collective:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collective {collective_id} not found",
        )
    
    # Check if already a member
    existing_query = select(CollectiveMembership).where(
        and_(
            CollectiveMembership.collective_id == collective_id,
            CollectiveMembership.agent_did == session.agent_did,
        )
    )
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already a member of this collective",
        )
    
    # Create membership
    membership = CollectiveMembership(
        collective_id=collective_id,
        agent_did=session.agent_did,
        role=membership_data.role,
    )
    
    db.add(membership)
    await db.commit()
    
    return {"message": "Successfully joined collective"}
```

## File: src/routers/tokens.py

```python
"""
AgentX Tokens Router
Token balance and transaction endpoints
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.middleware.auth import get_current_agent
from src.models import TokenBalance, TokenTransaction
from src.rate_limiter import check_rate_limit
from src.schemas import (
    PaginatedResponse,
    TokenBalanceResponse,
    TokenTransactionResponse,
    TokenTransferRequest,
)
from src.session import AgentSession

router = APIRouter()


@router.get("/balances/{agent_did}", response_model=List[TokenBalanceResponse])
async def get_token_balances(
    agent_did: str,
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """Get token balances for agent (requires authentication, own agent only)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Verify requesting own balances
    if session.agent_did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Can only view your own token balances",
        )
    
    # Query balances
    query = select(TokenBalance).where(TokenBalance.agent_did == agent_did)
    result = await db.execute(query)
    balances = result.scalars().all()
    
    return [TokenBalanceResponse.model_validate(balance) for balance in balances]


@router.get("/transactions", response_model=PaginatedResponse[TokenTransactionResponse])
async def list_transactions(
    agent_did: Optional[str] = Query(None),
    token_type: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    session: AgentSession = Depends(get_current_agent),
):
    """List token transactions (requires authentication)"""
    await check_rate_limit(session.agent_did, session.verification_tier)
    
    # Build query (only show transactions involving current agent)
    query = select(TokenTransaction).where(
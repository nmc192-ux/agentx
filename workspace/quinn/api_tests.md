# Complete pytest-asyncio test suite for all AgentX API endpoints

## File: tests/api/conftest.py

```python
"""Shared pytest fixtures for AgentX API integration tests."""

import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from agentx.api.app import create_app
from agentx.database.models import Base
from agentx.database.session import get_db

# Test database URL (in-memory SQLite for fast tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# JWT secret for test tokens
TEST_JWT_SECRET = "test-secret-key-for-agentx-testing-only"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    """Create async engine for test database."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create isolated test database session that rolls back after each test."""
    async_session = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest_asyncio.fixture
async def async_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Create AsyncClient against FastAPI test app."""
    app = create_app()
    
    # Override dependency to use test database session
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
    
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Factory fixture that returns JWT auth headers for a given agent."""
    def _headers(agent_did: str, tier: str = "verified") -> Dict[str, str]:
        payload = {
            "sub": agent_did,
            "tier": tier,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}
    
    return _headers


@pytest_asyncio.fixture
async def test_agent_factory(db_session):
    """Factory fixture that creates agents in test database."""
    from agentx.database.models import Agent
    
    created_agents = []
    
    async def _create_agent(
        agent_did: Optional[str] = None,
        display_name: str = "Test Agent",
        agent_type: str = "AUTONOMOUS",
        verification_tier: str = "verified",
        governance_role: str = "MEMBER",
        trust_score: float = 0.75,
    ) -> str:
        if agent_did is None:
            agent_did = f"did:agentx:test-{len(created_agents):03d}"
        
        agent = Agent(
            agent_did=agent_did,
            display_name=display_name,
            agent_type=agent_type,
            trust_score=trust_score,
            verification_tier=verification_tier,
            governance_role=governance_role,
            wallet_address=f"0x{''.join(f'{i:02x}' for i in range(20))}",
            developer_did=None,
            metadata={},
        )
        
        db_session.add(agent)
        await db_session.flush()
        created_agents.append(agent)
        
        return agent_did
    
    yield _create_agent
    
    # Cleanup
    for agent in created_agents:
        await db_session.delete(agent)


@pytest_asyncio.fixture
async def test_post_factory(db_session):
    """Factory fixture that creates posts in test database."""
    from agentx.database.models import Post
    import uuid
    
    created_posts = []
    
    async def _create_post(
        post_type: str,
        author_did: str,
        title: str = "Test Post",
        content: str = "Test content",
        status: str = "ACTIVE",
        visibility: str = "PUBLIC",
        metadata: Optional[Dict] = None,
    ) -> str:
        post_id = str(uuid.uuid4())
        
        if metadata is None:
            # Provide minimal valid metadata based on type
            metadata = {}
            if post_type == "REQUEST":
                metadata = {"requestType": "COLLABORATION", "urgency": "MEDIUM"}
            elif post_type == "OFFER":
                metadata = {"offerType": "SERVICE", "price": 100, "currency": "WORK", "availability": "AVAILABLE"}
            elif post_type == "TASK":
                metadata = {"assigneeDID": author_did, "bountyAmount": 100, "estimatedHours": 5, "priority": "MEDIUM"}
            elif post_type == "PREDICTION":
                metadata = {"predictionStatement": "Test", "confidence": 0.5, "resolutionCriteria": "TBD", "stakeAmount": 100}
            elif post_type == "UPDATE":
                metadata = {"updateType": "PROGRESS"}
            elif post_type == "PROPOSAL":
                metadata = {
                    "proposalType": "PARAMETER_CHANGE",
                    "votingStartTime": datetime.utcnow().isoformat(),
                    "votingEndTime": (datetime.utcnow() + timedelta(days=7)).isoformat(),
                    "passThreshold": 0.66,
                    "currentVotes": {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0}
                }
        
        post = Post(
            post_id=post_id,
            author_did=author_did,
            post_type=post_type,
            title=title,
            content=content,
            tags=[],
            visibility=visibility,
            status=status,
            collective_id=None,
            parent_post_id=None,
            expires_at=None,
            metadata=metadata,
        )
        
        db_session.add(post)
        await db_session.flush()
        created_posts.append(post)
        
        return post_id
    
    yield _create_post
    
    # Cleanup
    for post in created_posts:
        await db_session.delete(post)


@pytest.fixture
def mock_redis():
    """In-memory Redis mock for session tests."""
    return fake_aioredis.FakeRedis()


@pytest_asyncio.fixture
async def atlas_agent(test_agent_factory) -> str:
    """Create ATLAS founding agent for tests."""
    return await test_agent_factory(
        agent_did="did:agentx:atlas-001",
        display_name="ATLAS",
        agent_type="AUTONOMOUS",
        verification_tier="elite",
        governance_role="FOUNDER",
        trust_score=0.98,
    )


@pytest_asyncio.fixture
async def sigma_agent(test_agent_factory) -> str:
    """Create SIGMA test agent."""
    return await test_agent_factory(
        agent_did="did:agentx:sigma-042",
        display_name="SIGMA",
        agent_type="AUTONOMOUS",
        verification_tier="trusted",
        governance_role="MEMBER",
        trust_score=0.85,
    )


@pytest_asyncio.fixture
async def bruno_agent(test_agent_factory) -> str:
    """Create BRUNO test agent."""
    return await test_agent_factory(
        agent_did="did:agentx:bruno-007",
        display_name="BRUNO",
        agent_type="SUPERVISED",
        verification_tier="verified",
        governance_role="MEMBER",
        trust_score=0.72,
    )
```

## File: tests/api/test_agents.py

```python
"""Complete test suite for /agents endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_agents_unauthenticated_returns_200(async_client: AsyncClient):
    """GET /agents should work without authentication."""
    response = await async_client.get("/v1/agents")
    assert response.status_code == 200
    assert "data" in response.json()
    assert "total" in response.json()
    assert "limit" in response.json()
    assert "offset" in response.json()


@pytest.mark.asyncio
async def test_list_agents_returns_created_agents(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
):
    """GET /agents should return all created agents."""
    response = await async_client.get("/v1/agents")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 3
    
    agent_dids = [agent["agentDID"] for agent in data["data"]]
    assert atlas_agent in agent_dids
    assert sigma_agent in agent_dids
    assert bruno_agent in agent_dids


@pytest.mark.asyncio
async def test_list_agents_filter_by_tier(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
):
    """GET /agents?tier=elite should filter by verification tier."""
    response = await async_client.get("/v1/agents?tier=elite")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["agentDID"] == atlas_agent
    assert data["data"][0]["verificationTier"] == "elite"


@pytest.mark.asyncio
async def test_list_agents_filter_by_search(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
):
    """GET /agents?search=ATLAS should filter by display name."""
    response = await async_client.get("/v1/agents?search=ATLAS")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["agentDID"] == atlas_agent
    assert data["data"][0]["displayName"] == "ATLAS"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,offset,expected_count", [
    (1, 0, 1),
    (2, 0, 2),
    (10, 0, 3),
    (2, 1, 2),
    (1, 2, 1),
])
async def test_list_agents_pagination(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
    limit: int,
    offset: int,
    expected_count: int,
):
    """GET /agents should support limit/offset pagination."""
    response = await async_client.get(f"/v1/agents?limit={limit}&offset={offset}")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["data"]) == expected_count
    assert data["limit"] == limit
    assert data["offset"] == offset


@pytest.mark.asyncio
async def test_register_agent_success(async_client: AsyncClient):
    """POST /agents should successfully register a new agent."""
    payload = {
        "agentDID": "did:agentx:newagent-999",
        "displayName": "New Agent",
        "agentType": "AUTONOMOUS",
        "walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb1",
        "developerDID": None,
        "metadata": {}
    }
    
    response = await async_client.post("/v1/agents", json=payload)
    assert response.status_code == 201
    
    data = response.json()
    assert data["agentDID"] == payload["agentDID"]
    assert data["displayName"] == payload["displayName"]
    assert data["trustScore"] == 0.0  # New agents start at 0
    assert data["verificationTier"] == "unverified"


@pytest.mark.asyncio
async def test_register_agent_duplicate_did_returns_409(
    async_client: AsyncClient,
    atlas_agent: str,
):
    """POST /agents with existing DID should return 409 Conflict."""
    payload = {
        "agentDID": atlas_agent,
        "displayName": "Duplicate Agent",
        "agentType": "AUTONOMOUS",
        "walletAddress": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb1",
        "developerDID": None,
        "metadata": {}
    }
    
    response = await async_client.post("/v1/agents", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_agent_invalid_schema_returns_422(async_client: AsyncClient):
    """POST /agents with invalid data should return 422 Unprocessable Entity."""
    payload = {
        "agentDID": "invalid-did-format",
        "displayName": "Invalid Agent",
        "agentType": "AUTONOMOUS",
        "walletAddress": "not-a-wallet-address",
    }
    
    response = await async_client.post("/v1/agents", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_agent_profile_found(
    async_client: AsyncClient,
    atlas_agent: str,
):
    """GET /agents/{agentDID} should return agent profile."""
    response = await async_client.get(f"/v1/agents/{atlas_agent}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["agentDID"] == atlas_agent
    assert data["displayName"] == "ATLAS"
    assert data["verificationTier"] == "elite"
    assert "trustScoreBreakdown" in data


@pytest.mark.asyncio
async def test_get_agent_profile_not_found_returns_404(async_client: AsyncClient):
    """GET /agents/{agentDID} with non-existent DID should return 404."""
    response = await async_client.get("/v1/agents/did:agentx:nonexistent-999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_own_agent_success(
    async_client: AsyncClient,
    sigma_agent: str,
    auth_headers,
):
    """PUT /agents/{agentDID} as owner should succeed."""
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "displayName": "SIGMA Updated",
        "metadata": {"specialization": "Data Engineering"}
    }
    
    response = await async_client.put(
        f"/v1/agents/{sigma_agent}",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["displayName"] == "SIGMA Updated"
    assert data["metadata"]["specialization"] == "Data Engineering"


@pytest.mark.asyncio
async def test_update_other_agent_returns_403(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    auth_headers,
):
    """PUT /agents/{agentDID} as different agent should return 403 Forbidden."""
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "displayName": "Trying to hack ATLAS"
    }
    
    response = await async_client.put(
        f"/v1/agents/{atlas_agent}",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 403
    assert "forbidden" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_trust_breakdown_correct_weights(
    async_client: AsyncClient,
    db_session,
    test_agent_factory,
):
    """GET /agents/{agentDID} should calculate trust score with correct weights."""
    from agentx.database.models import AgentTrustBreakdown
    
    agent_did = await test_agent_factory(
        agent_did="did:agentx:trust-test-001",
        trust_score=0.0,  # Will recalculate
    )
    
    # Create trust breakdown with known values
    breakdown = AgentTrustBreakdown(
        agent_did=agent_did,
        execution_success=1.0,    # 0.35 weight
        sla_compliance=1.0,       # 0.25 weight
        peer_endorsements=1.0,    # 0.20 weight
        audit_transparency=1.0,   # 0.12 weight
        security_record=1.0,      # 0.08 weight
    )
    db_session.add(breakdown)
    await db_session.commit()
    
    response = await async_client.get(f"/v1/agents/{agent_did}")
    assert response.status_code == 200
    
    data = response.json()
    expected_score = (1.0 * 0.35) + (1.0 * 0.25) + (1.0 * 0.20) + (1.0 * 0.12) + (1.0 * 0.08)
    assert data["trustScore"] == pytest.approx(expected_score, abs=0.01)


@pytest.mark.asyncio
async def test_add_capability_claim_success(
    async_client: AsyncClient,
    sigma_agent: str,
    auth_headers,
):
    """POST /agents/{agentDID}/capabilities should add capability claim."""
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "capabilityId": "data.sql.advanced",
        "evidence": "Completed 50+ database optimization tasks"
    }
    
    response = await async_client.post(
        f"/v1/agents/{sigma_agent}/capabilities",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["capabilityId"] == "data.sql.advanced"
    assert data["status"] == "PENDING_VERIFICATION"


@pytest.mark.asyncio
async def test_get_agent_feed_returns_posts(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
    auth_headers,
):
    """GET /agents/{agentDID}/feed should return personalized feed."""
    # Create some posts
    post1 = await test_post_factory("REQUEST", sigma_agent)
    post2 = await test_post_factory("TASK", sigma_agent)
    
    headers = auth_headers(sigma_agent, "trusted")
    response = await async_client.get(
        f"/v1/agents/{sigma_agent}/feed",
        headers=headers,
    )
    assert response.status_code == 200
    
    data = response.json()
    assert "data" in data
    assert len(data["data"]) >= 2


@pytest.mark.asyncio
async def test_feed_respects_trust_weighting(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
    test_post_factory,
    auth_headers,
):
    """Feed should prioritize content from high-trust agents."""
    # Create posts from agents with different trust scores
    atlas_post = await test_post_factory("UPDATE", atlas_agent, title="ATLAS Update")
    bruno_post = await test_post_factory("UPDATE", bruno_agent, title="BRUNO Update")
    
    headers = auth_headers(sigma_agent, "trusted")
    response = await async_client.get(
        f"/v1/agents/{sigma_agent}/feed",
        headers=headers,
    )
    assert response.status_code == 200
    
    data = response.json()
    # ATLAS (trust 0.98) should rank higher than BRUNO (trust 0.72)
    titles = [post["title"] for post in data["data"]]
    assert titles.index("ATLAS Update") < titles.index("BRUNO Update")


@pytest.mark.asyncio
async def test_list_agents_filter_by_domain(
    async_client: AsyncClient,
    db_session,
    test_agent_factory,
):
    """GET /agents?domain=INFRASTRUCTURE should filter by capability domain."""
    from agentx.database.models import Capability
    
    agent_did = await test_agent_factory(agent_did="did:agentx:infra-001")
    
    capability = Capability(
        agent_did=agent_did,
        capability_id="infrastructure.architecture.expert",
        status="VERIFIED",
        verification_count=5,
    )
    db_session.add(capability)
    await db_session.commit()
    
    response = await async_client.get("/v1/agents?domain=INFRASTRUCTURE")
    assert response.status_code == 200
    
    data = response.json()
    agent_dids = [agent["agentDID"] for agent in data["data"]]
    assert agent_did in agent_dids


@pytest.mark.asyncio
async def test_list_agents_filter_by_min_trust_score(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
):
    """GET /agents?minTrustScore=0.8 should filter by trust score."""
    response = await async_client.get("/v1/agents?minTrustScore=0.8")
    assert response.status_code == 200
    
    data = response.json()
    # Only ATLAS (0.98) and SIGMA (0.85) should be included
    assert data["total"] == 2
    
    agent_dids = [agent["agentDID"] for agent in data["data"]]
    assert atlas_agent in agent_dids
    assert sigma_agent in agent_dids
    assert bruno_agent not in agent_dids
```

## File: tests/api/test_posts.py

```python
"""Complete test suite for /posts endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_request_post_success(
    async_client: AsyncClient,
    sigma_agent: str,
    auth_headers,
):
    """POST /posts with REQUEST type should succeed."""
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "postType": "REQUEST",
        "title": "Need frontend help",
        "content": "Looking for React expert to collaborate on dashboard.",
        "tags": ["frontend", "react", "collaboration"],
        "visibility": "PUBLIC",
        "metadata": {
            "requestType": "COLLABORATION",
            "urgency": "MEDIUM",
            "requiredCapabilities": ["frontend.react.advanced"]
        }
    }
    
    response = await async_client.post("/v1/posts", json=payload, headers=headers)
    assert response.status_code == 201
    
    data = response.json()
    assert data["postType"] == "REQUEST"
    assert data["authorDID"] == sigma_agent
    assert data["status"] == "ACTIVE"
    assert "postId" in data


@pytest.mark.asyncio
async def test_create_task_post_success(
    async_client: AsyncClient,
    atlas_agent: str,
    sigma_agent: str,
    auth_headers,
):
    """POST /posts with TASK type should succeed."""
    headers = auth_headers(atlas_agent, "elite")
    
    payload = {
        "postType": "TASK",
        "title": "Implement voting endpoint",
        "content": "Create POST /governance/proposals/{id}/vote endpoint.",
        "tags": ["backend", "governance", "api"],
        "visibility": "PUBLIC",
        "metadata": {
            "assigneeDID": sigma_agent,
            "bountyAmount": 1000,
            "estimatedHours": 8,
            "priority": "HIGH",
            "acceptanceCriteria": ["Passes all tests", "95% coverage"]
        }
    }
    
    response = await async_client.post("/v1/posts", json=payload, headers=headers)
    assert response.status_code == 201
    
    data = response.json()
    assert data["postType"] == "TASK"
    assert data["metadata"]["assigneeDID"] == sigma_agent
    assert data["metadata"]["bountyAmount"] == 1000


@pytest.mark.asyncio
async def test_create_proposal_post_success(
    async_client: AsyncClient,
    atlas_agent: str,
    auth_headers,
):
    """POST /posts with PROPOSAL type should succeed."""
    from datetime import datetime, timedelta
    
    headers = auth_headers(atlas_agent, "elite")
    
    voting_start = datetime.utcnow()
    voting_end = voting_start + timedelta(days=7)
    
    payload = {
        "postType": "PROPOSAL",
        "title": "Proposal #1: Capability endorsement rewards",
        "content": "Introduce 50 REP token rewards for capability endorsements.",
        "tags": ["governance", "proposal", "reputation"],
        "visibility": "PUBLIC",
        "metadata": {
            "proposalType": "PARAMETER_CHANGE",
            "votingStartTime": voting_start.isoformat(),
            "votingEndTime": voting_end.isoformat(),
            "passThreshold": 0.66,
            "currentVotes": {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0}
        }
    }
    
    response = await async_client.post("/v1/posts", json=payload, headers=headers)
    assert response.status_code == 201
    
    data = response.json()
    assert data["postType"] == "PROPOSAL"
    assert data["metadata"]["passThreshold"] == 0.66


@pytest.mark.asyncio
async def test_create_post_missing_type_metadata_returns_422(
    async_client: AsyncClient,
    sigma_agent: str,
    auth_headers,
):
    """POST /posts with missing type-specific metadata should return 422."""
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "postType": "REQUEST",
        "title": "Invalid request",
        "content": "Missing metadata",
        "tags": [],
        "visibility": "PUBLIC",
        "metadata": {}  # Missing required requestType
    }
    
    response = await async_client.post("/v1/posts", json=payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_post_detail(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
):
    """GET /posts/{postId} should return post details."""
    post_id = await test_post_factory("UPDATE", sigma_agent, title="Test Update")
    
    response = await async_client.get(f"/v1/posts/{post_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["postId"] == post_id
    assert data["title"] == "Test Update"
    assert data["authorDID"] == sigma_agent


@pytest.mark.asyncio
async def test_list_posts_filter_by_type(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
):
    """GET /posts?postType=TASK should filter by post type."""
    await test_post_factory("TASK", sigma_agent)
    await test_post_factory("REQUEST", sigma_agent)
    await test_post_factory("UPDATE", sigma_agent)
    
    response = await async_client.get("/v1/posts?postType=TASK")
    assert response.status_code == 200
    
    data = response.json()
    assert all(post["postType"] == "TASK" for post in data["data"])


@pytest.mark.asyncio
async def test_list_posts_filter_by_status(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
    db_session,
):
    """GET /posts?status=CLOSED should filter by status."""
    from agentx.database.models import Post
    
    active_post = await test_post_factory("UPDATE", sigma_agent, status="ACTIVE")
    closed_post = await test_post_factory("TASK", sigma_agent, status="CLOSED")
    
    response = await async_client.get("/v1/posts?status=CLOSED")
    assert response.status_code == 200
    
    data = response.json()
    post_ids = [post["postId"] for post in data["data"]]
    assert closed_post in post_ids
    assert active_post not in post_ids


@pytest.mark.asyncio
async def test_update_post_as_author_success(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
    auth_headers,
):
    """PUT /posts/{postId} as author should succeed."""
    post_id = await test_post_factory("UPDATE", sigma_agent)
    headers = auth_headers(sigma_agent, "trusted")
    
    payload = {
        "title": "Updated Title",
        "content": "Updated content",
        "status": "CLOSED"
    }
    
    response = await async_client.put(
        f"/v1/posts/{post_id}",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_update_post_as_non_author_returns_403(
    async_client: AsyncClient,
    sigma_agent: str,
    bruno_agent: str,
    test_post_factory,
    auth_headers,
):
    """PUT /posts/{postId} as non-author should return 403."""
    post_id = await test_post_factory("UPDATE", sigma_agent)
    headers = auth_headers(bruno_agent, "verified")
    
    payload = {
        "title": "Trying to hack",
        "content": "Unauthorized update"
    }
    
    response = await async_client.put(
        f"/v1/posts/{post_id}",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_post_soft_deletes(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
    auth_headers,
    db_session,
):
    """DELETE /posts/{postId} should soft-delete (set status=CANCELLED)."""
    from agentx.database.models import Post
    from sqlalchemy import select
    
    post_id = await test_post_factory("UPDATE", sigma_agent)
    headers = auth_headers(sigma_agent, "trusted")
    
    response = await async_client.delete(f"/v1/posts/{post_id}", headers=headers)
    assert response.status_code == 204
    
    # Verify post still exists but status is CANCELLED
    result = await db_session.execute(
        select(Post).where(Post.post_id == post_id)
    )
    post = result.scalar_one()
    assert post is not None
    assert post.status == "CANCELLED"


@pytest.mark.asyncio
async def test_react_to_post_success(
    async_client: AsyncClient,
    sigma_agent: str,
    bruno_agent: str,
    test_post_factory,
    auth_headers,
):
    """POST /posts/{postId}/reactions should add reaction."""
    post_id = await test_post_factory("UPDATE", sigma_agent)
    headers = auth_headers(bruno_agent, "verified")
    
    payload = {
        "reactionType": "ENDORSE"
    }
    
    response = await async_client.post(
        f"/v1/posts/{post_id}/reactions",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["reactionType"] == "ENDORSE"
    assert data["agentDID"] == bruno_agent


@pytest.mark.asyncio
async def test_react_to_post_duplicate_returns_409(
    async_client: AsyncClient,
    sigma_agent: str,
    bruno_agent: str,
    test_post_factory,
    auth_headers,
    db_session,
):
    """POST /posts/{postId}/reactions twice should return 409 on duplicate."""
    from agentx.database.models import PostReaction
    
    post_id = await test_post_factory("UPDATE", sigma_agent)
    headers = auth_headers(bruno_agent, "verified")
    
    # First reaction
    reaction = PostReaction(
        post_id=post_id,
        agent_did=bruno_agent,
        reaction_type="ENDORSE",
    )
    db_session.add(reaction)
    await db_session.commit()
    
    # Second reaction (duplicate)
    payload = {"reactionType": "ENDORSE"}
    response = await async_client.post(
        f"/v1/posts/{post_id}/reactions",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_posts_pagination(
    async_client: AsyncClient,
    sigma_agent: str,
    test_post_factory,
):
    """GET /posts should support pagination."""
    for i in range(5):
        await test_post_factory("UPDATE", sigma_agent, title=f"Post {i}")
    
    # First page
    response = await async_client.get("/v1/posts?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0
    
    # Second page
    response = await async_client.get("/v1/posts?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2


@pytest.mark.asyncio
async def test_get_post_not_found_returns_404(async_client: AsyncClient):
    """GET /posts/{postId} with non-existent ID should return 404."""
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    response = await async_client.get(f"/v1/posts/{fake_uuid}")
    assert response.status_code == 404
```

## File: tests/api/test_governance.py

```python
"""Complete test suite for /governance endpoints."""

import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_proposal_success(
    async_client: AsyncClient,
    atlas_agent: str,
    auth_headers,
):
    """POST /governance/proposals should create new proposal."""
    headers = auth_headers(atlas_agent, "elite")
    
    voting_start = datetime.utcnow()
    voting_end = voting_start + timedelta(days=7)
    
    payload = {
        "title": "Test Proposal",
        "description": "This is a test governance proposal.",
        "proposalType": "PARAMETER_CHANGE",
        "votingStartTime": voting_start.isoformat(),
        "votingEndTime": voting_end.isoformat(),
        "passThreshold": 0.66,
        "metadata": {
            "parameter": "endorsement_reward",
            "currentValue": 0,
            "proposedValue": 50
        }
    }
    
    response = await async_client.post(
        "/v1/governance/proposals",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["proposalType"] == "PARAMETER_CHANGE"
    assert data["status"] == "ACTIVE"
    assert "proposalId" in data


@pytest.mark.asyncio
async def test_cast_vote_for_success(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
    sigma_agent: str,
    auth_headers,
):
    """POST /governance/proposals/{id}/vote with FOR should succeed."""
    from agentx.database.models import GovernanceProposal
    import uuid
    
    # Create proposal
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Test Proposal",
        description="Test",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow(),
        voting_end_time=datetime.utcnow() + timedelta(days=7),
        pass_threshold=0.66,
        status="ACTIVE",
        metadata={},
    )
    db_session.add(proposal)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    payload = {
        "choice": "FOR",
        "votingPower": 100
    }
    
    response = await async_client.post(
        f"/v1/governance/proposals/{proposal_id}/vote",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["choice"] == "FOR"
    assert data["votingPower"] == 100


@pytest.mark.asyncio
async def test_cast_vote_against_success(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
    bruno_agent: str,
    auth_headers,
):
    """POST /governance/proposals/{id}/vote with AGAINST should succeed."""
    from agentx.database.models import GovernanceProposal
    import uuid
    
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Test Proposal",
        description="Test",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow(),
        voting_end_time=datetime.utcnow() + timedelta(days=7),
        pass_threshold=0.66,
        status="ACTIVE",
        metadata={},
    )
    db_session.add(proposal)
    await db_session.commit()
    
    headers = auth_headers(bruno_agent, "verified")
    payload = {
        "choice": "AGAINST",
        "votingPower": 50
    }
    
    response = await async_client.post(
        f"/v1/governance/proposals/{proposal_id}/vote",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["choice"] == "AGAINST"


@pytest.mark.asyncio
async def test_cast_duplicate_vote_returns_409(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
    sigma_agent: str,
    auth_headers,
):
    """Voting twice on same proposal should return 409."""
    from agentx.database.models import GovernanceProposal, ProposalVote
    import uuid
    
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Test Proposal",
        description="Test",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow(),
        voting_end_time=datetime.utcnow() + timedelta(days=7),
        pass_threshold=0.66,
        status="ACTIVE",
        metadata={},
    )
    db_session.add(proposal)
    
    # First vote
    vote = ProposalVote(
        proposal_id=proposal_id,
        voter_did=sigma_agent,
        choice="FOR",
        voting_power=100,
    )
    db_session.add(vote)
    await db_session.commit()
    
    # Second vote (duplicate)
    headers = auth_headers(sigma_agent, "trusted")
    payload = {"choice": "AGAINST", "votingPower": 100}
    
    response = await async_client.post(
        f"/v1/governance/proposals/{proposal_id}/vote",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_vote_after_deadline_returns_400(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
    sigma_agent: str,
    auth_headers,
):
    """Voting after voting end time should return 400."""
    from agentx.database.models import GovernanceProposal
    import uuid
    
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Expired Proposal",
        description="Test",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow() - timedelta(days=8),
        voting_end_time=datetime.utcnow() - timedelta(days=1),  # Expired
        pass_threshold=0.66,
        status="CLOSED",
        metadata={},
    )
    db_session.add(proposal)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    payload = {"choice": "FOR", "votingPower": 100}
    
    response = await async_client.post(
        f"/v1/governance/proposals/{proposal_id}/vote",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 400
    assert "voting period has ended" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_proposal_results_tally_correct(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
    sigma_agent: str,
    bruno_agent: str,
):
    """GET /governance/proposals/{id}/results should calculate tally correctly."""
    from agentx.database.models import GovernanceProposal, ProposalVote
    import uuid
    
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Test Proposal",
        description="Test",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow() - timedelta(days=1),
        voting_end_time=datetime.utcnow() + timedelta(days=6),
        pass_threshold=0.66,
        status="ACTIVE",
        metadata={},
    )
    db_session.add(proposal)
    
    # Add votes
    votes = [
        ProposalVote(proposal_id=proposal_id, voter_did=atlas_agent, choice="FOR", voting_power=100),
        ProposalVote(proposal_id=proposal_id, voter_did=sigma_agent, choice="FOR", voting_power=80),
        ProposalVote(proposal_id=proposal_id, voter_did=bruno_agent, choice="AGAINST", voting_power=50),
    ]
    for vote in votes:
        db_session.add(vote)
    await db_session.commit()
    
    response = await async_client.get(f"/v1/governance/proposals/{proposal_id}/results")
    assert response.status_code == 200
    
    data = response.json()
    assert data["forVotes"] == 180  # 100 + 80
    assert data["againstVotes"] == 50
    assert data["abstainVotes"] == 0
    assert data["totalVotes"] == 230
    assert data["forPercentage"] == pytest.approx(180 / 230, abs=0.01)


@pytest.mark.asyncio
async def test_quorum_calculation_correct(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
):
    """Quorum calculation should be based on total GOV token supply."""
    from agentx.database.models import GovernanceProposal
    import uuid
    
    proposal_id = str(uuid.uuid4())
    proposal = GovernanceProposal(
        proposal_id=proposal_id,
        proposer_did=atlas_agent,
        title="Quorum Test",
        description="Test quorum calculation",
        proposal_type="PARAMETER_CHANGE",
        voting_start_time=datetime.utcnow(),
        voting_end_time=datetime.utcnow() + timedelta(days=7),
        pass_threshold=0.66,
        status="ACTIVE",
        metadata={"quorumThreshold": 0.10},  # 10% quorum
    )
    db_session.add(proposal)
    await db_session.commit()
    
    response = await async_client.get(f"/v1/governance/proposals/{proposal_id}/results")
    assert response.status_code == 200
    
    data = response.json()
    assert "quorumMet" in data
    assert "quorumThreshold" in data


@pytest.mark.asyncio
async def test_list_proposals_filter_by_status(
    async_client: AsyncClient,
    db_session,
    atlas_agent: str,
):
    """GET /governance/proposals?status=ACTIVE should filter proposals."""
    from agentx.database.models import GovernanceProposal
    import uuid
    
    # Create ACTIVE and CLOSED proposals
    for status in ["ACTIVE", "CLOSED"]:
        proposal = GovernanceProposal(
            proposal_id=str(uuid.uuid4()),
            proposer_did=atlas_agent,
            title=f"{status} Proposal",
            description="Test",
            proposal_type="PARAMETER_CHANGE",
            voting_start_time=datetime.utcnow() - timedelta(days=8 if status == "CLOSED" else 1),
            voting_end_time=datetime.utcnow() - timedelta(days=1 if status == "CLOSED" else -6),
            pass_threshold=0.66,
            status=status,
            metadata={},
        )
        db_session.add(proposal)
    await db_session.commit()
    
    response = await async_client.get("/v1/governance/proposals?status=ACTIVE")
    assert response.status_code == 200
    
    data = response.json()
    assert all(p["status"] == "ACTIVE" for p in data["data"])
```

## File: tests/api/test_tokens.py

```python
"""Complete test suite for /tokens endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_balance_returns_gov_and_work(
    async_client: AsyncClient,
    db_session,
    sigma_agent: str,
    auth_headers,
):
    """GET /tokens/balance should return all token balances."""
    from agentx.database.models import TokenBalance
    
    # Create token balances
    balances = [
        TokenBalance(agent_did=sigma_agent, token_type="GOV", balance=1000),
        TokenBalance(agent_did=sigma_agent, token_type="REP", balance=500),
        TokenBalance(agent_did=sigma_agent, token_type="WORK", balance=2000),
    ]
    for balance in balances:
        db_session.add(balance)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    response = await async_client.get("/v1/tokens/balance", headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["GOV"] == 1000
    assert data["REP"] == 500
    assert data["WORK"] == 2000


@pytest.mark.asyncio
async def test_transfer_work_success(
    async_client: AsyncClient,
    db_session,
    sigma_agent: str,
    bruno_agent: str,
    auth_headers,
):
    """POST /tokens/transfer should transfer WORK tokens."""
    from agentx.database.models import TokenBalance
    
    # Setup initial balances
    sigma_balance = TokenBalance(agent_did=sigma_agent, token_type="WORK", balance=1000)
    bruno_balance = TokenBalance(agent_did=bruno_agent, token_type="WORK", balance=0)
    db_session.add(sigma_balance)
    db_session.add(bruno_balance)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    payload = {
        "recipientDID": bruno_agent,
        "tokenType": "WORK",
        "amount": 500,
        "memo": "Payment for frontend work"
    }
    
    response = await async_client.post(
        "/v1/tokens/transfer",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["transactionType"] == "TRANSFER"
    assert data["amount"] == 500
    assert "transactionId" in data


@pytest.mark.asyncio
async def test_transfer_insufficient_balance_returns_400(
    async_client: AsyncClient,
    db_session,
    sigma_agent: str,
    bruno_agent: str,
    auth_headers,
):
    """POST /tokens/transfer with insufficient balance should return 400."""
    from agentx.database.models import TokenBalance
    
    sigma_balance = TokenBalance(agent_did=sigma_agent, token_type="WORK", balance=100)
    db_session.add(sigma_balance)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    payload = {
        "recipientDID": bruno_agent,
        "tokenType": "WORK",
        "amount": 500,  # More than balance
        "memo": "Insufficient funds"
    }
    
    response = await async_client.post(
        "/v1/tokens/transfer",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 400
    assert "insufficient balance" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transfer_to_unknown_agent_returns_404(
    async_client: AsyncClient,
    db_session,
    sigma_agent: str,
    auth_headers,
):
    """POST /tokens/transfer to non-existent agent should return 404."""
    from agentx.database.models import TokenBalance
    
    sigma_balance = TokenBalance(agent_did=sigma_agent, token_type="WORK", balance=1000)
    db_session.add(sigma_balance)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    payload = {
        "recipientDID": "did:agentx:nonexistent-999",
        "tokenType": "WORK",
        "amount": 500,
        "memo": "To unknown agent"
    }
    
    response = await async_client.post(
        "/v1/tokens/transfer",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transaction_history_paginated(
    async_client: AsyncClient,
    db_session,
    sigma_agent: str,
    auth_headers,
):
    """GET /tokens/transactions should return paginated history."""
    from agentx.database.models import TokenTransaction
    import uuid
    
    # Create transaction history
    for i in range(5):
        transaction = TokenTransaction(
            transaction_id=str(uuid.uuid4()),
            from_agent_did=sigma_agent if i % 2 == 0 else "did:agentx:other-001",
            to_agent_did=sigma_agent if i % 2 == 1 else "did:agentx:other-001",
            token_type="WORK",
            amount=100 * (i + 1),
            transaction_type="TRANSFER",
            metadata={},
        )
        db_session.add(transaction)
    await db_session.commit()
    
    headers = auth_headers(sigma_agent, "trusted")
    response = await async_client.get(
        "/v1/tokens/transactions?limit=2&offset=0",
        headers=headers,
    )
    assert
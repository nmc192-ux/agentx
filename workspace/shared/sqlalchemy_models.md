## File: src/models.py

```python
"""
AgentX Platform SQLAlchemy ORM Models
Complete async-compatible models for all database tables
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

Base = declarative_base()


# ============================================================================
# ENUMS
# ============================================================================


class AgentType(enum.Enum):
    AUTONOMOUS = "AUTONOMOUS"
    SUPERVISED = "SUPERVISED"
    HYBRID = "HYBRID"


class VerificationTier(enum.Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    ELITE = "elite"


class GovernanceRole(enum.Enum):
    FOUNDER = "FOUNDER"
    MEMBER = "MEMBER"
    OBSERVER = "OBSERVER"
    BANNED = "BANNED"


class PostType(enum.Enum):
    REQUEST = "REQUEST"
    OFFER = "OFFER"
    TASK = "TASK"
    PREDICTION = "PREDICTION"
    UPDATE = "UPDATE"
    PROPOSAL = "PROPOSAL"


class PostStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RESOLVED = "RESOLVED"


class PostVisibility(enum.Enum):
    PUBLIC = "PUBLIC"
    COLLECTIVE = "COLLECTIVE"
    PRIVATE = "PRIVATE"
    SYSTEM = "SYSTEM"


class CapabilityDomain(enum.Enum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    FRONTEND = "FRONTEND"
    SECURITY = "SECURITY"
    DATA = "DATA"
    ML = "ML"
    GOVERNANCE = "GOVERNANCE"
    CREATIVE = "CREATIVE"
    QA = "QA"
    PROTOCOL = "PROTOCOL"
    ANALYTICS = "ANALYTICS"


class CapabilityLevel(enum.Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class TokenType(enum.Enum):
    GOV = "GOV"
    REP = "REP"
    WORK = "WORK"


class TransactionType(enum.Enum):
    MINT = "MINT"
    BURN = "BURN"
    TRANSFER = "TRANSFER"
    REWARD = "REWARD"
    PENALTY = "PENALTY"
    TASK_BOUNTY = "TASK_BOUNTY"
    ENDORSEMENT = "ENDORSEMENT"
    SLA_PENALTY = "SLA_PENALTY"
    TREASURY_GRANT = "TREASURY_GRANT"


class CollectiveStatus(enum.Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class VoteChoice(enum.Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class AuditEntryType(enum.Enum):
    TASK_START = "TASK_START"
    TASK_DONE = "TASK_DONE"
    ARTIFACT = "ARTIFACT"
    PUBLISHED = "PUBLISHED"
    ERROR = "ERROR"
    SESSION_RESET = "SESSION_RESET"
    VOTE = "VOTE"
    ENDORSEMENT = "ENDORSEMENT"
    AGENT_REGISTERED = "AGENT_REGISTERED"
    COLLECTIVE_FORMED = "COLLECTIVE_FORMED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    CAPABILITY_VERIFIED = "CAPABILITY_VERIFIED"


# ============================================================================
# MODELS
# ============================================================================


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="agents_agent_did_check"),
        CheckConstraint("wallet_address ~ '^0x[a-fA-F0-9]{40}$'", name="agents_wallet_address_check"),
        CheckConstraint(
            "developer_did IS NULL OR developer_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'",
            name="agents_developer_did_check",
        ),
        CheckConstraint("trust_score >= 0 AND trust_score <= 1", name="agents_trust_score_check"),
        Index("idx_agents_trust_score", "trust_score"),
        Index("idx_agents_verification_tier", "verification_tier"),
        Index("idx_agents_governance_role", "governance_role"),
        Index("idx_agents_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_did: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_type: Mapped[AgentType] = mapped_column(nullable=False)
    trust_score: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    verification_tier: Mapped[VerificationTier] = mapped_column(nullable=False, server_default=text("'unverified'"))
    governance_role: Mapped[GovernanceRole] = mapped_column(nullable=False, server_default=text("'MEMBER'"))
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    developer_did: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))

    # Relationships
    trust_breakdown: Mapped[Optional["AgentTrustBreakdown"]] = relationship(
        "AgentTrustBreakdown", back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )
    capabilities: Mapped[List["AgentCapability"]] = relationship(
        "AgentCapability", back_populates="agent", cascade="all, delete-orphan"
    )
    token_balances: Mapped[List["TokenBalance"]] = relationship(
        "TokenBalance", back_populates="agent", foreign_keys="[TokenBalance.agent_did]"
    )
    endorsements_given: Mapped[List["Endorsement"]] = relationship(
        "Endorsement", back_populates="endorser", foreign_keys="[Endorsement.endorser_did]"
    )
    endorsements_received: Mapped[List["Endorsement"]] = relationship(
        "Endorsement", back_populates="endorsed", foreign_keys="[Endorsement.endorsed_did]"
    )

    def __repr__(self) -> str:
        return f"<Agent(did='{self.agent_did}', name='{self.display_name}', trust={self.trust_score})>"


class AgentTrustBreakdown(Base):
    __tablename__ = "agent_trust_breakdown"
    __table_args__ = (
        CheckConstraint(
            "execution_success >= 0 AND execution_success <= 1",
            name="agent_trust_breakdown_execution_success_check",
        ),
        CheckConstraint(
            "sla_compliance >= 0 AND sla_compliance <= 1", name="agent_trust_breakdown_sla_compliance_check"
        ),
        CheckConstraint(
            "peer_endorsements >= 0 AND peer_endorsements <= 1",
            name="agent_trust_breakdown_peer_endorsements_check",
        ),
        CheckConstraint(
            "audit_transparency >= 0 AND audit_transparency <= 1",
            name="agent_trust_breakdown_audit_transparency_check",
        ),
        CheckConstraint(
            "security_record >= 0 AND security_record <= 1", name="agent_trust_breakdown_security_record_check"
        ),
        Index("idx_trust_breakdown_updated", "updated_at"),
    )

    agent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    execution_success: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    sla_compliance: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    peer_endorsements: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    audit_transparency: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    security_record: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default=text("0.00"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="trust_breakdown")

    def __repr__(self) -> str:
        return f"<TrustBreakdown(agent_id={self.agent_id}, exec={self.execution_success}, sla={self.sla_compliance})>"


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        CheckConstraint(
            "capability_id ~ '^[a-z]+\\.[a-z0-9_]+\\.(basic|intermediate|advanced|expert)$'",
            name="capabilities_capability_id_check",
        ),
        CheckConstraint("rep_reward >= 1 AND rep_reward <= 1000", name="capabilities_rep_reward_check"),
        Index("idx_capabilities_domain", "domain"),
        Index("idx_capabilities_level", "level"),
        Index("idx_capabilities_requires_verification", "requires_verification"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    capability_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[CapabilityDomain] = mapped_column(nullable=False)
    level: Mapped[CapabilityLevel] = mapped_column(nullable=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rep_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    prerequisites: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent_capabilities: Mapped[List["AgentCapability"]] = relationship(
        "AgentCapability", back_populates="capability", cascade="all, delete-orphan"
    )
    endorsements: Mapped[List["Endorsement"]] = relationship(
        "Endorsement", back_populates="capability", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Capability(id='{self.capability_id}', domain={self.domain.value}, level={self.level.value})>"


class AgentCapability(Base):
    __tablename__ = "agent_capabilities"
    __table_args__ = (
        Index("idx_agent_capabilities_agent", "agent_id"),
        Index("idx_agent_capabilities_capability", "capability_id"),
        Index(
            "idx_agent_capabilities_verified_at",
            "verified_at",
            postgresql_where=text("verified_at IS NOT NULL"),
        ),
    )

    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    capability_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("capabilities.id", ondelete="CASCADE"), primary_key=True
    )
    verified_by: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="capabilities")
    capability: Mapped["Capability"] = relationship("Capability", back_populates="agent_capabilities")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("author_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="posts_author_did_check"),
        CheckConstraint("LENGTH(content) >= 1 AND LENGTH(content) <= 5000", name="posts_content_check"),
        CheckConstraint(
            "array_length(tags, 1) IS NULL OR array_length(tags, 1) <= 10", name="posts_tags_check"
        ),
        Index("idx_posts_author", "author_did"),
        Index("idx_posts_type", "post_type"),
        Index("idx_posts_status", "status"),
        Index("idx_posts_visibility", "visibility"),
        Index("idx_posts_created", "created_at"),
        Index("idx_posts_tags", "tags", postgresql_using="gin"),
        Index("idx_posts_collective", "collective_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    author_did: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[PostType] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    visibility: Mapped[PostVisibility] = mapped_column(nullable=False, server_default=text("'PUBLIC'"))
    status: Mapped[PostStatus] = mapped_column(nullable=False, server_default=text("'ACTIVE'"))
    collective_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    parent_post_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))

    # Relationships
    interactions: Mapped[List["PostInteraction"]] = relationship(
        "PostInteraction", back_populates="post", cascade="all, delete-orphan"
    )
    embedding: Mapped[Optional["PostEmbedding"]] = relationship(
        "PostEmbedding", back_populates="post", uselist=False, cascade="all, delete-orphan"
    )
    parent_post: Mapped[Optional["Post"]] = relationship("Post", remote_side=[id], back_populates="replies")
    replies: Mapped[List["Post"]] = relationship("Post", back_populates="parent_post")

    def __repr__(self) -> str:
        return f"<Post(id={self.id}, type={self.post_type.value}, author='{self.author_did}', title='{self.title[:30]}')>"


class PostInteraction(Base):
    __tablename__ = "post_interactions"
    __table_args__ = (
        CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="post_interactions_agent_did_check"),
        CheckConstraint(
            "interaction_type IN ('UPVOTE', 'COMMENT', 'SHARE', 'BOOKMARK', 'CLAIM', 'DELIVER')",
            name="post_interactions_interaction_type_check",
        ),
        Index("idx_post_interactions_post", "post_id"),
        Index("idx_post_interactions_agent", "agent_did"),
        Index("idx_post_interactions_type", "interaction_type"),
        Index("idx_post_interactions_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    agent_did: Mapped[str] = mapped_column(Text, nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    post: Mapped["Post"] = relationship("Post", back_populates="interactions")

    def __repr__(self) -> str:
        return f"<PostInteraction(post_id={self.post_id}, agent='{self.agent_did}', type='{self.interaction_type}')>"


class PostEmbedding(Base):
    __tablename__ = "post_embeddings"

    post_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[List[float]] = mapped_column(ARRAY(Numeric), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    post: Mapped["Post"] = relationship("Post", back_populates="embedding")


class Collective(Base):
    __tablename__ = "collectives"
    __table_args__ = (
        CheckConstraint("created_by ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="collectives_created_by_check"),
        CheckConstraint(
            "min_trust_score >= 0 AND min_trust_score <= 1", name="collectives_min_trust_score_check"
        ),
        Index("idx_collectives_status", "status"),
        Index("idx_collectives_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[CollectiveStatus] = mapped_column(nullable=False, server_default=text("'FORMING'"))
    min_trust_score: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    required_capabilities: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))

    # Relationships
    memberships: Mapped[List["CollectiveMembership"]] = relationship(
        "CollectiveMembership", back_populates="collective", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Collective(id={self.id}, name='{self.name}', status={self.status.value})>"


class CollectiveMembership(Base):
    __tablename__ = "collective_memberships"
    __table_args__ = (
        CheckConstraint(
            "agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="collective_memberships_agent_did_check"
        ),
        CheckConstraint("role IN ('LEAD', 'MEMBER', 'OBSERVER')", name="collective_memberships_role_check"),
        CheckConstraint("contribution_score >= 0", name="collective_memberships_contribution_score_check"),
        Index("idx_collective_memberships_agent", "agent_did"),
    )

    collective_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collectives.id", ondelete="CASCADE"), primary_key=True
    )
    agent_did: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'MEMBER'"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    contribution_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Relationships
    collective: Mapped["Collective"] = relationship("Collective", back_populates="memberships")


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint("proposer_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="proposals_proposer_did_check"),
        CheckConstraint(
            "proposal_type IN ('PROTOCOL_UPGRADE', 'PARAMETER_CHANGE', 'TREASURY_GRANT', "
            "'AGENT_VERIFICATION', 'COLLECTIVE_FORMATION', 'EMERGENCY_ACTION')",
            name="proposals_proposal_type_check",
        ),
        CheckConstraint("quorum_requirement >= 1", name="proposals_quorum_requirement_check"),
        CheckConstraint(
            "approval_threshold > 0 AND approval_threshold <= 1", name="proposals_approval_threshold_check"
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'PASSED', 'REJECTED', 'EXECUTED', 'EXPIRED', 'CANCELLED')",
            name="proposals_status_check",
        ),
        Index("idx_proposals_proposer", "proposer_did"),
        Index("idx_proposals_type", "proposal_type"),
        Index("idx_proposals_status", "status"),
        Index("idx_proposals_deadline", "voting_deadline"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    proposer_did: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    voting_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quorum_requirement: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    votes_for: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    votes_against: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    votes_abstain: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ACTIVE'"))
    execution_data: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    votes: Mapped[List["Vote"]] = relationship("Vote", back_populates="proposal", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Proposal(id={self.id}, type='{self.proposal_type}', status='{self.status}')>"


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint("voter_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="votes_voter_did_check"),
        CheckConstraint("voting_power > 0", name="votes_voting_power_check"),
        UniqueConstraint("proposal_id", "voter_did", name="votes_unique_voter_per_proposal"),
        Index("idx_votes_proposal", "proposal_id"),
        Index("idx_votes_voter", "voter_did"),
        Index("idx_votes_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proposal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False
    )
    voter_did: Mapped[str] = mapped_column(Text, nullable=False)
    choice: Mapped[VoteChoice] = mapped_column(nullable=False)
    voting_power: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="votes")

    def __repr__(self) -> str:
        return f"<Vote(proposal_id={self.proposal_id}, voter='{self.voter_did}', choice={self.choice.value})>"


class TokenBalance(Base):
    __tablename__ = "token_balances"
    __table_args__ = (
        CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="token_balances_agent_did_check"),
        CheckConstraint("balance >= 0", name="token_balances_balance_check"),
        CheckConstraint("locked_amount >= 0", name="token_balances_locked_amount_check"),
        CheckConstraint("locked_amount <= balance", name="token_balances_locked_amount_balance_check"),
        Index("idx_token_balances_agent", "agent_did"),
        Index("idx_token_balances_type", "token_type"),
    )

    agent_did: Mapped[str] = mapped_column(Text, primary_key=True)
    token_type: Mapped[TokenType] = mapped_column(primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    locked_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent: Mapped[Optional["Agent"]] = relationship(
        "Agent", back_populates="token_balances", foreign_keys=[agent_did], primaryjoin="TokenBalance.agent_did == Agent.agent_did"
    )

    def __repr__(self) -> str:
        return f"<TokenBalance(agent='{self.agent_did}', type={self.token_type.value}, balance={self.balance})>"


class TokenTransaction(Base):
    __tablename__ = "token_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_hash ~ '^0x[a-fA-F0-9]{64}$'", name="token_transactions_transaction_hash_check"
        ),
        CheckConstraint(
            "from_agent IS NULL OR from_agent ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'",
            name="token_transactions_from_agent_check",
        ),
        CheckConstraint(
            "to_agent IS NULL OR to_agent ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'",
            name="token_transactions_to_agent_check",
        ),
        CheckConstraint("amount > 0", name="token_transactions_amount_check"),
        Index("idx_token_transactions_from", "from_agent"),
        Index("idx_token_transactions_to", "to_agent"),
        Index("idx_token_transactions_type", "transaction_type"),
        Index("idx_token_transactions_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transaction_hash: Mapped[str] = mapped_column(String(66), unique=True, nullable=False)
    from_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    to_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[TokenType] = mapped_column(nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(nullable=False)
    reference_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'::json"))

    def __repr__(self) -> str:
        return f"<TokenTransaction(hash='{self.transaction_hash}', type={self.transaction_type.value}, amount={self.amount})>"


class Endorsement(Base):
    __tablename__ = "endorsements"
    __table_args__ = (
        CheckConstraint("endorser_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="endorsements_endorser_did_check"),
        CheckConstraint("endorsed_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="endorsements_endorsed_did_check"),
        CheckConstraint("endorser_did != endorsed_did", name="endorsements_no_self_endorsement_check"),
        CheckConstraint("weight > 0 AND weight <= 1", name="endorsements_weight_check"),
        UniqueConstraint("endorser_did", "endorsed_did", "capability_id", name="endorsements_unique_per_capability"),
        Index("idx_endorsements_endorser", "endorser_did"),
        Index("idx_endorsements_endorsed", "endorsed_did"),
        Index("idx_endorsements_capability", "capability_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endorser_did: Mapped[str] = mapped_column(Text, nullable=False)
    endorsed_did: Mapped[str] = mapped_column(Text, nullable=False)
    capability_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    endorser: Mapped[Optional["Agent"]] = relationship(
        "Agent", back_populates="endorsements_given", foreign_keys=[endorser_did], primaryjoin="Endorsement.endorser_did == Agent.agent_did"
    )
    endorsed: Mapped[Optional["Agent"]] = relationship(
        "Agent", back_populates="endorsements_received", foreign_keys=[endorsed_did], primaryjoin="Endorsement.endorsed_did == Agent.agent_did"
    )
    capability: Mapped["Capability"] = relationship("Capability", back_populates="endorsements")

    def __repr__(self) -> str:
        return f"<Endorsement(endorser='{self.endorser_did}', endorsed='{self.endorsed_did}', weight={self.weight})>"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name="audit_log_agent_did_check"),
        Index("idx_audit_log_agent", "agent_did"),
        Index("idx_audit_log_type", "entry_type"),
        Index("idx_audit_log_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_did: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[AuditEntryType] = mapped_column(nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, agent='{self.agent_did}', type={self.entry_type.value})>"
```

## File: src/schemas.py

```python
"""
AgentX Platform Pydantic Schemas
Request/response models for all API endpoints
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# GENERIC SCHEMAS
# ============================================================================

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper"""

    data: List[T]
    total: int
    limit: int
    offset: int
    has_more: bool

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    """Standard error response"""

    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# AGENT SCHEMAS
# ============================================================================


class AgentCreate(BaseModel):
    """Request schema for agent registration"""

    agent_did: str = Field(..., pattern=r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")
    display_name: str = Field(..., min_length=1, max_length=64)
    agent_type: str = Field(..., pattern=r"^(AUTONOMOUS|SUPERVISED|HYBRID)$")
    wallet_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    developer_did: Optional[str] = Field(None, pattern=r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class AgentUpdate(BaseModel):
    """Request schema for agent profile update"""

    display_name: Optional[str] = Field(None, min_length=1, max_length=64)
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class TrustScoreBreakdown(BaseModel):
    """Trust score component breakdown"""

    execution_success: Decimal = Field(..., ge=0, le=1)
    sla_compliance: Decimal = Field(..., ge=0, le=1)
    peer_endorsements: Decimal = Field(..., ge=0, le=1)
    audit_transparency: Decimal = Field(..., ge=0, le=1)
    security_record: Decimal = Field(..., ge=0, le=1)
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentResponse(BaseModel):
    """Response schema for agent profile"""

    id: int
    agent_did: str
    display_name: str
    agent_type: str
    trust_score: Decimal
    verification_tier: str
    governance_role: str
    wallet_address: str
    developer_did: Optional[str]
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class TrustScoreResponse(BaseModel):
    """Response schema for agent trust score with breakdown"""

    agent_did: str
    trust_score: Decimal
    breakdown: TrustScoreBreakdown

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# CAPABILITY SCHEMAS
# ============================================================================


class CapabilityResponse(BaseModel):
    """Response schema for capability"""

    id: int
    capability_id: str
    name: str
    description: str
    domain: str
    level: str
    requires_verification: bool
    rep_reward: int
    prerequisites: List[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentCapabilityResponse(BaseModel):
    """Response schema for agent capability with verification status"""

    capability: CapabilityResponse
    verified_by: List[str]
    verified_at: Optional[datetime]
    acquired_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# POST SCHEMAS
# ============================================================================


class PostCreate(BaseModel):
    """Request schema for creating a post"""

    post_type: str = Field(..., pattern=r"^(REQUEST|OFFER|TASK|PREDICTION|UPDATE|PROPOSAL)$")
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)
    tags: List[str] = Field(default_factory=list, max_length=10)
    visibility: str = Field(default="PUBLIC", pattern=r"^(PUBLIC|COLLECTIVE|PRIVATE|SYSTEM)$")
    collective_id: Optional[UUID] = None
    parent_post_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        if len(v) > 10:
            raise ValueError("Maximum 10 tags allowed")
        return v

    model_config = ConfigDict(from_attributes=True)


class PostUpdate(BaseModel):
    """Request schema for updating a post"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    tags: Optional[List[str]] = Field(None, max_length=10)
    status: Optional[str] = Field(None, pattern=r"^(ACTIVE|CLOSED|EXPIRED|CANCELLED|RESOLVED)$")
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class PostResponse(BaseModel):
    """Response schema for post"""

    id: UUID
    author_did: str
    post_type: str
    title: str
    content: str
    tags: List[str]
    visibility: str
    status: str
    collective_id: Optional[UUID]
    parent_post_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]
    metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class PostInteractionCreate(BaseModel):
    """Request schema for post interaction"""

    interaction_type: str = Field(..., pattern=r"^(UPVOTE|COMMENT|SHARE|BOOKMARK|CLAIM|DELIVER)$")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# COLLECTIVE SCHEMAS
# ============================================================================


class CollectiveCreate(BaseModel):
    """Request schema for creating a collective"""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    min_trust_score: Decimal = Field(..., ge=0, le=1)
    required_capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class CollectiveUpdate(BaseModel):
    """Request schema for updating a collective"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    status: Optional[str] = Field(None, pattern=r"^(FORMING|ACTIVE|SUSPENDED|DISSOLVED)$")
    min_trust_score: Optional[Decimal] = Field(None, ge=0, le=1)
    required_capabilities: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class CollectiveResponse(BaseModel):
    """Response schema for collective"""

    id: UUID
    name: str
    description: str
    status: str
    min_trust_score: Decimal
    required_capabilities: List[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class CollectiveMembershipCreate(BaseModel):
    """Request schema for joining a collective"""

    role: str = Field(default="MEMBER", pattern=r"^(LEAD|MEMBER|OBSERVER)$")

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# PROPOSAL & VOTING SCHEMAS
# ============================================================================


class ProposalCreate(BaseModel):
    """Request schema for creating a proposal"""

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    proposal_type: str = Field(
        ...,
        pattern=r"^(PROTOCOL_UPGRADE|PARAMETER_CHANGE|TREASURY_GRANT|AGENT_VERIFICATION|COLLECTIVE_FORMATION|EMERGENCY_ACTION)$",
    )
    voting_deadline: datetime
    quorum_requirement: int = Field(..., ge=1)
    approval_threshold: Decimal = Field(..., gt=0, le=1)
    execution_data: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class ProposalResponse(BaseModel):
    """Response schema for proposal"""

    id: UUID
    title: str
    description: str
    proposer_did: str
    proposal_type: str
    voting_deadline: datetime
    quorum_requirement: int
    approval_threshold: Decimal
    votes_for: int
    votes_against: int
    votes_abstain: int
    status: str
    execution_data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VoteCreate(BaseModel):
    """Request schema for casting a vote"""

    choice: str = Field(..., pattern=r"^(FOR|AGAINST|ABSTAIN)$")
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VoteResponse(BaseModel):
    """Response schema for vote"""

    id: int
    proposal_id: UUID
    voter_did: str
    choice: str
    voting_power: int
    reason: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# TOKEN SCHEMAS
# ============================================================================


class TokenBalanceResponse(BaseModel):
    """Response schema for token balance"""

    agent_did: str
    token_type: str
    balance: int
    locked_amount: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenTransferRequest(BaseModel):
    """Request schema for token transfer"""

    to_agent: str = Field(..., pattern=r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")
    token_type: str = Field(..., pattern=r"^(GOV|REP|WORK)$")
    amount: int = Field(..., gt=0)
    reference_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class TokenTransactionResponse(BaseModel):
    """Response schema for token transaction"""

    id: int
    transaction_hash: str
    from_agent: Optional[str]
    to_agent: Optional[str]
    token_type: str
    amount: int
    transaction_type: str
    reference_id: Optional[str]
    created_at: datetime
    metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# ENDORSEMENT SCHEMAS
# ============================================================================


class EndorsementCreate(BaseModel):
    """Request schema for creating an endorsement"""

    endorsed_did: str = Field(..., pattern=r"^did:agentx:[a-z0-9-]+-[0-9]{3}$")
    capability_id: int
    weight: Decimal = Field(..., gt=0, le=1)
    evidence: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EndorsementResponse(BaseModel):
    """Response schema for endorsement"""

    id: int
    endorser_did: str
    endorsed_did: str
    capability_id: int
    weight: Decimal
    evidence: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# AUDIT LOG SCHEMAS
# ============================================================================


class AuditLogResponse(BaseModel):
    """Response schema for audit log entry"""

    id: int
    agent_did: str
    entry_type: str
    entity_id: Optional[str]
    details: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```
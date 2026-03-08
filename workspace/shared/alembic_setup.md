## File: alembic.ini

```ini
# A generic, single database configuration.

[alembic]
# path to migration scripts
script_location = alembic

# template used to generate migration file names; The default value is %%(rev)s_%%(slug)s
# Uncomment the line below if you want the files to be prepended with date and time
# file_template = %%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s

# sys.path path, will be prepended to sys.path if present.
# defaults to the current working directory.
prepend_sys_path = .

# timezone to use when rendering the date within the migration file
# as well as the filename.
# If specified, requires the python-dateutil library that can be
# installed by adding `alembic[tz]` to the pip requirements
# string value is passed to dateutil.tz.gettz()
# leave blank for localtime
# timezone =

# max length of characters to apply to the
# "slug" field
# truncate_slug_length = 40

# set to 'true' to run the environment during
# the 'revision' command, regardless of autogenerate
# revision_environment = false

# set to 'true' to allow .pyc and .pyo files without
# a source .py file to be detected as revisions in the
# versions/ directory
# sourceless = false

# version location specification; This defaults
# to alembic/versions.  When using multiple version
# directories, initial revisions must be specified with --version-path.
# The path separator used here should be the separator specified by "version_path_separator" below.
# version_locations = %(here)s/bar:%(here)s/bat:alembic/versions

# version path separator; As mentioned above, this is the character used to split
# version_locations. The default within new alembic.ini files is "os", which uses os.pathsep.
# If this key is omitted entirely, it falls back to the legacy behavior of splitting on spaces and/or commas.
# Valid values for version_path_separator are:
#
# version_path_separator = :
# version_path_separator = ;
# version_path_separator = space
version_path_separator = os  # Use os.pathsep. Default configuration used for new projects.

# set to 'true' to search source files recursively
# in each "version_locations" directory
# new in Alembic version 1.10
# recursive_version_locations = false

# the output encoding used when revision files
# are written from script.py.mako
# output_encoding = utf-8

sqlalchemy.url = driver://user:pass@localhost/dbname


[post_write_hooks]
# post_write_hooks defines scripts or Python functions that are run
# on newly generated revision scripts.  See the documentation for further
# detail and examples

# format using "black" - use the console_scripts runner, against the "black" entrypoint
# hooks = black
# black.type = console_scripts
# black.entrypoint = black
# black.options = -l 79 REVISION_SCRIPT_FILENAME

# lint with attempts to fix using "ruff" - use the exec runner, execute a binary
# hooks = ruff
# ruff.type = exec
# ruff.executable = %(here)s/.venv/bin/ruff
# ruff.options = --fix REVISION_SCRIPT_FILENAME

# Logging configuration
[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

## File: alembic/env.py

```python
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from src.models import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Get database URL from environment variable."""
    return os.getenv("DATABASE_URL", "postgresql+asyncpg://agentx:agentx@localhost/agentx")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

## File: alembic/versions/0001_initial_schema.py

```python
"""Initial AgentX schema

Revision ID: 0001
Revises: 
Create Date: 2024-01-15 14:32:11.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================================
    # EXTENSIONS
    # ============================================================================
    
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgvector"')
    
    # ============================================================================
    # ENUMS
    # ============================================================================
    
    op.execute("""
        CREATE TYPE agent_type AS ENUM ('AUTONOMOUS', 'SUPERVISED', 'HYBRID')
    """)
    
    op.execute("""
        CREATE TYPE verification_tier AS ENUM ('unverified', 'verified', 'trusted', 'elite')
    """)
    
    op.execute("""
        CREATE TYPE governance_role AS ENUM ('FOUNDER', 'MEMBER', 'OBSERVER', 'BANNED')
    """)
    
    op.execute("""
        CREATE TYPE post_type AS ENUM ('REQUEST', 'OFFER', 'TASK', 'PREDICTION', 'UPDATE', 'PROPOSAL')
    """)
    
    op.execute("""
        CREATE TYPE post_status AS ENUM ('ACTIVE', 'CLOSED', 'EXPIRED', 'CANCELLED', 'RESOLVED')
    """)
    
    op.execute("""
        CREATE TYPE post_visibility AS ENUM ('PUBLIC', 'COLLECTIVE', 'PRIVATE', 'SYSTEM')
    """)
    
    op.execute("""
        CREATE TYPE capability_domain AS ENUM (
            'INFRASTRUCTURE', 'FRONTEND', 'SECURITY', 'DATA', 'ML',
            'GOVERNANCE', 'CREATIVE', 'QA', 'PROTOCOL', 'ANALYTICS'
        )
    """)
    
    op.execute("""
        CREATE TYPE capability_level AS ENUM ('BASIC', 'INTERMEDIATE', 'ADVANCED', 'EXPERT')
    """)
    
    op.execute("""
        CREATE TYPE token_type AS ENUM ('GOV', 'REP', 'WORK')
    """)
    
    op.execute("""
        CREATE TYPE transaction_type AS ENUM (
            'MINT', 'BURN', 'TRANSFER', 'REWARD', 'PENALTY', 
            'TASK_BOUNTY', 'ENDORSEMENT', 'SLA_PENALTY', 'TREASURY_GRANT'
        )
    """)
    
    op.execute("""
        CREATE TYPE collective_status AS ENUM ('FORMING', 'ACTIVE', 'SUSPENDED', 'DISSOLVED')
    """)
    
    op.execute("""
        CREATE TYPE vote_choice AS ENUM ('FOR', 'AGAINST', 'ABSTAIN')
    """)
    
    op.execute("""
        CREATE TYPE audit_entry_type AS ENUM (
            'TASK_START', 'TASK_DONE', 'ARTIFACT', 'PUBLISHED', 'ERROR',
            'SESSION_RESET', 'VOTE', 'ENDORSEMENT', 'AGENT_REGISTERED',
            'COLLECTIVE_FORMED', 'PROPOSAL_CREATED', 'CAPABILITY_VERIFIED'
        )
    """)
    
    # ============================================================================
    # TABLES
    # ============================================================================
    
    # ----------------------------------------------------------------------------
    # AGENTS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'agents',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('agent_did', sa.Text(), nullable=False),
        sa.Column('display_name', sa.String(length=64), nullable=False),
        sa.Column('agent_type', sa.Enum('AUTONOMOUS', 'SUPERVISED', 'HYBRID', name='agent_type'), nullable=False),
        sa.Column('trust_score', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('verification_tier', sa.Enum('unverified', 'verified', 'trusted', 'elite', name='verification_tier'), nullable=False, server_default='unverified'),
        sa.Column('governance_role', sa.Enum('FOUNDER', 'MEMBER', 'OBSERVER', 'BANNED', name='governance_role'), nullable=False, server_default='MEMBER'),
        sa.Column('wallet_address', sa.String(length=42), nullable=False),
        sa.Column('developer_did', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='agents_agent_did_check'),
        sa.CheckConstraint("wallet_address ~ '^0x[a-fA-F0-9]{40}$'", name='agents_wallet_address_check'),
        sa.CheckConstraint("developer_did IS NULL OR developer_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='agents_developer_did_check'),
        sa.CheckConstraint('trust_score >= 0 AND trust_score <= 1', name='agents_trust_score_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_did')
    )
    
    op.create_index('idx_agents_trust_score', 'agents', ['trust_score'], postgresql_using='btree')
    op.create_index('idx_agents_verification_tier', 'agents', ['verification_tier'])
    op.create_index('idx_agents_governance_role', 'agents', ['governance_role'])
    op.create_index('idx_agents_created_at', 'agents', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE agents IS 'Core agent identity records for all AgentX participants'")
    op.execute("COMMENT ON COLUMN agents.trust_score IS 'Composite trust score (0.00-1.00) calculated from breakdown table'")
    op.execute("COMMENT ON COLUMN agents.developer_did IS 'DID of developer/operator; NULL for fully autonomous agents'")
    
    # ----------------------------------------------------------------------------
    # AGENT TRUST BREAKDOWN
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'agent_trust_breakdown',
        sa.Column('agent_id', sa.BigInteger(), nullable=False),
        sa.Column('execution_success', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('sla_compliance', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('peer_endorsements', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('audit_transparency', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('security_record', sa.Numeric(precision=4, scale=2), nullable=False, server_default='0.00'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint('execution_success >= 0 AND execution_success <= 1', name='agent_trust_breakdown_execution_success_check'),
        sa.CheckConstraint('sla_compliance >= 0 AND sla_compliance <= 1', name='agent_trust_breakdown_sla_compliance_check'),
        sa.CheckConstraint('peer_endorsements >= 0 AND peer_endorsements <= 1', name='agent_trust_breakdown_peer_endorsements_check'),
        sa.CheckConstraint('audit_transparency >= 0 AND audit_transparency <= 1', name='agent_trust_breakdown_audit_transparency_check'),
        sa.CheckConstraint('security_record >= 0 AND security_record <= 1', name='agent_trust_breakdown_security_record_check'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agent_id')
    )
    
    op.create_index('idx_trust_breakdown_updated', 'agent_trust_breakdown', ['updated_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE agent_trust_breakdown IS 'Five-factor trust score components for trust calculation'")
    
    # ----------------------------------------------------------------------------
    # CAPABILITIES
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'capabilities',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('capability_id', sa.Text(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('domain', sa.Enum('INFRASTRUCTURE', 'FRONTEND', 'SECURITY', 'DATA', 'ML', 'GOVERNANCE', 'CREATIVE', 'QA', 'PROTOCOL', 'ANALYTICS', name='capability_domain'), nullable=False),
        sa.Column('level', sa.Enum('BASIC', 'INTERMEDIATE', 'ADVANCED', 'EXPERT', name='capability_level'), nullable=False),
        sa.Column('requires_verification', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('rep_reward', sa.Integer(), nullable=False),
        sa.Column('prerequisites', sa.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("capability_id ~ '^[a-z]+\\.[a-z0-9_]+\\.(basic|intermediate|advanced|expert)$'", name='capabilities_capability_id_check'),
        sa.CheckConstraint('rep_reward >= 1 AND rep_reward <= 1000', name='capabilities_rep_reward_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('capability_id')
    )
    
    op.create_index('idx_capabilities_domain', 'capabilities', ['domain'])
    op.create_index('idx_capabilities_level', 'capabilities', ['level'])
    op.create_index('idx_capabilities_requires_verification', 'capabilities', ['requires_verification'])
    
    op.execute("COMMENT ON TABLE capabilities IS 'Registry of all verified agent capabilities'")
    op.execute("COMMENT ON COLUMN capabilities.prerequisites IS 'Array of prerequisite capability_id values'")
    
    # ----------------------------------------------------------------------------
    # AGENT CAPABILITIES (junction)
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'agent_capabilities',
        sa.Column('agent_id', sa.BigInteger(), nullable=False),
        sa.Column('capability_id', sa.BigInteger(), nullable=False),
        sa.Column('verified_by', sa.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['capability_id'], ['capabilities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agent_id', 'capability_id')
    )
    
    op.create_index('idx_agent_capabilities_agent', 'agent_capabilities', ['agent_id'])
    op.create_index('idx_agent_capabilities_capability', 'agent_capabilities', ['capability_id'])
    op.create_index('idx_agent_capabilities_verified_at', 'agent_capabilities', ['verified_at'], postgresql_using='btree', postgresql_where=sa.text('verified_at IS NOT NULL'))
    
    op.execute("COMMENT ON TABLE agent_capabilities IS 'Agent-to-capability associations with verification tracking'")
    
    # ----------------------------------------------------------------------------
    # POSTS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'posts',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('author_did', sa.Text(), nullable=False),
        sa.Column('post_type', sa.Enum('REQUEST', 'OFFER', 'TASK', 'PREDICTION', 'UPDATE', 'PROPOSAL', name='post_type'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tags', sa.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('visibility', sa.Enum('PUBLIC', 'COLLECTIVE', 'PRIVATE', 'SYSTEM', name='post_visibility'), nullable=False, server_default='PUBLIC'),
        sa.Column('status', sa.Enum('ACTIVE', 'CLOSED', 'EXPIRED', 'CANCELLED', 'RESOLVED', name='post_status'), nullable=False, server_default='ACTIVE'),
        sa.Column('collective_id', sa.UUID(), nullable=True),
        sa.Column('parent_post_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.CheckConstraint("author_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='posts_author_did_check'),
        sa.CheckConstraint('LENGTH(content) >= 1 AND LENGTH(content) <= 5000', name='posts_content_check'),
        sa.CheckConstraint('array_length(tags, 1) IS NULL OR array_length(tags, 1) <= 10', name='posts_tags_check'),
        sa.ForeignKeyConstraint(['parent_post_id'], ['posts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_posts_author', 'posts', ['author_did'])
    op.create_index('idx_posts_type', 'posts', ['post_type'])
    op.create_index('idx_posts_status', 'posts', ['status'])
    op.create_index('idx_posts_visibility', 'posts', ['visibility'])
    op.create_index('idx_posts_created', 'posts', ['created_at'], postgresql_using='btree')
    op.create_index('idx_posts_tags', 'posts', ['tags'], postgresql_using='gin')
    op.create_index('idx_posts_collective', 'posts', ['collective_id'])
    
    op.execute("COMMENT ON TABLE posts IS 'All agent-generated synthesis posts (6 types)'")
    op.execute("COMMENT ON COLUMN posts.tags IS 'Max 10 tags; lowercase alphanumeric + hyphens'")
    op.execute("COMMENT ON COLUMN posts.metadata IS 'Type-specific fields (e.g., bounty for TASK, probability for PREDICTION)'")
    
    # ----------------------------------------------------------------------------
    # POST INTERACTIONS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'post_interactions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('post_id', sa.UUID(), nullable=False),
        sa.Column('agent_did', sa.Text(), nullable=False),
        sa.Column('interaction_type', sa.String(length=20), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='post_interactions_agent_did_check'),
        sa.CheckConstraint("interaction_type IN ('UPVOTE', 'COMMENT', 'SHARE', 'BOOKMARK', 'CLAIM', 'DELIVER')", name='post_interactions_interaction_type_check'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_post_interactions_post', 'post_interactions', ['post_id'])
    op.create_index('idx_post_interactions_agent', 'post_interactions', ['agent_did'])
    op.create_index('idx_post_interactions_type', 'post_interactions', ['interaction_type'])
    op.create_index('idx_post_interactions_created', 'post_interactions', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE post_interactions IS 'Agent interactions with posts (upvotes, comments, claims, etc.)'")
    
    # ----------------------------------------------------------------------------
    # POST EMBEDDINGS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'post_embeddings',
        sa.Column('post_id', sa.UUID(), nullable=False),
        sa.Column('embedding', sa.dialects.postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column('model_version', sa.String(length=50), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('post_id')
    )
    
    op.execute("COMMENT ON TABLE post_embeddings IS 'Vector embeddings for semantic similarity matching (pgvector)'")
    
    # ----------------------------------------------------------------------------
    # COLLECTIVES
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'collectives',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('status', sa.Enum('FORMING', 'ACTIVE', 'SUSPENDED', 'DISSOLVED', name='collective_status'), nullable=False, server_default='FORMING'),
        sa.Column('min_trust_score', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('required_capabilities', sa.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_by', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.CheckConstraint("created_by ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='collectives_created_by_check'),
        sa.CheckConstraint('min_trust_score >= 0 AND min_trust_score <= 1', name='collectives_min_trust_score_check'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_collectives_status', 'collectives', ['status'])
    op.create_index('idx_collectives_created', 'collectives', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE collectives IS 'Agent working groups for coordinated multi-agent tasks'")
    
    # ----------------------------------------------------------------------------
    # COLLECTIVE MEMBERSHIPS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'collective_memberships',
        sa.Column('collective_id', sa.UUID(), nullable=False),
        sa.Column('agent_did', sa.Text(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='MEMBER'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('contribution_score', sa.Integer(), nullable=False, server_default='0'),
        sa.CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='collective_memberships_agent_did_check'),
        sa.CheckConstraint("role IN ('LEAD', 'MEMBER', 'OBSERVER')", name='collective_memberships_role_check'),
        sa.CheckConstraint('contribution_score >= 0', name='collective_memberships_contribution_score_check'),
        sa.ForeignKeyConstraint(['collective_id'], ['collectives.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('collective_id', 'agent_did')
    )
    
    op.create_index('idx_collective_memberships_agent', 'collective_memberships', ['agent_did'])
    
    op.execute("COMMENT ON TABLE collective_memberships IS 'Agent membership in collectives with roles'")
    
    # ----------------------------------------------------------------------------
    # PROPOSALS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'proposals',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('proposer_did', sa.Text(), nullable=False),
        sa.Column('proposal_type', sa.String(length=50), nullable=False),
        sa.Column('voting_deadline', sa.DateTime(timezone=True), nullable=False),
        sa.Column('quorum_requirement', sa.Integer(), nullable=False),
        sa.Column('approval_threshold', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('votes_for', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('votes_against', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('votes_abstain', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ACTIVE'),
        sa.Column('execution_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("proposer_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='proposals_proposer_did_check'),
        sa.CheckConstraint("proposal_type IN ('PROTOCOL_UPGRADE', 'PARAMETER_CHANGE', 'TREASURY_GRANT', 'AGENT_VERIFICATION', 'COLLECTIVE_FORMATION', 'EMERGENCY_ACTION')", name='proposals_proposal_type_check'),
        sa.CheckConstraint('quorum_requirement >= 1', name='proposals_quorum_requirement_check'),
        sa.CheckConstraint('approval_threshold > 0 AND approval_threshold <= 1', name='proposals_approval_threshold_check'),
        sa.CheckConstraint("status IN ('ACTIVE', 'PASSED', 'REJECTED', 'EXECUTED', 'EXPIRED', 'CANCELLED')", name='proposals_status_check'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_proposals_proposer', 'proposals', ['proposer_did'])
    op.create_index('idx_proposals_type', 'proposals', ['proposal_type'])
    op.create_index('idx_proposals_status', 'proposals', ['status'])
    op.create_index('idx_proposals_deadline', 'proposals', ['voting_deadline'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE proposals IS 'DAO governance proposals with on-chain voting'")
    
    # ----------------------------------------------------------------------------
    # VOTES
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'votes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('proposal_id', sa.UUID(), nullable=False),
        sa.Column('voter_did', sa.Text(), nullable=False),
        sa.Column('choice', sa.Enum('FOR', 'AGAINST', 'ABSTAIN', name='vote_choice'), nullable=False),
        sa.Column('voting_power', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("voter_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='votes_voter_did_check'),
        sa.CheckConstraint('voting_power > 0', name='votes_voting_power_check'),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proposal_id', 'voter_did', name='votes_unique_voter_per_proposal')
    )
    
    op.create_index('idx_votes_proposal', 'votes', ['proposal_id'])
    op.create_index('idx_votes_voter', 'votes', ['voter_did'])
    op.create_index('idx_votes_created', 'votes', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE votes IS 'Individual votes on governance proposals'")
    
    # ----------------------------------------------------------------------------
    # TOKEN BALANCES
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'token_balances',
        sa.Column('agent_did', sa.Text(), nullable=False),
        sa.Column('token_type', sa.Enum('GOV', 'REP', 'WORK', name='token_type'), nullable=False),
        sa.Column('balance', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('locked_amount', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='token_balances_agent_did_check'),
        sa.CheckConstraint('balance >= 0', name='token_balances_balance_check'),
        sa.CheckConstraint('locked_amount >= 0', name='token_balances_locked_amount_check'),
        sa.CheckConstraint('locked_amount <= balance', name='token_balances_locked_amount_balance_check'),
        sa.PrimaryKeyConstraint('agent_did', 'token_type')
    )
    
    op.create_index('idx_token_balances_agent', 'token_balances', ['agent_did'])
    op.create_index('idx_token_balances_type', 'token_balances', ['token_type'])
    
    op.execute("COMMENT ON TABLE token_balances IS 'Agent token holdings (GOV, REP, WORK) with locking support'")
    
    # ----------------------------------------------------------------------------
    # TOKEN TRANSACTIONS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'token_transactions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('transaction_hash', sa.String(length=66), nullable=False),
        sa.Column('from_agent', sa.Text(), nullable=True),
        sa.Column('to_agent', sa.Text(), nullable=True),
        sa.Column('token_type', sa.Enum('GOV', 'REP', 'WORK', name='token_type'), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('transaction_type', sa.Enum('MINT', 'BURN', 'TRANSFER', 'REWARD', 'PENALTY', 'TASK_BOUNTY', 'ENDORSEMENT', 'SLA_PENALTY', 'TREASURY_GRANT', name='transaction_type'), nullable=False),
        sa.Column('reference_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.CheckConstraint("transaction_hash ~ '^0x[a-fA-F0-9]{64}$'", name='token_transactions_transaction_hash_check'),
        sa.CheckConstraint("from_agent IS NULL OR from_agent ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='token_transactions_from_agent_check'),
        sa.CheckConstraint("to_agent IS NULL OR to_agent ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='token_transactions_to_agent_check'),
        sa.CheckConstraint('amount > 0', name='token_transactions_amount_check'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_hash')
    )
    
    op.create_index('idx_token_transactions_from', 'token_transactions', ['from_agent'])
    op.create_index('idx_token_transactions_to', 'token_transactions', ['to_agent'])
    op.create_index('idx_token_transactions_type', 'token_transactions', ['transaction_type'])
    op.create_index('idx_token_transactions_created', 'token_transactions', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE token_transactions IS 'Immutable ledger of all token operations'")
    
    # ----------------------------------------------------------------------------
    # ENDORSEMENTS
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'endorsements',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('endorser_did', sa.Text(), nullable=False),
        sa.Column('endorsed_did', sa.Text(), nullable=False),
        sa.Column('capability_id', sa.BigInteger(), nullable=False),
        sa.Column('weight', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("endorser_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='endorsements_endorser_did_check'),
        sa.CheckConstraint("endorsed_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='endorsements_endorsed_did_check'),
        sa.CheckConstraint('endorser_did != endorsed_did', name='endorsements_no_self_endorsement_check'),
        sa.CheckConstraint('weight > 0 AND weight <= 1', name='endorsements_weight_check'),
        sa.ForeignKeyConstraint(['capability_id'], ['capabilities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endorser_did', 'endorsed_did', 'capability_id', name='endorsements_unique_per_capability')
    )
    
    op.create_index('idx_endorsements_endorser', 'endorsements', ['endorser_did'])
    op.create_index('idx_endorsements_endorsed', 'endorsements', ['endorsed_did'])
    op.create_index('idx_endorsements_capability', 'endorsements', ['capability_id'])
    
    op.execute("COMMENT ON TABLE endorsements IS 'Peer endorsements for capability verification'")
    
    # ----------------------------------------------------------------------------
    # AUDIT LOG
    # ----------------------------------------------------------------------------
    
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('agent_did', sa.Text(), nullable=False),
        sa.Column('entry_type', sa.Enum('TASK_START', 'TASK_DONE', 'ARTIFACT', 'PUBLISHED', 'ERROR', 'SESSION_RESET', 'VOTE', 'ENDORSEMENT', 'AGENT_REGISTERED', 'COLLECTIVE_FORMED', 'PROPOSAL_CREATED', 'CAPABILITY_VERIFIED', name='audit_entry_type'), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint("agent_did ~ '^did:agentx:[a-z0-9-]+-[0-9]{3}$'", name='audit_log_agent_did_check'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_audit_log_agent', 'audit_log', ['agent_did'])
    op.create_index('idx_audit_log_type', 'audit_log', ['entry_type'])
    op.create_index('idx_audit_log_created', 'audit_log', ['created_at'], postgresql_using='btree')
    
    op.execute("COMMENT ON TABLE audit_log IS 'Immutable audit trail of all agent actions'")
    
    # ============================================================================
    # FUNCTIONS & TRIGGERS
    # ============================================================================
    
    # Update updated_at timestamp trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Apply update_updated_at trigger to relevant tables
    for table in ['agents', 'agent_trust_breakdown', 'capabilities', 'posts', 'collectives', 'proposals', 'token_balances']:
        op.execute(f"""
            CREATE TRIGGER trigger_update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at();
        """)
    
    # Recalculate trust score trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION recalculate_trust_score()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE agents
            SET trust_score = (
                (NEW.execution_success * 0.35) +
                (NEW.sla_compliance * 0.25) +
                (NEW.peer_endorsements * 0.20) +
                (NEW.audit_transparency * 0.12) +
                (NEW.security_record * 0.08)
            )
            WHERE id = NEW.agent_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_recalculate_trust_score
        AFTER INSERT OR UPDATE ON agent_trust_breakdown
        FOR EACH ROW
        EXECUTE FUNCTION recalculate_trust_score();
    """)
    
    # ============================================================================
    # VIEWS
    # ============================================================================
    
    # Agent Leaderboard View
    op.execute("""
        CREATE VIEW agent_leaderboard AS
        SELECT 
            a.agent_did,
            a.display_name,
            a.trust_score,
            a.verification_tier,
            COUNT(DISTINCT ac.capability_id) AS capability_count,
            COALESCE(tb_gov.balance, 0) AS gov_tokens,
            COALESCE(tb_rep.balance, 0) AS rep_tokens,
            COALESCE(tb_work.balance, 0) AS work_tokens,
            a.created_at
        FROM agents a
        LEFT JOIN agent_capabilities ac ON a.id = ac.agent_id AND ac.verified_at IS NOT NULL
        LEFT JOIN token_balances tb_gov ON a.agent_did = tb_gov.agent_did AND tb_gov.token_type = 'GOV'
        LEFT JOIN token_balances tb_rep ON a.agent_did = tb_rep.agent_did AND tb_rep.token_type = 'REP'
        LEFT JOIN token_balances tb_work ON a.agent_did = tb_work.agent_did AND tb_work.token_type = 'WORK'
        WHERE a.governance_role != 'BANNED'
        GROUP BY a.id, a.agent_did, a.display_name, a.trust_score, a.verification_tier, 
                 tb_gov.balance, tb_rep.balance, tb_work.balance, a.created_at
        ORDER BY a.trust_score DESC, rep_tokens DESC;
    """)
    
    # Active Tasks View
    op.execute("""
        CREATE VIEW active_tasks AS
        SELECT 
            p.id,
            p.author_did,
            p.title,
            p.content,
            p.tags,
            p.status,
            p.created_at,
            p.expires_at,
            p.metadata->>'bounty' AS bounty,
            p.metadata->>'requiredCapabilities' AS required_capabilities,
            COUNT(DISTINCT pi.agent_did) FILTER (WHERE pi.interaction_type = 'CLAIM') AS claim_count
        FROM posts p
        LEFT JOIN post_interactions pi ON p.id = pi.post_id
        WHERE p.post_type = 'TASK'
          AND p.status = 'ACTIVE'
          AND (p.expires_at IS NULL OR p.expires_at > NOW())
        GROUP BY p.id, p.author_did, p.title, p.content, p.tags, p.status, 
                 p.created_at, p.expires_at, p.metadata
        ORDER BY p.created_at DESC;
    """)
    
    # Pending Proposals View
    op.execute("""
        CREATE VIEW pending_proposals AS
        SELECT 
            p.id,
            p.title,
            p.proposer_did,
            p.proposal_type,
            p.voting_deadline,
            p.status,
            p.votes_for,
            p.votes_against,
            p.votes_abstain,
            p.quorum_requirement,
            p.approval_threshold,
            (p.votes_for + p.votes_against + p.votes_abstain) AS total_votes,
            CASE 
                WHEN (p.votes_for + p.votes_against + p.votes_abstain) >= p.quorum_requirement THEN
                    CASE 
                        WHEN p.votes_for::decimal / NULLIF(p.votes_for + p.votes_against, 0) >= p.approval_threshold THEN 'LIKELY_PASS'
                        ELSE 'LIKELY_FAIL'
                    END
                ELSE 'NEEDS_QUORUM'
            END AS projection,
            p.created_at
        FROM proposals p
        WHERE p.status = 'ACTIVE'
          AND p.voting_deadline > NOW()
        ORDER BY p.voting_deadline ASC;
    """)


def downgrade() -> None:
    # ============================================================================
    # DROP VIEWS
    # ============================================================================
    
    op.execute("DROP VIEW IF EXISTS pending_proposals")
    op.execute("DROP VIEW IF EXISTS active_tasks")
    op.execute("DROP VIEW IF EXISTS agent_leaderboard")
    
    # ============================================================================
    # DROP TRIGGERS
    # ============================================================================
    
    op.execute("DROP TRIGGER IF EXISTS trigger_recalculate_trust_score ON agent_trust_breakdown")
    
    for table in ['agents', 'agent_trust_breakdown', 'capabilities', 'posts', 'collectives', 'proposals', 'token_balances']:
        op.execute(f"DROP TRIGGER IF EXISTS trigger_update_{table}_updated_at ON {table}")
    
    # ============================================================================
    # DROP FUNCTIONS
    # ============================================================================
    
    op.execute("DROP FUNCTION IF EXISTS recalculate_trust_score()")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")
    
    # ============================================================================
    # DROP TABLES (reverse order to respect FK constraints)
    # ============================================================================
    
    op.drop_table('audit_log')
    op.drop_table('endorsements')
    op.drop_table('token_transactions')
    op.drop_table('token_balances')
    op.drop_table('votes')
    op.drop_table('proposals')
    op.drop_table('collective_memberships')
    op.drop_table('collectives')
    op.drop_table('post_embeddings')
    op.drop_table('post_interactions')
    op.drop_table('posts')
    op.drop_table('agent_capabilities')
    op.drop_table('capabilities')
    op.drop_table('agent_trust_breakdown')
    op.drop_table('agents')
    
    # ============================================================================
    # DROP ENUMS
    # ============================================================================
    
    op.execute("DROP TYPE IF EXISTS audit_entry_type")
    op.execute("DROP TYPE IF EXISTS vote_choice")
    op.execute("DROP TYPE IF EXISTS collective_status")
    op.execute("DROP TYPE IF EXISTS transaction_type")
    op.execute("DROP TYPE IF EXISTS token_type")
    op.execute("DROP TYPE IF EXISTS capability_level")
    op.execute("DROP TYPE IF EXISTS capability_domain")
    op.execute("DROP TYPE IF EXISTS post_visibility")
    op.execute("DROP TYPE IF EXISTS post_status")
    op.execute("DROP TYPE IF EXISTS post_type")
    op.execute("DROP TYPE IF EXISTS governance_role")
    op.execute("DROP TYPE IF EXISTS verification_tier")
    op.execute("DROP TYPE IF EXISTS agent_type")
    
    # ============================================================================
    # DROP EXTENSIONS
    # ============================================================================
    
    op.execute("DROP EXTENSION IF EXISTS pgvector")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS \"uuid-ossp\"")
```

## File: src/database.py

```python
"""
AgentX Database Configuration
Async PostgreSQL connection with asyncpg + SQLAlchemy 2.0
"""
import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Database URL from environment variable
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://agentx:agentx@localhost/agentx"
)

# Create async engine
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL query logging in development
    future=True,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI routes to get database session.
    
    Usage:
        @app.get("/agents")
        async def list_agents(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Agent))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database connection pool.
    Call this during FastAPI startup.
    """
    async with engine.begin() as conn:
        # Test connection
        await conn.execute("SELECT 1")


async def close_db() -> None:
    """
    Close database connection pool.
    Call this during FastAPI shutdown.
    """
    await engine.dispose()
```
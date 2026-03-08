"""Alembic migration environment for AgentX Platform."""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Add src/ to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

settings = get_settings()
target_metadata = None   # add SQLAlchemy Base.metadata here in Sprint 2


def run_migrations_offline() -> None:
    context.configure(
        url=settings.postgres_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        settings.postgres_dsn,
        poolclass=pool.NullPool,
        connect_args={
            "ssl": "require" if settings.postgres_ssl_mode == "require" else None,
        },
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

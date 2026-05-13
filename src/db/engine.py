"""Database engine and session factory."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import config
from src.db.base import Base

# Create async engine
engine = create_async_engine(
    config.db.url,
    echo=config.db.echo,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database - create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_schema(conn)


async def _ensure_schema(conn) -> None:
    """Apply minimal schema updates for existing databases."""
    await conn.execute(
        text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'expert_organizer'")
    )
    await conn.execute(
        text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS registered_by_code BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS invite_role VARCHAR(50)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE invite_codes "
            "ADD COLUMN IF NOT EXISTS campaign_id INTEGER"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_invite_codes_campaign_id "
            "ON invite_codes (campaign_id)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE campaigns "
            "ADD COLUMN IF NOT EXISTS p2p_reviews_required INTEGER NOT NULL DEFAULT 3"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE campaigns "
            "ADD COLUMN IF NOT EXISTS voting_type VARCHAR(20)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE campaigns "
            "ADD COLUMN IF NOT EXISTS campaign_deadline_at TIMESTAMPTZ"
        )
    )
    await conn.execute(
        text(
            "UPDATE campaigns "
            "SET campaign_deadline_at = created_at + INTERVAL '7 days' "
            "WHERE campaign_deadline_at IS NULL"
        )
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
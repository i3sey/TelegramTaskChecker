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
from src.db import models as _db_models  # noqa: F401
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
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_type
                    WHERE typname = 'user_role'
                ) THEN
                    ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'expert_organizer';
                END IF;
            END
            $$;
            """
        )
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
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS campaign_id INTEGER"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_users_campaign_id "
            "ON users (campaign_id)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS last_google_file_id VARCHAR(255)"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS web_access_token VARCHAR(64)"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_web_access_token "
            "ON users (web_access_token) "
            "WHERE web_access_token IS NOT NULL"
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
            "ADD COLUMN IF NOT EXISTS organizer_id BIGINT"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_campaigns_organizer_id "
            "ON campaigns (organizer_id)"
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
            "ADD COLUMN IF NOT EXISTS campaign_deadline_at TIMESTAMPTZ"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE campaigns "
            "ADD COLUMN IF NOT EXISTS allow_resubmission_after_review "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE campaigns "
            "ADD COLUMN IF NOT EXISTS allow_resubmission_before_review "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    await conn.execute(
        text(
            "UPDATE campaigns "
            "SET campaign_deadline_at = created_at + INTERVAL '7 days' "
            "WHERE campaign_deadline_at IS NULL"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE reviews "
            "ADD COLUMN IF NOT EXISTS criteria_scores TEXT"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE submissions "
            "ADD COLUMN IF NOT EXISTS p2p_completed_at TIMESTAMPTZ"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_submissions_p2p_completed_at "
            "ON submissions (p2p_completed_at)"
        )
    )
    await conn.execute(
        text(
            """
            DELETE FROM reviews duplicate
            USING reviews original
            WHERE duplicate.submission_id = original.submission_id
              AND duplicate.reviewer_id = original.reviewer_id
              AND duplicate.id > original.id
            """
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_submission_reviewer "
            "ON reviews (submission_id, reviewer_id)"
        )
    )
    await conn.execute(
        text(
            """
            UPDATE submissions AS submission
            SET p2p_completed_at = COALESCE(submission.updated_at, submission.created_at)
            FROM campaigns AS campaign
            WHERE submission.campaign_id = campaign.id
              AND campaign.type = 'P2P'
              AND submission.p2p_completed_at IS NULL
              AND (
                    SELECT COUNT(*)
                    FROM reviews AS review
                    JOIN submissions AS reviewed_submission
                      ON reviewed_submission.id = review.submission_id
                    WHERE review.reviewer_id = submission.author_id
                      AND reviewed_submission.campaign_id = submission.campaign_id
                  ) >= campaign.p2p_reviews_required
            """
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

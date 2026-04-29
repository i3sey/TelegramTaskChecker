"""Invite service for role-based access links."""
from __future__ import annotations

import secrets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import InviteCode
from src.utils.logging import logger


def generate_invite_code(length: int = 10) -> str:
    """Generate a short URL-safe invite code."""
    # token_urlsafe returns roughly 1.3 chars per byte
    return secrets.token_urlsafe(length)[:length]


async def create_invite(
    role: str,
    created_by: int,
    session: AsyncSession,
    max_uses: int | None = None,
) -> InviteCode:
    """Create a new invite code for a role."""
    code = generate_invite_code()
    invite = InviteCode(
        code=code,
        role=role,
        created_by=created_by,
        max_uses=max_uses,
    )
    session.add(invite)
    await session.flush()
    logger.info(f"Created invite code {code} for role {role} by {created_by}")
    return invite


async def get_invite_by_code(code: str, session: AsyncSession) -> InviteCode | None:
    """Get invite by code."""
    result = await session.execute(
        select(InviteCode).where(InviteCode.code == code)
    )
    return result.scalar_one_or_none()


async def mark_invite_used(invite: InviteCode, session: AsyncSession) -> None:
    """Increment invite usage count."""
    invite.uses += 1
    await session.flush()


def is_invite_valid(invite: InviteCode | None) -> bool:
    """Validate invite state and usage limits."""
    if invite is None or not invite.is_active:
        return False
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return False
    return True

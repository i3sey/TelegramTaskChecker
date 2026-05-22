"""Invite service for role-based access links."""
from __future__ import annotations

import secrets
import string
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import InviteCode
from src.bot.utils.logging import logger


def generate_invite_code(length: int = 10) -> str:
    """Generate a Telegram deep-link safe invite code."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def create_invite(
    role: str,
    created_by: int,
    campaign_id: int,
    session: AsyncSession,
    max_uses: int | None = None,
) -> InviteCode:
    """Create a new invite code for a role."""
    code = generate_invite_code()
    invite = InviteCode(
        code=code,
        role=role,
        campaign_id=campaign_id,
        created_by=created_by,
        max_uses=max_uses,
    )
    session.add(invite)
    await session.flush()
    logger.info(
        f"Created invite code {code} for role {role} by {created_by} for campaign {campaign_id}"
    )
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

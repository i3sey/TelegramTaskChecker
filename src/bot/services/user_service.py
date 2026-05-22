"""User service for database operations."""

import secrets

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import CampaignAccess, User, UserRole
from src.bot.utils.logging import logger

ROLE_ALIASES: dict[str, UserRole] = {role.value: role for role in UserRole}

class UserService:
    """Service for user-related database operations."""

    @staticmethod
    async def get_user(tg_id: int, session: AsyncSession) -> User | None:
        """
        Get user by Telegram ID.

        Args:
            tg_id: Telegram user ID
            session: Database session

        Returns:
            User object or None if not found
        """
        result = await session.execute(
            select(User).where(User.tg_id == tg_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def generate_unique_web_access_token(session: AsyncSession) -> str:
        """Generate unique web access token for organizer web access."""
        while True:
            token = secrets.token_urlsafe(24)
            result = await session.execute(
                select(User.tg_id).where(User.web_access_token == token)
            )
            if result.scalar_one_or_none() is None:
                return token

    @staticmethod
    async def ensure_web_access_token(user: User, session: AsyncSession) -> str:
        """Ensure organizer has a web access token."""
        if user.web_access_token:
            return user.web_access_token

        user.web_access_token = await UserService.generate_unique_web_access_token(session)
        await session.flush()
        logger.info(f"Generated web access token for user {user.tg_id}")
        return user.web_access_token

    @staticmethod
    async def create_user(
        tg_id: int,
        full_name: str,
        study_group: str | None,
        session: AsyncSession,
        role: UserRole = UserRole.STUDENT,
        registered_by_code: bool = False,
        invite_role: str | None = None,
        campaign_id: int | None = None,
    ) -> User:
        """
        Create a new user.

        Args:
            tg_id: Telegram user ID
            full_name: User's full name
            study_group: User's study group
            session: Database session
            role: User role (default: STUDENT)

        Returns:
            Created User object
        """
        user = User(
            tg_id=tg_id,
            full_name=full_name,
            study_group=study_group,
            role=role,
            registered_by_code=registered_by_code,
            invite_role=invite_role,
            campaign_id=campaign_id,
        )
        session.add(user)
        await session.flush()

        if role in {UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER}:
            await UserService.ensure_web_access_token(user, session)

        logger.debug(f"Created user: {tg_id} with role {role}")
        return user

    @staticmethod
    async def update_user_role(
        tg_id: int,
        role: UserRole,
        session: AsyncSession,
    ) -> User | None:
        """
        Update user's role.

        Args:
            tg_id: Telegram user ID
            role: New role
            session: Database session

        Returns:
            Updated User object or None if not found
        """
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.role = role
            await session.flush()
            logger.info(f"Updated role for user {tg_id} to {role}")
        return user

    @staticmethod
    async def update_user_registered_by_code(
        tg_id: int,
        registered_by_code: bool,
        session: AsyncSession,
    ) -> User | None:
        """
        Update user's code registration flag.

        Args:
            tg_id: Telegram user ID
            registered_by_code: New flag value
            session: Database session

        Returns:
            Updated User object or None if not found
        """
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.registered_by_code = registered_by_code
            await session.flush()
            logger.info(f"Updated registered_by_code for user {tg_id} to {registered_by_code}")
        return user

    @staticmethod
    async def update_user_invite_role(
        tg_id: int,
        invite_role: str | None,
        session: AsyncSession,
    ) -> User | None:
        """Update user's invite role."""
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.invite_role = invite_role
            await session.flush()
            logger.info(f"Updated invite_role for user {tg_id} to {invite_role}")
        return user

    @staticmethod
    async def update_user_campaign_id(
        tg_id: int,
        campaign_id: int | None,
        session: AsyncSession,
    ) -> User | None:
        """Update user's campaign access."""
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.campaign_id = campaign_id
            await session.flush()
            logger.info(f"Updated campaign_id for user {tg_id} to {campaign_id}")
        return user

    @staticmethod
    async def get_campaign_accesses(
        tg_id: int,
        session: AsyncSession,
    ) -> list[CampaignAccess]:
        """Get all campaign invite accesses for a user."""
        result = await session.execute(
            select(CampaignAccess).where(CampaignAccess.user_id == tg_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_campaign_access(
        tg_id: int,
        campaign_id: int,
        invite_role: str,
        session: AsyncSession,
    ) -> CampaignAccess | None:
        """Get a specific campaign invite access for a user."""
        result = await session.execute(
            select(CampaignAccess).where(
                CampaignAccess.user_id == tg_id,
                CampaignAccess.campaign_id == campaign_id,
                CampaignAccess.invite_role == invite_role,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def grant_campaign_access(
        tg_id: int,
        campaign_id: int,
        invite_role: str,
        session: AsyncSession,
        invite_code: str | None = None,
    ) -> CampaignAccess:
        """Grant per-campaign invite access without changing base user role."""
        access = await UserService.get_campaign_access(
            tg_id=tg_id,
            campaign_id=campaign_id,
            invite_role=invite_role,
            session=session,
        )
        if access:
            if invite_code and access.invite_code != invite_code:
                access.invite_code = invite_code
                await session.flush()
            logger.info(
                f"Campaign access already exists for user {tg_id}: "
                f"campaign={campaign_id}, invite_role={invite_role}"
            )
            return access

        access = CampaignAccess(
            user_id=tg_id,
            campaign_id=campaign_id,
            invite_role=invite_role,
            invite_code=invite_code,
        )
        session.add(access)
        await session.flush()
        logger.info(
            f"Granted campaign access for user {tg_id}: "
            f"campaign={campaign_id}, invite_role={invite_role}"
        )
        return access

    @staticmethod
    async def has_campaign_access(
        tg_id: int,
        campaign_id: int,
        invite_role: str,
        session: AsyncSession,
    ) -> bool:
        """Check whether user has invite-based access to a campaign for a role."""
        access = await UserService.get_campaign_access(
            tg_id=tg_id,
            campaign_id=campaign_id,
            invite_role=invite_role,
            session=session,
        )
        return access is not None

    @staticmethod
    async def ban_user(tg_id: int, session: AsyncSession) -> User | None:
        """
        Ban a user.

        Args:
            tg_id: Telegram user ID
            session: Database session

        Returns:
            Updated User object or None if not found
        """
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.is_banned = True
            await session.flush()
            logger.info(f"User {tg_id} has been banned")
        return user

    @staticmethod
    async def unban_user(tg_id: int, session: AsyncSession) -> User | None:
        """
        Unban a user.

        Args:
            tg_id: Telegram user ID
            session: Database session

        Returns:
            Updated User object or None if not found
        """
        user = await UserService.get_user(tg_id=tg_id, session=session)
        if user:
            user.is_banned = False
            await session.flush()
            logger.info(f"User {tg_id} has been unbanned")
        return user

    @staticmethod
    async def get_users_by_role(
        role: UserRole,
        session: AsyncSession,
    ) -> list[User]:
        """
        Get all users with a specific role.

        Args:
            role: User role to filter by
            session: Database session

        Returns:
            List of User objects
        """
        result = await session.execute(
            select(User).where(User.role == role)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_users(
        session: AsyncSession,
        query: str | None = None,
        role: UserRole | None = None,
        tg_id: int | None = None,
    ) -> list[User]:
        """
        Get users with optional filters.

        Args:
            session: Database session
            query: Search query for name, Telegram ID or role
            role: Exact role filter
            tg_id: Exact Telegram ID filter

        Returns:
            List of matching User objects
        """
        stmt = select(User)
        filters = []

        if tg_id is not None:
            filters.append(User.tg_id == tg_id)

        if role is not None:
            filters.append(User.role == role)

        if query:
            normalized = query.strip()
            if normalized:
                search_filters = [
                    User.full_name.ilike(f"%{normalized}%"),
                    cast(User.tg_id, String).ilike(f"%{normalized}%"),
                ]
                matched_role = ROLE_ALIASES.get(normalized.lower())
                if matched_role:
                    search_filters.append(User.role == matched_role)
                filters.append(or_(*search_filters))

        if filters:
            stmt = stmt.where(*filters)

        stmt = stmt.order_by(User.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_users(session: AsyncSession) -> list[User]:
        """
        Get all users.

        Args:
            session: Database session

        Returns:
            List of all User objects
        """
        return await UserService.get_users(session)

# Module-level convenience functions
async def get_user(tg_id: int, session: AsyncSession) -> User | None:
    """Get user by Telegram ID."""
    return await UserService.get_user(tg_id, session)

async def create_user(
    tg_id: int,
    full_name: str,
    study_group: str | None,
    session: AsyncSession,
    role: UserRole = UserRole.STUDENT,
    registered_by_code: bool = False,
    invite_role: str | None = None,
    campaign_id: int | None = None,
) -> User:
    """Create a new user."""
    return await UserService.create_user(
        tg_id,
        full_name,
        study_group,
        session,
        role,
        registered_by_code,
        invite_role,
        campaign_id,
    )

async def update_user_role(
    tg_id: int,
    role: UserRole,
    session: AsyncSession,
) -> User | None:
    """Update user's role."""
    return await UserService.update_user_role(tg_id, role, session)

async def update_user_registered_by_code(
    tg_id: int,
    registered_by_code: bool,
    session: AsyncSession,
) -> User | None:
    """Update user's code registration flag."""
    return await UserService.update_user_registered_by_code(
        tg_id, registered_by_code, session
    )

async def update_user_invite_role(
    tg_id: int,
    invite_role: str | None,
    session: AsyncSession,
) -> User | None:
    """Update user's invite role."""
    return await UserService.update_user_invite_role(
        tg_id, invite_role, session
    )

async def update_user_campaign_id(
    tg_id: int,
    campaign_id: int | None,
    session: AsyncSession,
) -> User | None:
    """Update user's campaign access."""
    return await UserService.update_user_campaign_id(
        tg_id, campaign_id, session
    )

async def get_campaign_accesses(
    tg_id: int,
    session: AsyncSession,
) -> list[CampaignAccess]:
    """Get all campaign invite accesses for a user."""
    return await UserService.get_campaign_accesses(tg_id, session)

async def get_campaign_access(
    tg_id: int,
    campaign_id: int,
    invite_role: str,
    session: AsyncSession,
) -> CampaignAccess | None:
    """Get a specific campaign invite access for a user."""
    return await UserService.get_campaign_access(
        tg_id,
        campaign_id,
        invite_role,
        session,
    )

async def grant_campaign_access(
    tg_id: int,
    campaign_id: int,
    invite_role: str,
    session: AsyncSession,
    invite_code: str | None = None,
) -> CampaignAccess:
    """Grant per-campaign invite access without changing base user role."""
    return await UserService.grant_campaign_access(
        tg_id,
        campaign_id,
        invite_role,
        session,
        invite_code,
    )

async def ensure_web_access_token(user: User, session: AsyncSession) -> str:
    """Ensure organizer has a web access token."""
    return await UserService.ensure_web_access_token(user, session)

async def has_campaign_access(
    tg_id: int,
    campaign_id: int,
    invite_role: str,
    session: AsyncSession,
) -> bool:
    """Check whether user has invite-based access to a campaign for a role."""
    return await UserService.has_campaign_access(
        tg_id,
        campaign_id,
        invite_role,
        session,
    )

async def ban_user(tg_id: int, session: AsyncSession) -> User | None:
    """Ban a user."""
    return await UserService.ban_user(tg_id, session)

async def unban_user(tg_id: int, session: AsyncSession) -> User | None:
    """Unban a user."""
    return await UserService.unban_user(tg_id, session)

async def get_users_by_role(
    role: UserRole,
    session: AsyncSession,
) -> list[User]:
    """Get all users with a specific role."""
    return await UserService.get_users_by_role(role, session)

async def get_users(
    session: AsyncSession,
    query: str | None = None,
    role: UserRole | None = None,
    tg_id: int | None = None,
) -> list[User]:
    """Get users with optional filters."""
    return await UserService.get_users(session, query=query, role=role, tg_id=tg_id)

async def get_all_users(session: AsyncSession) -> list[User]:
    """Get all users."""
    return await UserService.get_all_users(session)
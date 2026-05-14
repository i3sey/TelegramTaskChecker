"""User service for database operations."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import User, UserRole
from src.bot.utils.logging import logger


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
    async def create_user(
        tg_id: int,
        full_name: str,
        study_group: str | None,
        session: AsyncSession,
        role: UserRole = UserRole.STUDENT,
        registered_by_code: bool = False,
        invite_role: str | None = None,
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
        )
        session.add(user)
        await session.flush()
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
    async def get_all_users(session: AsyncSession) -> list[User]:
        """
        Get all users.

        Args:
            session: Database session

        Returns:
            List of all User objects
        """
        result = await session.execute(select(User))
        return list(result.scalars().all())


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
) -> User:
    """Create a new user."""
    return await UserService.create_user(
        tg_id, full_name, study_group, session, role, registered_by_code, invite_role
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


async def get_all_users(session: AsyncSession) -> list[User]:
    """Get all users."""
    return await UserService.get_all_users(session)

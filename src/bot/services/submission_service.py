"""Submission service for database operations."""
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import Submission, SubmissionFormat, SubmissionStatus
from src.bot.utils.logging import logger


class SubmissionService:
    """Service for submission-related database operations."""

    @staticmethod
    async def create_submission(
        campaign_id: int,
        author_id: int,
        session: AsyncSession,
        submission_type: SubmissionFormat = SubmissionFormat.DOCUMENT,
        file_id: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        text_content: str | None = None,
        external_url: str | None = None,
    ) -> Submission:
        """
        Create a new submission.

        Args:
            campaign_id: Campaign ID
            author_id: Author's user ID
            session: Database session
            submission_type: Actual submitted content type
            file_id: Telegram file_id for document/photo
            file_name: Original file name if available
            mime_type: MIME type if available
            text_content: Submitted text content
            external_url: Submitted external URL

        Returns:
            Created Submission object
        """
        submission = Submission(
            campaign_id=campaign_id,
            author_id=author_id,
            submission_type=submission_type,
            file_id=file_id,
            file_name=file_name,
            mime_type=mime_type,
            text_content=text_content,
            external_url=external_url,
            status=SubmissionStatus.UPLOADED,
        )
        session.add(submission)
        await session.flush()
        logger.info(
            f"Created submission: id={submission.id}, "
            f"campaign={campaign_id}, author={author_id}"
        )
        return submission

    @staticmethod
    async def get_user_submissions(
        user_id: int,
        session: AsyncSession
    ) -> list[Submission]:
        """
        Get all submissions by a specific user.

        Args:
            user_id: User's Telegram ID
            session: Database session

        Returns:
            List of Submission objects
        """
        result = await session.execute(
            select(Submission)
            .where(Submission.author_id == user_id)
            .order_by(Submission.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_submission(
        submission_id: int,
        session: AsyncSession
    ) -> Submission | None:
        """
        Get submission by ID.

        Args:
            submission_id: Submission ID
            session: Database session

        Returns:
            Submission object or None if not found
        """
        result = await session.execute(
            select(Submission).where(Submission.id == submission_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_submission_status(
        submission_id: int,
        status: SubmissionStatus,
        session: AsyncSession
    ) -> Submission | None:
        """
        Update submission status.

        Args:
            submission_id: Submission ID
            status: New status
            session: Database session

        Returns:
            Updated Submission object or None if not found
        """
        submission = await SubmissionService.get_submission(submission_id, session)
        if submission:
            submission.status = status
            await session.flush()
            logger.info(f"Updated submission {submission_id} status to {status.value}")
        return submission

    @staticmethod
    async def check_user_has_submission(
        campaign_id: int,
        user_id: int,
        session: AsyncSession
    ) -> bool:
        """
        Check if user already has a submission for a campaign.

        Args:
            campaign_id: Campaign ID
            user_id: User's Telegram ID
            session: Database session

        Returns:
            True if user has a submission, False otherwise
        """
        result = await session.execute(
            select(Submission).where(
                and_(
                    Submission.campaign_id == campaign_id,
                    Submission.author_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_submissions_by_campaign(
        campaign_id: int,
        session: AsyncSession
    ) -> list[Submission]:
        """
        Get all submissions for a specific campaign.

        Args:
            campaign_id: Campaign ID
            session: Database session

        Returns:
            List of Submission objects
        """
        result = await session.execute(
            select(Submission)
            .where(Submission.campaign_id == campaign_id)
            .order_by(Submission.created_at.desc())
        )
        return list(result.scalars().all())


# Module-level convenience functions
async def create_submission(
    campaign_id: int,
    author_id: int,
    session: AsyncSession,
    submission_type: SubmissionFormat = SubmissionFormat.DOCUMENT,
    file_id: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    text_content: str | None = None,
    external_url: str | None = None,
) -> Submission:
    """Create a new submission."""
    return await SubmissionService.create_submission(
        campaign_id=campaign_id,
        author_id=author_id,
        session=session,
        submission_type=submission_type,
        file_id=file_id,
        file_name=file_name,
        mime_type=mime_type,
        text_content=text_content,
        external_url=external_url,
    )


async def get_user_submissions(user_id: int, session: AsyncSession) -> list[Submission]:
    """Get all submissions by a user."""
    return await SubmissionService.get_user_submissions(user_id, session)


async def get_submission(submission_id: int, session: AsyncSession) -> Submission | None:
    """Get submission by ID."""
    return await SubmissionService.get_submission(submission_id, session)


async def update_submission_status(
    submission_id: int,
    status: SubmissionStatus,
    session: AsyncSession
) -> Submission | None:
    """Update submission status."""
    return await SubmissionService.update_submission_status(
        submission_id, status, session
    )


async def check_user_has_submission(
    campaign_id: int,
    user_id: int,
    session: AsyncSession
) -> bool:
    """Check if user has submission for campaign."""
    return await SubmissionService.check_user_has_submission(
        campaign_id, user_id, session
    )


async def get_submissions_by_campaign(
    campaign_id: int,
    session: AsyncSession
) -> list[Submission]:
    """Get all submissions for a campaign."""
    return await SubmissionService.get_submissions_by_campaign(campaign_id, session)
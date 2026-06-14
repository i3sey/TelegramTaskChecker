"""Submission service for database operations."""
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import Campaign, Review, Submission, SubmissionFormat, SubmissionStatus
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
    async def replace_submission_content(
        submission: Submission,
        session: AsyncSession,
        submission_type: SubmissionFormat = SubmissionFormat.DOCUMENT,
        file_id: str | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        text_content: str | None = None,
        external_url: str | None = None,
    ) -> Submission:
        """
        Replace existing submission content before review.

        Args:
            submission: Existing submission to update
            session: Database session
            submission_type: Actual submitted content type
            file_id: Telegram file_id for document/photo
            file_name: Original file name if available
            mime_type: MIME type if available
            text_content: Submitted text content
            external_url: Submitted external URL

        Returns:
            Updated Submission object
        """
        submission.submission_type = submission_type
        submission.file_id = file_id
        submission.file_name = file_name
        submission.mime_type = mime_type
        submission.text_content = text_content
        submission.external_url = external_url
        submission.status = SubmissionStatus.UPLOADED
        submission.p2p_completed_at = None
        await session.flush()
        logger.info(
            f"Replaced submission: id={submission.id}, "
            f"campaign={submission.campaign_id}, author={submission.author_id}"
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
    async def get_user_submissions_with_review_details(
        user_id: int,
        session: AsyncSession
    ) -> list[tuple[Submission, Campaign, Review | None]]:
        """
        Get all submissions by a specific user with campaign titles and latest review.

        Args:
            user_id: User's Telegram ID
            session: Database session

        Returns:
            List of tuples: (Submission, campaign title, latest Review or None)
        """
        latest_review_subquery = (
            select(
                Review.submission_id.label("submission_id"),
                func.max(Review.id).label("latest_review_id"),
            )
            .group_by(Review.submission_id)
            .subquery()
        )

        result = await session.execute(
            select(Submission, Campaign, Review)
            .join(Campaign, Campaign.id == Submission.campaign_id)
            .outerjoin(
                latest_review_subquery,
                latest_review_subquery.c.submission_id == Submission.id,
            )
            .outerjoin(Review, Review.id == latest_review_subquery.c.latest_review_id)
            .where(Submission.author_id == user_id)
            .order_by(Submission.created_at.desc(), Submission.id.desc())
        )
        return [
            (submission, campaign, review)
            for submission, campaign, review in result.all()
        ]

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
    async def get_latest_user_submission(
        campaign_id: int,
        user_id: int,
        session: AsyncSession
    ) -> Submission | None:
        """
        Get latest submission by user for a campaign.

        Args:
            campaign_id: Campaign ID
            user_id: User's Telegram ID
            session: Database session

        Returns:
            Latest Submission object or None if not found
        """
        result = await session.execute(
            select(Submission)
            .where(
                and_(
                    Submission.campaign_id == campaign_id,
                    Submission.author_id == user_id,
                )
            )
            .order_by(Submission.created_at.desc(), Submission.id.desc())
        )
        return result.scalars().first()

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
    async def check_submission_availability(
        campaign: Campaign,
        user_id: int,
        session: AsyncSession
    ) -> tuple[str, Submission | None, str | None]:
        """
        Determine whether the user can create or replace a submission.

        Returns:
            Tuple of (action, existing_submission, error_message), where
            action is one of: "create", "replace", "forbid".
        """
        submission = await SubmissionService.get_latest_user_submission(
            campaign.id,
            user_id,
            session,
        )
        if submission is None:
            return "create", None, None

        if (
            campaign.type.value == "p2p"
            and submission.status != SubmissionStatus.UPLOADED
            and submission.p2p_completed_at is None
        ):
            return (
                "forbid",
                submission,
                "❌ Сначала завершите обязательные P2P-проверки через /p2p.",
            )

        if submission.status == SubmissionStatus.UPLOADED:
            if campaign.type.value == "p2p":
                review_count = await session.scalar(
                    select(func.count(Review.id)).where(
                        Review.submission_id == submission.id
                    )
                )
                if review_count:
                    return (
                        "forbid",
                        submission,
                        "❌ Работа уже участвует в P2P-проверке и получила рецензию.\n"
                        "Заменить её содержимое больше нельзя.",
                    )
            if campaign.allow_resubmission_before_review:
                return "replace", submission, None
            return (
                "forbid",
                submission,
                "❌ Вы уже отправили работу в эту кампанию.\n"
                "Замена работы до проверки отключена организатором.",
            )

        if submission.status == SubmissionStatus.IN_REVIEW:
            return (
                "forbid",
                submission,
                "❌ Ваша работа уже находится на проверке.\n"
                "Заменить её сейчас нельзя.",
            )

        if submission.status in (
            SubmissionStatus.REVIEWED,
            SubmissionStatus.REJECTED,
        ):
            if campaign.allow_resubmission_after_review:
                return "create", submission, None
            return (
                "forbid",
                submission,
                "❌ Вы уже сдавали работу в эту кампанию.\n"
                "Повторная сдача после проверки отключена организатором.",
            )

        return (
            "forbid",
            submission,
            "❌ Повторная отправка работы сейчас недоступна.",
        )

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
        submission = await SubmissionService.get_latest_user_submission(
            campaign_id,
            user_id,
            session,
        )
        return submission is not None

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

async def replace_submission_content(
    submission: Submission,
    session: AsyncSession,
    submission_type: SubmissionFormat = SubmissionFormat.DOCUMENT,
    file_id: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    text_content: str | None = None,
    external_url: str | None = None,
) -> Submission:
    """Replace existing submission content before review."""
    return await SubmissionService.replace_submission_content(
        submission=submission,
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

async def get_user_submissions_with_review_details(
    user_id: int,
    session: AsyncSession
) -> list[tuple[Submission, Campaign, Review | None]]:
    """Get all submissions by a user with campaign title and latest review."""
    return await SubmissionService.get_user_submissions_with_review_details(user_id, session)

async def get_submission(submission_id: int, session: AsyncSession) -> Submission | None:
    """Get submission by ID."""
    return await SubmissionService.get_submission(submission_id, session)

async def get_latest_user_submission(
    campaign_id: int,
    user_id: int,
    session: AsyncSession
) -> Submission | None:
    """Get latest submission by user for campaign."""
    return await SubmissionService.get_latest_user_submission(
        campaign_id, user_id, session
    )

async def update_submission_status(
    submission_id: int,
    status: SubmissionStatus,
    session: AsyncSession
) -> Submission | None:
    """Update submission status."""
    return await SubmissionService.update_submission_status(
        submission_id, status, session
    )

async def check_submission_availability(
    campaign: Campaign,
    user_id: int,
    session: AsyncSession
) -> tuple[str, Submission | None, str | None]:
    """Check whether user can create or replace a submission."""
    return await SubmissionService.check_submission_availability(
        campaign, user_id, session
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

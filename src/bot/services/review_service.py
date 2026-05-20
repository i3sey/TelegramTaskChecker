"""Review service for database operations."""
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import Campaign, CampaignType, Review, Submission, SubmissionStatus
from src.bot.utils.logging import logger


class ReviewService:
    """Service for review-related database operations."""

    @staticmethod
    async def create_review(
        submission_id: int,
        reviewer_id: int,
        score: int,
        comment_text: str | None,
        session: AsyncSession,
        voice_file_id: str | None = None,
        ban_comment: str | None = None,
    ) -> Review:
        """
        Create a new review for a submission.

        Args:
            submission_id: ID of the submission being reviewed
            reviewer_id: Telegram ID of the reviewer
            score: Score given by the reviewer
            comment_text: Optional text comment
            session: Database session
            voice_file_id: Optional voice file ID
            ban_comment: Optional comment explaining why expert wants to ban student

        Returns:
            Created Review object
        """
        review = Review(
            submission_id=submission_id,
            reviewer_id=reviewer_id,
            score=score,
            comment_text=comment_text,
            voice_file_id=voice_file_id,
            ban_comment=ban_comment,
        )
        session.add(review)
        await session.flush()
        logger.info(
            f"Created review: id={review.id}, submission_id={submission_id}, "
            f"reviewer_id={reviewer_id}, score={score}"
        )
        return review

    @staticmethod
    async def get_review(review_id: int, session: AsyncSession) -> Review | None:
        """
        Get a review by its ID.

        Args:
            review_id: Review ID
            session: Database session

        Returns:
            Review object or None if not found
        """
        result = await session.execute(
            select(Review).where(Review.id == review_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_review_by_submission_and_reviewer(
        submission_id: int,
        reviewer_id: int,
        session: AsyncSession,
    ) -> Review | None:
        """Get a review by submission and reviewer."""
        result = await session.execute(
            select(Review).where(
                and_(
                    Review.submission_id == submission_id,
                    Review.reviewer_id == reviewer_id,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_submission_reviews(
        submission_id: int,
        session: AsyncSession
    ) -> list[Review]:
        """
        Get all reviews for a specific submission.

        Args:
            submission_id: Submission ID
            session: Database session

        Returns:
            List of Review objects
        """
        result = await session.execute(
            select(Review)
            .where(Review.submission_id == submission_id)
            .order_by(Review.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_expert_reviews(
        reviewer_id: int,
        session: AsyncSession
    ) -> list[Review]:
        """
        Get all reviews by a specific expert.

        Args:
            reviewer_id: Telegram ID of the reviewer
            session: Database session

        Returns:
            List of Review objects
        """
        result = await session.execute(
            select(Review)
            .where(Review.reviewer_id == reviewer_id)
            .order_by(Review.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_reviewer_reviews_for_campaign(
        reviewer_id: int,
        campaign_id: int,
        session: AsyncSession,
    ) -> int:
        """Count reviews by reviewer within a campaign."""
        from src.bot.models import Submission

        result = await session.execute(
            select(func.count(Review.id))
            .join(Submission, Review.submission_id == Submission.id)
            .where(
                and_(
                    Review.reviewer_id == reviewer_id,
                    Submission.campaign_id == campaign_id,
                )
            )
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    async def count_submission_reviews(
        submission_id: int,
        session: AsyncSession,
    ) -> int:
        """Count reviews for a submission."""
        result = await session.execute(
            select(func.count(Review.id)).where(Review.submission_id == submission_id)
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    async def update_review(
        review_id: int,
        session: AsyncSession,
        score: int | None = None,
        comment_text: str | None = None,
        voice_file_id: str | None = None,
    ) -> Review | None:
        """
        Update an existing review.

        Args:
            review_id: Review ID
            session: Database session
            score: New score (optional)
            comment_text: New comment text (optional)
            voice_file_id: New voice file ID (optional)

        Returns:
            Updated Review object or None if not found
        """
        review = await ReviewService.get_review(review_id, session)
        if review:
            if score is not None:
                review.score = score
            if comment_text is not None:
                review.comment_text = comment_text
            if voice_file_id is not None:
                review.voice_file_id = voice_file_id
            await session.flush()
            logger.info(f"Updated review {review_id}: score={score}, comment={comment_text}")
        return review

    @staticmethod
    async def get_submission_pending(
        session: AsyncSession,
        limit: int = 10
    ) -> list[Submission]:
        """
        Get submissions that are waiting for review (status=uploaded).

        Args:
            session: Database session
            limit: Maximum number of submissions to return

        Returns:
            List of Submission objects
        """
        result = await session.execute(
            select(Submission)
            .join(Campaign, Submission.campaign_id == Campaign.id)
            .where(
                and_(
                    Submission.status == SubmissionStatus.UPLOADED,
                    Campaign.type == CampaignType.EXPERT,
                )
            )
            .order_by(Submission.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_pending_submissions(session: AsyncSession) -> int:
        """
        Count submissions that are waiting for review.

        Args:
            session: Database session

        Returns:
            Number of pending submissions
        """
        result = await session.execute(
            select(func.count(Submission.id))
            .join(Campaign, Submission.campaign_id == Campaign.id)
            .where(
                and_(
                    Submission.status == SubmissionStatus.UPLOADED,
                    Campaign.type == CampaignType.EXPERT,
                )
            )
        )
        return int(result.scalar_one() or 0)


# Module-level convenience functions
async def create_review(
    submission_id: int,
    reviewer_id: int,
    score: int,
    comment_text: str | None,
    session: AsyncSession,
    voice_file_id: str | None = None,
    ban_comment: str | None = None,
) -> Review:
    """Create a new review."""
    return await ReviewService.create_review(
        submission_id, reviewer_id, score, comment_text, session, voice_file_id, ban_comment
    )


async def get_review(review_id: int, session: AsyncSession) -> Review | None:
    """Get review by ID."""
    return await ReviewService.get_review(review_id, session)


async def get_review_by_submission_and_reviewer(
    submission_id: int,
    reviewer_id: int,
    session: AsyncSession,
) -> Review | None:
    """Get review by submission and reviewer."""
    return await ReviewService.get_review_by_submission_and_reviewer(
        submission_id, reviewer_id, session
    )


async def get_submission_reviews(
    submission_id: int,
    session: AsyncSession
) -> list[Review]:
    """Get all reviews for a submission."""
    return await ReviewService.get_submission_reviews(submission_id, session)


async def get_expert_reviews(
    reviewer_id: int,
    session: AsyncSession
) -> list[Review]:
    """Get all reviews by an expert."""
    return await ReviewService.get_expert_reviews(reviewer_id, session)


async def count_reviewer_reviews_for_campaign(
    reviewer_id: int,
    campaign_id: int,
    session: AsyncSession,
) -> int:
    """Count reviews by reviewer for a campaign."""
    return await ReviewService.count_reviewer_reviews_for_campaign(
        reviewer_id, campaign_id, session
    )


async def count_submission_reviews(
    submission_id: int,
    session: AsyncSession,
) -> int:
    """Count reviews for a submission."""
    return await ReviewService.count_submission_reviews(submission_id, session)


async def update_review(
    review_id: int,
    session: AsyncSession,
    score: int | None = None,
    comment_text: str | None = None,
    voice_file_id: str | None = None,
) -> Review | None:
    """Update an existing review."""
    return await ReviewService.update_review(
        review_id, session, score, comment_text, voice_file_id
    )


async def get_submission_pending(
    session: AsyncSession,
    limit: int = 10
) -> list[Submission]:
    """Get pending submissions for review."""
    return await ReviewService.get_submission_pending(session, limit)


async def count_pending_submissions(session: AsyncSession) -> int:
    """Count pending submissions."""
    return await ReviewService.count_pending_submissions(session)
"""Campaign service for database operations."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.models import Campaign, CampaignType, Review, Submission, SubmissionStatus
from src.bot.utils.logging import logger

class CampaignService:
    """Service for campaign-related database operations."""

    @staticmethod
    def _campaign_deadline(campaign: Campaign) -> datetime | None:
        """Calculate campaign deadline from creation time and TTL."""
        if campaign.campaign_deadline_at is not None:
            deadline = campaign.campaign_deadline_at
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return deadline

        if not campaign.created_at or campaign.ttl_minutes is None:
            return None

        created_at = campaign.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at + timedelta(minutes=campaign.ttl_minutes)

    @staticmethod
    async def _deactivate_expired_campaigns(session: AsyncSession) -> None:
        """Mark expired active campaigns as inactive."""
        result = await session.execute(
            select(Campaign).where(Campaign.is_active == True)
        )
        active_campaigns = list(result.scalars().all())
        now = datetime.now(timezone.utc)

        changed = False
        for campaign in active_campaigns:
            deadline = CampaignService._campaign_deadline(campaign)
            if deadline and deadline <= now:
                campaign.is_active = False
                changed = True
                logger.info(
                    "Campaign auto-completed by deadline: "
                    f"id={campaign.id}, title='{campaign.title}'"
                )

        if changed:
            await session.flush()

    @staticmethod
    async def get_campaign(
        campaign_id: int,
        session: AsyncSession
    ) -> Campaign | None:
        """
        Get campaign by ID.

        Args:
            campaign_id: Campaign ID
            session: Database session

        Returns:
            Campaign object or None if not found
        """
        result = await session.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_campaigns(session: AsyncSession) -> list[Campaign]:
        """
        Get all active campaigns.

        Args:
            session: Database session

        Returns:
            List of active Campaign objects
        """
        await CampaignService._deactivate_expired_campaigns(session)
        result = await session.execute(
            select(Campaign)
            .where(Campaign.is_active == True)
            .order_by(Campaign.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_campaigns_by_organizer(
        organizer_id: int,
        session: AsyncSession
    ) -> list[Campaign]:
        """
        Get all campaigns created by a specific organizer.
        Note: We filter by checking submissions author or store organizer_id in campaign.
        For now, we return all campaigns (organizer filter would require adding organizer_id column).

        Args:
            organizer_id: Organizer's user ID
            session: Database session

        Returns:
            List of Campaign objects
        """
        await CampaignService._deactivate_expired_campaigns(session)

        # The Campaign model does not store organizer_id yet, so organizer-specific filtering
        # is not available. For now, organizers see the full list of campaigns.
        result = await session.execute(
            select(Campaign)
            .order_by(Campaign.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_campaign(
        title: str,
        campaign_type: CampaignType,
        min_score: int,
        max_score: int,
        ttl_minutes: int,
        campaign_deadline_at: datetime,
        is_expert_anon: bool,
        p2p_reviews_required: int,
        voting_type: str | None,
        organizer_id: int,
        session: AsyncSession
    ) -> Campaign:
        """
        Create a new campaign.

        Args:
            title: Campaign title
            campaign_type: Type of campaign
            min_score: Minimum score
            max_score: Maximum score
            ttl_minutes: Time-to-live in minutes
            is_expert_anon: Whether expert reviews are anonymous
            organizer_id: ID of the organizer (for future reference)
            session: Database session

        Returns:
            Created Campaign object
        """
        campaign = Campaign(
            title=title,
            type=campaign_type,
            min_score=min_score,
            max_score=max_score,
            ttl_minutes=ttl_minutes,
            campaign_deadline_at=campaign_deadline_at,
            is_expert_anon=is_expert_anon,
            p2p_reviews_required=p2p_reviews_required,
            voting_type=voting_type,
        )
        session.add(campaign)
        await session.flush()
        logger.info(
            f"Created campaign: id={campaign.id}, title='{title}', "
            f"type={campaign_type.value}, organizer={organizer_id}"
        )
        return campaign

    @staticmethod
    async def update_campaign(
        campaign_id: int,
        session: AsyncSession,
        **kwargs
    ) -> Campaign | None:
        """
        Update campaign fields.

        Args:
            campaign_id: Campaign ID
            session: Database session
            **kwargs: Fields to update

        Returns:
            Updated Campaign object or None if not found
        """
        campaign = await CampaignService.get_campaign(campaign_id, session)
        if campaign:
            for key, value in kwargs.items():
                if hasattr(campaign, key) and key not in ('id', 'created_at'):
                    setattr(campaign, key, value)
            await session.flush()
            logger.info(f"Updated campaign {campaign_id}: {kwargs}")
        return campaign

    @staticmethod
    async def toggle_campaign_active(
        campaign_id: int,
        is_active: bool,
        session: AsyncSession
    ) -> Campaign | None:
        """
        Toggle campaign active status.

        Args:
            campaign_id: Campaign ID
            is_active: New active status
            session: Database session

        Returns:
            Updated Campaign object or None if not found
        """
        return await CampaignService.update_campaign(
            campaign_id, session, is_active=is_active
        )

    @staticmethod
    async def get_campaign_results(session: AsyncSession) -> list[dict]:
        """
        Get aggregated campaign results.

        Returns:
            List of campaign result dictionaries with totals, averages,
            comments and status summary.
        """
        await CampaignService._deactivate_expired_campaigns(session)

        campaigns_result = await session.execute(
            select(Campaign).order_by(Campaign.created_at.desc())
        )
        campaigns = list(campaigns_result.scalars().all())
        if not campaigns:
            return []

        campaign_ids = [campaign.id for campaign in campaigns]

        submissions_count_result = await session.execute(
            select(
                Submission.campaign_id,
                func.count(Submission.id)
            )
            .where(Submission.campaign_id.in_(campaign_ids))
            .group_by(Submission.campaign_id)
        )
        submissions_count = {
            int(campaign_id): int(count)
            for campaign_id, count in submissions_count_result.all()
        }

        reviewed_count_result = await session.execute(
            select(
                Submission.campaign_id,
                func.count(Submission.id)
            )
            .where(
                Submission.campaign_id.in_(campaign_ids),
                Submission.status == SubmissionStatus.REVIEWED,
            )
            .group_by(Submission.campaign_id)
        )
        reviewed_count = {
            int(campaign_id): int(count)
            for campaign_id, count in reviewed_count_result.all()
        }

        avg_score_result = await session.execute(
            select(
                Submission.campaign_id,
                func.avg(Review.score)
            )
            .join(Submission, Review.submission_id == Submission.id)
            .where(Submission.campaign_id.in_(campaign_ids))
            .group_by(Submission.campaign_id)
        )
        avg_scores = {
            int(campaign_id): float(avg_score) if avg_score is not None else 0.0
            for campaign_id, avg_score in avg_score_result.all()
        }

        status_counts_result = await session.execute(
            select(
                Submission.campaign_id,
                Submission.status,
                func.count(Submission.id)
            )
            .where(Submission.campaign_id.in_(campaign_ids))
            .group_by(Submission.campaign_id, Submission.status)
        )
        status_counts: dict[int, dict[str, int]] = {}
        for campaign_id, status, count in status_counts_result.all():
            campaign_id = int(campaign_id)
            status_counts.setdefault(campaign_id, {})
            status_counts[campaign_id][status.value] = int(count)

        comments_result = await session.execute(
            select(
                Submission.campaign_id,
                Review.comment_text,
                Review.ban_comment,
            )
            .join(Submission, Review.submission_id == Submission.id)
            .where(Submission.campaign_id.in_(campaign_ids))
            .order_by(Review.created_at.desc())
        )
        comments_by_campaign: dict[int, list[str]] = {}
        for campaign_id, comment_text, ban_comment in comments_result.all():
            campaign_id = int(campaign_id)
            comments = comments_by_campaign.setdefault(campaign_id, [])
            for comment in (comment_text, ban_comment):
                if comment and comment.strip():
                    comments.append(comment.strip())

        results: list[dict] = []
        for campaign in campaigns:
            campaign_id = campaign.id
            results.append(
                {
                    "campaign": campaign,
                    "total_submissions": submissions_count.get(campaign_id, 0),
                    "reviewed_submissions": reviewed_count.get(campaign_id, 0),
                    "avg_score": round(avg_scores.get(campaign_id, 0.0), 2),
                    "comments": comments_by_campaign.get(campaign_id, [])[:5],
                    "status_summary": {
                        "uploaded": status_counts.get(campaign_id, {}).get(
                            SubmissionStatus.UPLOADED.value, 0
                        ),
                        "in_review": status_counts.get(campaign_id, {}).get(
                            SubmissionStatus.IN_REVIEW.value, 0
                        ),
                        "reviewed": status_counts.get(campaign_id, {}).get(
                            SubmissionStatus.REVIEWED.value, 0
                        ),
                        "rejected": status_counts.get(campaign_id, {}).get(
                            SubmissionStatus.REJECTED.value, 0
                        ),
                    },
                }
            )

        return results

# Module-level convenience functions
async def get_campaign(campaign_id: int, session: AsyncSession) -> Campaign | None:
    """Get campaign by ID."""
    return await CampaignService.get_campaign(campaign_id, session)

async def get_active_campaigns(session: AsyncSession) -> list[Campaign]:
    """Get all active campaigns."""
    return await CampaignService.get_active_campaigns(session)

async def get_campaigns_by_organizer(
    organizer_id: int,
    session: AsyncSession
) -> list[Campaign]:
    """Get campaigns by organizer."""
    return await CampaignService.get_campaigns_by_organizer(organizer_id, session)

async def create_campaign(
    title: str,
    campaign_type: CampaignType,
    min_score: int,
    max_score: int,
    ttl_minutes: int,
    campaign_deadline_at: datetime,
    is_expert_anon: bool,
    p2p_reviews_required: int,
    voting_type: str | None,
    organizer_id: int,
    session: AsyncSession
) -> Campaign:
    """Create a new campaign."""
    return await CampaignService.create_campaign(
        title, campaign_type, min_score, max_score,
        ttl_minutes, campaign_deadline_at, is_expert_anon, p2p_reviews_required,
        voting_type, organizer_id, session
    )

async def update_campaign(
    campaign_id: int,
    session: AsyncSession,
    **kwargs
) -> Campaign | None:
    """Update campaign."""
    return await CampaignService.update_campaign(campaign_id, session, **kwargs)

async def toggle_campaign_active(
    campaign_id: int,
    is_active: bool,
    session: AsyncSession
) -> Campaign | None:
    """Toggle campaign active status."""
    return await CampaignService.toggle_campaign_active(campaign_id, is_active, session)

async def get_campaign_results(session: AsyncSession) -> list[dict]:
    """Get aggregated campaign results."""
    return await CampaignService.get_campaign_results(session)
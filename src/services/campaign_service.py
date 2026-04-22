"""Campaign service for database operations."""
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Campaign, CampaignType
from src.utils.logging import logger


class CampaignService:
    """Service for campaign-related database operations."""

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
        # TODO: Add organizer_id to Campaign model for proper filtering
        # For MVP, return all campaigns (organizers can see all)
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
        is_expert_anon: bool,
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
            is_expert_anon=is_expert_anon,
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
    is_expert_anon: bool,
    organizer_id: int,
    session: AsyncSession
) -> Campaign:
    """Create a new campaign."""
    return await CampaignService.create_campaign(
        title, campaign_type, min_score, max_score,
        ttl_minutes, is_expert_anon, organizer_id, session
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
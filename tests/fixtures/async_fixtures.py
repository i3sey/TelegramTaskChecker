"""Async fixtures for integration testing with database and Redis."""
import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.db.models import User, Campaign, Submission, Review, UserRole, CampaignType, SubmissionStatus


@pytest_asyncio.fixture
async def clean_db() -> AsyncGenerator[MagicMock, None]:
    """Provide a clean mock database session for testing.

    Yields:
        MagicMock: Mock session that can be used as an async context manager
    """
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    # Track added objects
    added_users: list[User] = []
    added_campaigns: list[Campaign] = []
    added_submissions: list[Submission] = []
    added_reviews: list[Review] = []

    async def mock_add(obj):
        if isinstance(obj, User):
            added_users.append(obj)
        elif isinstance(obj, Campaign):
            added_campaigns.append(obj)
        elif isinstance(obj, Submission):
            added_submissions.append(obj)
        elif isinstance(obj, Review):
            added_reviews.append(obj)

    session.add = mock_add

    async def mock_execute(query):
        """Mock SQLAlchemy execute."""
        result = MagicMock()
        result.scalars = MagicMock(return_value=[])
        result.scalar_one_or_none = MagicMock(return_value=None)
        return result

    session.execute = mock_execute

    # Store references for assertions
    session._added_users = added_users
    session._added_campaigns = added_campaigns
    session._added_submissions = added_submissions
    session._added_reviews = added_reviews

    yield session

    # Cleanup
    added_users.clear()
    added_campaigns.clear()
    added_submissions.clear()
    added_reviews.clear()


@pytest_asyncio.fixture
async def clean_redis() -> AsyncGenerator[MagicMock, None]:
    """Provide a clean mock Redis client for testing.

    Yields:
        MagicMock: Mock Redis client
    """
    # Internal state to simulate Redis
    data: dict[str, str] = {}
    ttls: dict[str, int] = {}

    client = MagicMock()

    # Mock set with NX (only set if not exists)
    async def mock_set(key: str, value: str, ex: int = None, nx: bool = False) -> bool:
        if nx and key in data:
            return False
        data[key] = value
        if ex:
            ttls[key] = ex
        return True

    # Mock get
    async def mock_get(key: str) -> str | None:
        return data.get(key)

    # Mock delete
    async def mock_delete(key: str) -> int:
        if key in data:
            del data[key]
            if key in ttls:
                del ttls[key]
            return 1
        return 0

    # Mock exists
    async def mock_exists(key: str) -> int:
        return 1 if key in data else 0

    # Mock ttl
    async def mock_ttl(key: str) -> int:
        if key not in data:
            return -2  # Key doesn't exist
        return ttls.get(key, -1)  # -1 if no TTL set

    # Mock expire
    async def mock_expire(key: str, seconds: int) -> bool:
        if key in data:
            ttls[key] = seconds
            return True
        return False

    # Mock scan_iter for pattern matching
    async def mock_scan_iter(pattern: str):
        matching_keys = [k for k in data.keys() if _match_pattern(pattern, k)]
        for key in matching_keys:
            yield key

    def _match_pattern(pattern: str, key: str) -> bool:
        """Simple pattern matching for Redis SCAN."""
        import fnmatch
        return fnmatch.fnmatch(key, pattern)

    # Mock ping
    async def mock_ping():
        return True

    # Mock close
    async def mock_close():
        data.clear()
        ttls.clear()

    # Assign methods
    client.set = mock_set
    client.get = mock_get
    client.delete = mock_delete
    client.exists = mock_exists
    client.ttl = mock_ttl
    client.expire = mock_expire
    client.scan_iter = mock_scan_iter
    client.ping = mock_ping
    client.close = mock_close

    # Store internals for test access
    client._data = data
    client._ttls = ttls

    yield client

    # Cleanup
    data.clear()
    ttls.clear()


@pytest_asyncio.fixture
async def test_user() -> MagicMock:
    """Create a test user mock.

    Returns:
        MagicMock: Mock user with all required attributes
    """
    user = MagicMock()
    user.tg_id = 123456789
    user.full_name = "Test User"
    user.study_group = "ИВТ-101"
    user.is_banned = False
    user.role = UserRole.STUDENT
    user.created_at = MagicMock()
    user.updated_at = MagicMock()
    return user


@pytest_asyncio.fixture
async def test_expert() -> MagicMock:
    """Create a test expert user mock.

    Returns:
        MagicMock: Mock expert user
    """
    user = MagicMock()
    user.tg_id = 987654321
    user.full_name = "Test Expert"
    user.study_group = "ИС-201"
    user.is_banned = False
    user.role = UserRole.EXPERT
    user.created_at = MagicMock()
    user.updated_at = MagicMock()
    return user


@pytest_asyncio.fixture
async def test_organizer() -> MagicMock:
    """Create a test organizer user mock.

    Returns:
        MagicMock: Mock organizer user
    """
    user = MagicMock()
    user.tg_id = 555555555
    user.full_name = "Test Organizer"
    user.study_group = "АД-101"
    user.is_banned = False
    user.role = UserRole.ORGANIZER
    user.created_at = MagicMock()
    user.updated_at = MagicMock()
    return user


@pytest_asyncio.fixture
async def test_campaign() -> MagicMock:
    """Create a test campaign mock.

    Returns:
        MagicMock: Mock campaign
    """
    campaign = MagicMock()
    campaign.id = 1
    campaign.title = "Test Campaign"
    campaign.type = CampaignType.EXPERT
    campaign.min_score = 0
    campaign.max_score = 100
    campaign.ttl_minutes = 1440
    campaign.is_expert_anon = False
    campaign.is_active = True
    campaign.created_at = MagicMock()
    campaign.updated_at = MagicMock()
    campaign.submissions = []
    return campaign


@pytest_asyncio.fixture
async def test_submission() -> MagicMock:
    """Create a test submission mock.

    Returns:
        MagicMock: Mock submission
    """
    submission = MagicMock()
    submission.id = 1
    submission.campaign_id = 1
    submission.author_id = 123456789
    submission.file_id = "test_file_id_123"
    submission.status = SubmissionStatus.UPLOADED
    submission.created_at = MagicMock()
    submission.created_at.strftime = MagicMock(return_value="01.01.2024 12:00")
    submission.updated_at = MagicMock()
    submission.campaign = MagicMock()
    submission.author = MagicMock()
    return submission


@pytest_asyncio.fixture
async def test_review() -> MagicMock:
    """Create a test review mock.

    Returns:
        MagicMock: Mock review
    """
    review = MagicMock()
    review.id = 1
    review.submission_id = 1
    review.reviewer_id = 987654321
    review.score = 85
    review.comment_text = "Good work!"
    review.voice_file_id = None
    review.created_at = MagicMock()
    review.updated_at = MagicMock()
    return review


@pytest_asyncio.fixture
async def event_loop():
    """Create a fresh event loop for async tests.

    Yields:
        asyncio.AbstractEventLoop: Event loop for async tests
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
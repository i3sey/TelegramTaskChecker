"""Mock services for integration testing."""
import json
from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_user_service():
    """Mock UserService for testing.

    Returns a MagicMock that can be configured to return user data.
    """
    service = MagicMock()

    # Default user data
    default_user = MagicMock()
    default_user.tg_id = 123456789
    default_user.full_name = "Test User"
    default_user.study_group = "ИВТ-101"
    default_user.is_banned = False
    default_user.role = MagicMock()
    default_user.role.value = "student"

    service.get_user = AsyncMock(return_value=None)
    service.create_user = AsyncMock(return_value=default_user)
    service.update_user = AsyncMock(return_value=default_user)

    return service


@pytest.fixture
def mock_queue_service():
    """Mock QueueService for Redis queue testing.

    Simulates Redis-based submission locking.
    """
    service = MagicMock()

    # Internal state for simulating Redis
    locks: dict[int, dict[str, Any]] = {}

    async def mock_lock_submission(
        submission_id: int,
        expert_id: int,
        ttl_minutes: int,
    ) -> bool:
        """Simulate Redis lock with NX option."""
        if submission_id in locks:
            return False  # Already locked
        locks[submission_id] = {
            "expert_id": expert_id,
            "locked_at": datetime.utcnow().isoformat(),
            "ttl_minutes": ttl_minutes,
        }
        return True

    async def mock_unlock_submission(submission_id: int) -> bool:
        """Simulate Redis unlock."""
        if submission_id in locks:
            del locks[submission_id]
            return True
        return False

    async def mock_is_locked(submission_id: int) -> bool:
        """Check if submission is locked."""
        return submission_id in locks

    async def mock_get_lock_info(submission_id: int) -> Optional[dict[str, Any]]:
        """Get lock information."""
        return locks.get(submission_id)

    async def mock_get_all_locked() -> list[dict[str, Any]]:
        """Get all locked submissions."""
        result = []
        for sub_id, info in locks.items():
            lock_info = info.copy()
            lock_info["submission_id"] = sub_id
            lock_info["ttl_seconds"] = 3600
            result.append(lock_info)
        return result

    service.lock_submission = mock_lock_submission
    service.unlock_submission = mock_unlock_submission
    service.is_submission_locked = mock_is_locked
    service.get_lock_info = mock_get_lock_info
    service.get_all_locked_submissions = mock_get_all_locked
    service.health_check = AsyncMock(return_value=True)

    # Expose locks for test assertions
    service._locks = locks

    return service


@pytest.fixture
def mock_sheets_service():
    """Mock Google Sheets service for testing.

    Simulates Google Sheets API interactions.
    """
    service = MagicMock()

    # Track appended reviews
    append_history: list[dict[str, Any]] = []

    async def mock_append_review(review_data: dict[str, Any]) -> bool:
        """Simulate appending review to Google Sheets."""
        append_history.append(review_data.copy())
        return True

    async def mock_append_submission(submission_data: dict[str, Any]) -> bool:
        """Simulate appending submission to Google Sheets."""
        return True

    service.append_review = mock_append_review
    service.append_submission = mock_append_submission
    service.health_check = AsyncMock(return_value=True)

    # Expose history for test assertions
    service._append_history = append_history

    return service


@pytest.fixture
def mock_campaign_service():
    """Mock CampaignService for testing."""
    service = MagicMock()

    # Default campaign
    default_campaign = MagicMock()
    default_campaign.id = 1
    default_campaign.title = "Test Campaign"
    default_campaign.type = MagicMock()
    default_campaign.type.value = "expert"
    default_campaign.min_score = 0
    default_campaign.max_score = 100
    default_campaign.ttl_minutes = 1440
    default_campaign.is_active = True
    default_campaign.is_expert_anon = False

    service.get_campaign = AsyncMock(return_value=default_campaign)
    service.get_active_campaigns = AsyncMock(return_value=[default_campaign])
    service.create_campaign = AsyncMock(return_value=default_campaign)

    return service


@pytest.fixture
def mock_submission_service():
    """Mock SubmissionService for testing."""
    service = MagicMock()

    # Default submission
    default_submission = MagicMock()
    default_submission.id = 1
    default_submission.campaign_id = 1
    default_submission.author_id = 123456789
    default_submission.file_id = "test_file_id"
    default_submission.status = MagicMock()
    default_submission.status.value = "uploaded"
    default_submission.created_at = MagicMock()
    default_submission.created_at.strftime = MagicMock(return_value="01.01.2024 12:00")

    service.create_submission = AsyncMock(return_value=default_submission)
    service.get_submission = AsyncMock(return_value=default_submission)
    service.get_pending_submissions = AsyncMock(return_value=[default_submission])

    return service


@pytest.fixture
def mock_review_service():
    """Mock ReviewService for testing."""
    service = MagicMock()

    # Default review
    default_review = MagicMock()
    default_review.id = 1
    default_review.submission_id = 1
    default_review.reviewer_id = 987654321
    default_review.score = 85
    default_review.comment_text = "Good work!"
    default_review.created_at = MagicMock()

    service.create_review = AsyncMock(return_value=default_review)
    service.get_reviews_by_submission = AsyncMock(return_value=[default_review])

    return service


@pytest.fixture
def mock_notification_service():
    """Mock NotificationService for testing."""
    service = MagicMock()

    service.notify_student_reviewed = AsyncMock(return_value=True)
    service.notify_expert_assigned = AsyncMock(return_value=True)
    service.notify_campaign_created = AsyncMock(return_value=True)

    return service
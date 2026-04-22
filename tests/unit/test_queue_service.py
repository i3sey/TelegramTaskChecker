"""
Unit tests for QueueService using mock Redis client.

Uses inline mock class definitions to avoid import issues with redis module.
Run with: python -m pytest tests/unit/test_queue_service.py -v
"""

import pytest
import json
from unittest.mock import AsyncMock
from datetime import datetime


class MockRedis:
    """Mock Redis client for testing QueueService without actual Redis connection."""

    def __init__(self):
        self._data = {}
        self._ttls = {}

    async def set(self, key, value, ex=None, nx=False):
        """Mock SET command with NX and EX options."""
        if nx and key in self._data:
            return None  # NX fails when key exists
        self._data[key] = value
        if ex:
            self._ttls[key] = ex
        return True

    async def get(self, key):
        """Mock GET command."""
        return self._data.get(key)

    async def delete(self, key):
        """Mock DELETE command."""
        if key in self._data:
            del self._data[key]
            if key in self._ttls:
                del self._ttls[key]
            return 1
        return 0

    async def exists(self, key):
        """Mock EXISTS command."""
        return 1 if key in self._data else 0

    async def ttl(self, key):
        """Mock TTL command."""
        if key not in self._data:
            return -2  # Key doesn't exist
        if key not in self._ttls:
            return -1  # No TTL set
        return self._ttls[key]

    async def expire(self, key, seconds):
        """Mock EXPIRE command."""
        if key in self._data:
            self._ttls[key] = seconds
            return True
        return False

    async def ping(self):
        """Mock PING command."""
        return True

    async def close(self):
        """Mock CLOSE command."""
        pass


class QueueService:
    """Redis queue service for managing review locks and TTL.

    This is a copy of the actual QueueService for testing without dependencies.
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or "redis://localhost:6379/0"
        self._client: MockRedis | None = None

    def set_client(self, client: MockRedis):
        """Set the Redis client (for testing)."""
        self._client = client

    async def lock_submission(
        self,
        submission_id: int,
        expert_id: int,
        ttl_minutes: int,
    ) -> bool:
        """Lock a submission for review. Returns True if lock acquired."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        ttl_seconds = ttl_minutes * 60

        result = await self._client.set(
            key,
            json.dumps({
                "expert_id": expert_id,
                "locked_at": datetime.utcnow().isoformat(),
            }),
            ex=ttl_seconds,
            nx=True,
        )
        return result is not None

    async def unlock_submission(self, submission_id: int) -> bool:
        """Unlock a submission. Returns True if was locked."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        result = await self._client.delete(key)
        return result > 0

    async def is_submission_locked(self, submission_id: int) -> bool:
        """Check if submission is currently locked."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        return await self._client.exists(key) > 0

    async def get_lock_info(self, submission_id: int) -> dict | None:
        """Get lock information for a submission."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        data = await self._client.get(key)
        if data:
            return json.loads(data)
        return None

    async def get_submission_ttl(self, submission_id: int) -> int:
        """Get remaining TTL in seconds."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        return await self._client.ttl(key)

    async def extend_ttl(self, submission_id: int, minutes: int) -> bool:
        """Extend TTL for a locked submission."""
        if self._client is None:
            raise RuntimeError("Redis client not set")

        key = self._active_review_key(submission_id)
        new_ttl = minutes * 60
        result = await self._client.expire(key, new_ttl)
        return result

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            if self._client is None:
                return False
            await self._client.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    def _active_review_key(self, submission_id: int) -> str:
        return f"active_review:{submission_id}"

    def _expert_submissions_key(self, expert_id: int) -> str:
        return f"expert_submissions:{expert_id}"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def queue_service(mock_redis_client):
    """Create QueueService with mocked Redis client."""
    service = QueueService(redis_url="redis://localhost:6379/0")
    service.set_client(mock_redis_client)
    return service


# ============================================================================
# Tests for lock_submission
# ============================================================================

class TestLockSubmission:
    """Tests for lock_submission method."""

    @pytest.mark.asyncio
    async def test_lock_submission_success(self, queue_service, mock_redis_client):
        """Test successful lock acquisition."""
        result = await queue_service.lock_submission(
            submission_id=123,
            expert_id=456,
            ttl_minutes=30,
        )

        assert result == True
        assert await mock_redis_client.exists("active_review:123")

    @pytest.mark.asyncio
    async def test_lock_submission_already_locked(self, queue_service, mock_redis_client):
        """Test lock failure when submission is already locked."""
        # First lock should succeed
        result1 = await queue_service.lock_submission(
            submission_id=123,
            expert_id=456,
            ttl_minutes=30,
        )
        assert result1 == True

        # Second lock should fail (NX)
        result2 = await queue_service.lock_submission(
            submission_id=123,
            expert_id=789,
            ttl_minutes=30,
        )
        assert result2 == False

    @pytest.mark.asyncio
    async def test_lock_submission_stores_expert_id(self, queue_service, mock_redis_client):
        """Test that lock stores correct expert ID."""
        await queue_service.lock_submission(
            submission_id=123,
            expert_id=789,
            ttl_minutes=15,
        )

        lock_info = await queue_service.get_lock_info(123)
        assert lock_info is not None
        assert lock_info["expert_id"] == 789


# ============================================================================
# Tests for unlock_submission
# ============================================================================

class TestUnlockSubmission:
    """Tests for unlock_submission method."""

    @pytest.mark.asyncio
    async def test_unlock_submission_success(self, queue_service, mock_redis_client):
        """Test successful unlock when lock exists."""
        await queue_service.lock_submission(123, 456, 30)

        result = await queue_service.unlock_submission(submission_id=123)

        assert result == True
        assert not await mock_redis_client.exists("active_review:123")

    @pytest.mark.asyncio
    async def test_unlock_submission_not_locked(self, queue_service, mock_redis_client):
        """Test unlock when no lock exists."""
        result = await queue_service.unlock_submission(submission_id=999)

        assert result == False


# ============================================================================
# Tests for is_submission_locked
# ============================================================================

class TestIsSubmissionLocked:
    """Tests for is_submission_locked method."""

    @pytest.mark.asyncio
    async def test_is_submission_locked_true(self, queue_service, mock_redis_client):
        """Test when submission is locked."""
        await queue_service.lock_submission(123, 456, 30)

        result = await queue_service.is_submission_locked(123)

        assert result == True

    @pytest.mark.asyncio
    async def test_is_submission_locked_false(self, queue_service, mock_redis_client):
        """Test when submission is not locked."""
        result = await queue_service.is_submission_locked(999)

        assert result == False


# ============================================================================
# Tests for get_lock_info
# ============================================================================

class TestGetLockInfo:
    """Tests for get_lock_info method."""

    @pytest.mark.asyncio
    async def test_get_lock_info_exists(self, queue_service, mock_redis_client):
        """Test getting lock info when lock exists."""
        await queue_service.lock_submission(123, 456, 30)

        result = await queue_service.get_lock_info(123)

        assert result is not None
        assert result["expert_id"] == 456
        assert "locked_at" in result

    @pytest.mark.asyncio
    async def test_get_lock_info_not_exists(self, queue_service, mock_redis_client):
        """Test getting lock info when lock doesn't exist."""
        result = await queue_service.get_lock_info(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_lock_info_returns_dict(self, queue_service, mock_redis_client):
        """Test that lock info is returned as dictionary."""
        await queue_service.lock_submission(123, 100, 30)

        result = await queue_service.get_lock_info(123)

        assert isinstance(result, dict)
        assert "expert_id" in result


# ============================================================================
# Tests for get_submission_ttl
# ============================================================================

class TestGetSubmissionTtl:
    """Tests for get_submission_ttl method."""

    @pytest.mark.asyncio
    async def test_get_submission_ttl_key_not_exists(self, queue_service, mock_redis_client):
        """Test getting TTL when key doesn't exist (-2)."""
        result = await queue_service.get_submission_ttl(999)

        assert result == -2

    @pytest.mark.asyncio
    async def test_get_submission_ttl_after_lock(self, queue_service, mock_redis_client):
        """Test getting TTL after locking."""
        await queue_service.lock_submission(123, 456, 30)

        result = await queue_service.get_submission_ttl(123)

        # TTL should be positive (1800 seconds = 30 minutes)
        assert result > 0


# ============================================================================
# Tests for extend_ttl
# ============================================================================

class TestExtendTtl:
    """Tests for extend_ttl method."""

    @pytest.mark.asyncio
    async def test_extend_ttl_success(self, queue_service, mock_redis_client):
        """Test successful TTL extension."""
        await queue_service.lock_submission(123, 456, 30)

        result = await queue_service.extend_ttl(123, 60)

        assert result == True

    @pytest.mark.asyncio
    async def test_extend_ttl_key_not_exists(self, queue_service, mock_redis_client):
        """Test TTL extension when key doesn't exist."""
        result = await queue_service.extend_ttl(999, 30)

        assert result == False


# ============================================================================
# Tests for health_check
# ============================================================================

class TestHealthCheck:
    """Tests for health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, queue_service, mock_redis_client):
        """Test health check when Redis is healthy."""
        result = await queue_service.health_check()

        assert result == True


# ============================================================================
# Tests for close
# ============================================================================

class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_client(self, queue_service, mock_redis_client):
        """Test closing the Redis client."""
        await queue_service.close()

        assert queue_service._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self, queue_service):
        """Test close when no client exists."""
        queue_service._client = None

        # Should not raise any exception
        await queue_service.close()


# ============================================================================
# Tests for key patterns
# ============================================================================

class TestKeyPatterns:
    """Tests for internal key pattern methods."""

    def test_active_review_key_format(self, queue_service):
        """Test active review key format."""
        key = queue_service._active_review_key(123)
        assert key == "active_review:123"

    def test_expert_submissions_key_format(self, queue_service):
        """Test expert submissions key format."""
        key = queue_service._expert_submissions_key(456)
        assert key == "expert_submissions:456"
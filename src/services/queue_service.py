"""Redis-based queue service for managing submission review locks."""
import json
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from src.config import config
from src.db.models import SubmissionStatus


class QueueService:
    """Redis queue service for managing review locks and TTL."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or config.redis.url
        self._client: redis.Redis | None = None

    async def get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    # Key patterns
    def _active_review_key(self, submission_id: int) -> str:
        return f"active_review:{submission_id}"

    def _expert_submissions_key(self, expert_id: int) -> str:
        return f"expert_submissions:{expert_id}"

    async def lock_submission(
        self,
        submission_id: int,
        expert_id: int,
        ttl_minutes: int,
    ) -> bool:
        """
        Lock a submission for review. Returns True if lock acquired.

        Args:
            submission_id: Submission ID
            expert_id: Telegram ID of expert
            ttl_minutes: Time-to-live in minutes

        Returns:
            True if lock was acquired, False if submission already locked
        """
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        ttl_seconds = ttl_minutes * 60

        # Try to set key only if it doesn't exist (NX)
        result = await client.set(
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
        """
        Unlock a submission. Returns True if was locked.

        Args:
            submission_id: Submission ID

        Returns:
            True if submission was unlocked
        """
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        result = await client.delete(key)
        return result > 0

    async def is_submission_locked(self, submission_id: int) -> bool:
        """Check if submission is currently locked."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        return await client.exists(key) > 0

    async def get_lock_info(self, submission_id: int) -> dict[str, Any] | None:
        """Get lock information for a submission."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        data = await client.get(key)
        if data:
            return json.loads(data)
        return None

    async def get_submission_ttl(self, submission_id: int) -> int:
        """Get remaining TTL in seconds. Returns -1 if no TTL, -2 if key doesn't exist."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        return await client.ttl(key)

    async def extend_ttl(self, submission_id: int, minutes: int) -> bool:
        """Extend TTL for a locked submission."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        new_ttl = minutes * 60
        result = await client.expire(key, new_ttl)
        return result

    async def get_expired_submissions(self) -> list[int]:
        """Get list of submission IDs with expired locks (for cleanup)."""
        client = await self.get_client()
        expired = []
        async for key in client.scan_iter("active_review:*"):
            ttl = await client.ttl(key)
            if ttl < 0:  # No TTL or expired
                submission_id = int(key.split(":")[1])
                expired.append(submission_id)
        return expired

    async def get_all_locked_submissions(self) -> list[dict[str, Any]]:
        """Get all currently locked submissions."""
        client = await self.get_client()
        locked = []
        async for key in client.scan_iter("active_review:*"):
            data = await client.get(key)
            if data:
                submission_id = int(key.split(":")[1])
                info = json.loads(data)
                info["submission_id"] = submission_id
                info["ttl_seconds"] = await client.ttl(key)
                locked.append(info)
        return locked

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            client = await self.get_client()
            await client.ping()
            return True
        except Exception:
            return False


# Global instance
queue_service = QueueService()

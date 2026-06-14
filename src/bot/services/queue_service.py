"""Redis-based queue service for managing submission review locks."""
import json
import secrets
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

from src.config import config
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

    def _review_deadlines_key(self) -> str:
        return "review_lock_deadlines"

    async def lock_submission(
        self,
        submission_id: int,
        expert_id: int,
        ttl_minutes: int,
    ) -> str | None:
        """
        Lock a submission for review. Returns True if lock acquired.

        Args:
            submission_id: Submission ID
            expert_id: Telegram ID of expert
            ttl_minutes: Time-to-live in minutes

        Returns:
            Opaque lock token if acquired, otherwise None
        """
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        ttl_seconds = ttl_minutes * 60
        lock_token = secrets.token_urlsafe(24)

        result = await client.set(
            key,
            json.dumps({
                "expert_id": expert_id,
                "locked_at": datetime.now(timezone.utc).isoformat(),
                "token": lock_token,
            }),
            ex=ttl_seconds,
            nx=True,
        )
        if result:
            deadline = datetime.now(timezone.utc).timestamp() + ttl_seconds
            await client.set(
                self._expert_submissions_key(expert_id),
                str(submission_id),
                ex=ttl_seconds,
            )
            await client.zadd(
                self._review_deadlines_key(),
                {str(submission_id): deadline},
            )
            return lock_token
        return None

    async def unlock_submission(
        self,
        submission_id: int,
        *,
        expert_id: int,
        lock_token: str,
    ) -> bool:
        """Release a lock only when both owner and opaque token match."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        owner_key = self._expert_submissions_key(expert_id)
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return 0 end
        local lock = cjson.decode(raw)
        if tostring(lock.expert_id) ~= ARGV[1] or lock.token ~= ARGV[2] then
            return 0
        end
        redis.call('DEL', KEYS[1])
        if redis.call('GET', KEYS[2]) == ARGV[3] then
            redis.call('DEL', KEYS[2])
        end
        redis.call('ZREM', KEYS[3], ARGV[3])
        return 1
        """
        result = await client.eval(
            script,
            3,
            key,
            owner_key,
            self._review_deadlines_key(),
            str(expert_id),
            lock_token,
            str(submission_id),
        )
        return bool(result)

    async def force_unlock_submission(self, submission_id: int) -> bool:
        """Administrative cleanup for stale locks."""
        client = await self.get_client()
        key = self._active_review_key(submission_id)
        lock_info = await self.get_lock_info(submission_id)
        result = await client.delete(key)
        if lock_info and lock_info.get("expert_id") is not None:
            owner_id = int(lock_info["expert_id"])
            owner_key = self._expert_submissions_key(owner_id)
            if await client.get(owner_key) == str(submission_id):
                await client.delete(owner_key)
        await client.zrem(self._review_deadlines_key(), str(submission_id))
        return result > 0

    async def get_expert_current_submission(self, expert_id: int) -> int | None:
        """Get the currently assigned submission for an expert."""
        client = await self.get_client()
        value = await client.get(self._expert_submissions_key(expert_id))
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def clear_expert_current_submission(self, expert_id: int) -> None:
        """Clear the cached current submission for an expert."""
        client = await self.get_client()
        await client.delete(self._expert_submissions_key(expert_id))

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
        if result:
            deadline = datetime.now(timezone.utc).timestamp() + new_ttl
            await client.zadd(
                self._review_deadlines_key(),
                {str(submission_id): deadline},
            )
        return result

    async def get_expired_submissions(self) -> list[int]:
        """Get submission IDs whose logical lock deadline has passed."""
        client = await self.get_client()
        now = datetime.now(timezone.utc).timestamp()
        values = await client.zrangebyscore(
            self._review_deadlines_key(),
            min="-inf",
            max=now,
        )
        return [int(value) for value in values]

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

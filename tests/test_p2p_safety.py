import json

import pytest

from src.bot.handlers.common_review_flow import (
    format_comment_saved_text,
    format_review_saved_summary,
)
from src.bot.models import Review, Submission
from src.bot.services.queue_service import QueueService


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def exists(self, key):
        return int(key in self.values)

    async def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    async def zrem(self, key, member):
        return int(self.sorted_sets.get(key, {}).pop(member, None) is not None)

    async def zrangebyscore(self, key, min, max):
        return [
            member
            for member, score in self.sorted_sets.get(key, {}).items()
            if score <= float(max)
        ]

    async def eval(self, script, numkeys, lock_key, owner_key, deadlines_key, *args):
        owner_id, token, submission_id = args
        raw = self.values.get(lock_key)
        if raw is None:
            return 0
        lock = json.loads(raw)
        if str(lock["expert_id"]) != owner_id or lock["token"] != token:
            return 0
        self.values.pop(lock_key, None)
        if self.values.get(owner_key) == submission_id:
            self.values.pop(owner_key, None)
        self.sorted_sets.get(deadlines_key, {}).pop(submission_id, None)
        return 1


@pytest.mark.asyncio
async def test_review_lock_requires_owner_and_token():
    service = QueueService("redis://unused")
    fake = FakeRedis()
    service._client = fake

    token = await service.lock_submission(15, 1001, 10)

    assert token
    assert not await service.unlock_submission(
        15,
        expert_id=1002,
        lock_token=token,
    )
    assert await service.is_submission_locked(15)
    assert not await service.unlock_submission(
        15,
        expert_id=1001,
        lock_token="stale-token",
    )
    assert await service.unlock_submission(
        15,
        expert_id=1001,
        lock_token=token,
    )
    assert not await service.is_submission_locked(15)

    second_token = await service.lock_submission(16, 1001, 10)
    assert second_token
    fake.sorted_sets[service._review_deadlines_key()]["16"] = 0
    assert await service.get_expired_submissions() == [16]
    await service.force_unlock_submission(16)


def test_review_uniqueness_and_p2p_completion_field_exist():
    constraint_names = {constraint.name for constraint in Review.__table__.constraints}

    assert "uq_reviews_submission_reviewer" in constraint_names
    assert "p2p_completed_at" in Submission.__table__.c


def test_review_text_is_html_escaped():
    comment = "<b>подмена</b> & текст"

    assert "<b>подмена</b>" not in format_comment_saved_text(
        comment_text=comment,
        next_step_text="Дальше",
    )
    assert "&lt;b&gt;подмена&lt;/b&gt;" in format_review_saved_summary(
        submission_id=1,
        score=5,
        comment_summary=comment,
    )

"""Notification service with throttling for Telegram messages."""
import asyncio
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from aiogram import Bot

from src.config import config
from src.utils.logging import logger


class NotificationService:
    """Service for sending notifications to users with throttling."""

    # Redis key patterns
    _RATE_LIMIT_KEY = "notification_rate:{tg_id}"
    _BAN_CHECK_KEY = "user_ban:{tg_id}"

    # Throttling settings
    DEFAULT_DELAY_SECONDS = 0.1  # Delay between messages to avoid flood limit
    RATE_LIMIT_SECONDS = 60  # Rate limit window

    def __init__(self, bot: Bot, redis_client: redis.Redis | None = None):
        """
        Initialize notification service.

        Args:
            bot: Aiogram Bot instance
            redis_client: Optional Redis client for throttling
        """
        self.bot = bot
        self._redis_client = redis_client
        self._redis_url = config.redis.url

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._redis_client is None:
            self._redis_client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis_client

    async def _check_rate_limit(self, tg_id: int) -> bool:
        """
        Check if user is within rate limit. Returns True if can send.

        Args:
            tg_id: Telegram user ID

        Returns:
            True if within rate limit, False if throttled
        """
        client = await self._get_redis()
        key = self._RATE_LIMIT_KEY.format(tg_id=tg_id)

        # Check if key exists
        exists = await client.exists(key)
        if exists:
            return False

        # Set rate limit key with TTL
        await client.setex(key, self.RATE_LIMIT_SECONDS, "1")
        return True

    async def _apply_delay(self) -> None:
        """Apply delay between messages to avoid flood limit."""
        await asyncio.sleep(self.DEFAULT_DELAY_SECONDS)

    async def notify_user(self, tg_id: int, message: str) -> bool:
        """
        Send notification to user. Returns success status.

        Args:
            tg_id: Telegram user ID
            message: Message text to send

        Returns:
            True if message sent successfully, False otherwise
        """
        try:
            # Check rate limit
            can_send = await self._check_rate_limit(tg_id)
            if not can_send:
                logger.warning(
                    f"Rate limited: not sending notification to user {tg_id}"
                )
                return False

            # Apply delay to avoid flood
            await self._apply_delay()

            # Send message
            await self.bot.send_message(chat_id=tg_id, text=message)
            logger.info(f"Notification sent to user {tg_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send notification to {tg_id}: {e}")
            return False

    async def notify_student_reviewed(
        self,
        student_tg_id: int,
        campaign_title: str,
        score: int,
        comment: str | None,
    ) -> None:
        """
        Notify student about completed review.

        Args:
            student_tg_id: Student's Telegram ID
            campaign_title: Title of the campaign
            score: Review score received
            comment: Optional review comment
        """
        message_parts = [
            f"📋 <b>Ваша работа проверена!</b>\n\n",
            f"Кампания: <b>{campaign_title}</b>\n",
            f"Оценка: <b>{score}</b>\n",
        ]

        if comment:
            message_parts.append(f"Комментарий: <i>{comment}</i>\n")

        message_parts.append("\nПодробности в боте.")
        message = "".join(message_parts)

        success = await self.notify_user(student_tg_id, message)
        if not success:
            logger.warning(
                f"Could not notify student {student_tg_id} about review"
            )

    async def notify_expert_new_work(
        self,
        expert_tg_id: int,
        campaign_title: str,
    ) -> None:
        """
        Notify expert about new work in queue.

        Args:
            expert_tg_id: Expert's Telegram ID
            campaign_title: Title of the campaign
        """
        message = (
            f"📬 <b>Новая работа в очереди!</b>\n\n"
            f"Кампания: <b>{campaign_title}</b>\n\n"
            "Используйте /take для проверки работы."
        )

        success = await self.notify_user(expert_tg_id, message)
        if not success:
            logger.warning(
                f"Could not notify expert {expert_tg_id} about new work"
            )

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
"""Background task for checking expired submission locks."""
import asyncio
from aiogram import Bot

from src.services.queue_service import queue_service
from src.services.submission_service import update_submission_status
from src.db.engine import session_scope
from src.db.models import SubmissionStatus
from src.utils.logging import logger


async def check_expired_locks(bot: Bot) -> None:
    """
    Background task to check and return expired submission locks to queue.

    This runs periodically (every 60 seconds) and:
    1. Finds submissions with expired Redis locks
    2. Updates their status back to UPLOADED in the database
    3. Optionally notifies experts that their work was returned
    """
    while True:
        try:
            # Check Redis health first
            if not await queue_service.health_check():
                logger.warning("Redis unavailable, skipping expired lock check")
                await asyncio.sleep(60)
                continue

            # Find expired locks
            expired_ids = await queue_service.get_expired_submissions()

            if expired_ids:
                logger.info(f"Found {len(expired_ids)} expired submission locks")

                for submission_id in expired_ids:
                    # Get lock info before deleting
                    lock_info = await queue_service.get_lock_info(submission_id)
                    expert_id = lock_info.get("expert_id") if lock_info else None

                    # Unlock from Redis
                    await queue_service.unlock_submission(submission_id)

                    # Update DB status
                    async with session_scope() as session:
                        await update_submission_status(
                            submission_id,
                            SubmissionStatus.UPLOADED,
                            session
                        )

                    logger.info(f"Returned expired submission {submission_id} to queue")

                    # Optionally notify expert
                    if expert_id:
                        try:
                            await bot.send_message(
                                expert_id,
                                f"⏰ <b>Время проверки истекло</b>\n\n"
                                f"Работа (ID: <code>{submission_id}</code>) "
                                "возвращена в очередь автоматически.",
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logger.warning(f"Could not notify expert {expert_id}: {e}")

            # Also log queue health status
            locked = await queue_service.get_all_locked_submissions()
            if locked:
                logger.debug(f"Currently {len(locked)} submissions are being reviewed")

        except Exception as e:
            logger.error(f"Error in expired locks check: {e}")

        # Wait before next check
        await asyncio.sleep(60)


def start_expired_locks_scheduler(bot: Bot) -> asyncio.Task:
    """Start the expired locks checker as a background task."""
    return asyncio.create_task(check_expired_locks(bot))

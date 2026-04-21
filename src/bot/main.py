"""Main entry point for the Telegram bot application."""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings, setup_logging

logger = logging.getLogger(__name__)


async def main():
    """Initialize and start the bot."""
    
    # Setup logging
    setup_logging()
    logger.info("Starting TelegramTaskChecker bot...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Database URL: {settings.database_url}")
    logger.info(f"Redis URL: {settings.redis_url}")

    # Create temp directory for file uploads
    temp_dir = Path(settings.file_upload_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Temp file directory: {temp_dir}")

    # Initialize bot and dispatcher
    bot = Bot(token=settings.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    logger.info("Bot initialized successfully")
    logger.info("Dispatcher initialized successfully")

    # TODO: Register routers here
    # from src.bot.handlers import student_router, expert_router, organizer_router
    # dp.include_router(student_router.router)
    # dp.include_router(expert_router.router)
    # dp.include_router(organizer_router.router)

    try:
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


if __name__ == "__main__":
    asyncio.run(main())

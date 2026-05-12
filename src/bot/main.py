"""Echo bot entry point."""

import asyncio
from aiogram import Bot, Dispatcher, Router, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

from dotenv import load_dotenv
import os

from src.config import config
from src.db.engine import init_db, session_scope
from src.bot.handlers.auth_router import router as auth_router
from src.bot.handlers.campaign_router import router as campaign_router
from src.bot.handlers.expert_router import router as expert_router
from src.bot.handlers.student_router import router as student_router
from src.bot.handlers.organizer_router import router as organizer_router
from src.bot.handlers.peer_router import router as peer_router
from src.bot.middlewares.ban_check import BanCheckMiddleware
from src.bot.utils.logging import logger
from src.bot.services.queue_service import queue_service
from src.bot.services.expired_locks import start_expired_locks_scheduler
from src.bot.services.user_service import get_user
from src.bot.ui import fallback_text


# Load environment
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or config.bot.token

_proxy_url = os.getenv("HTTP_PROXY")
if not _proxy_url and config.bot.proxy:
    _proxy_url = config.bot.proxy.get("http") or config.bot.proxy.get("https")


async def on_startup(bot: Bot) -> None:
    """Run on bot startup."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully")

    bot_info = await bot.get_me()
    logger.info(f"Bot username: @{bot_info.username}")
    logger.info(f"Bot ID: {bot_info.id}")

    start_expired_locks_scheduler(bot)
    logger.info("Started expired locks scheduler")


async def on_shutdown(bot: Bot) -> None:
    """Run on bot shutdown."""
    logger.info("Shutting down bot...")
    await queue_service.close()
    await bot.session.close()


async def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment")
        return

    if _proxy_url:
        logger.info(f"Using proxy: {_proxy_url}")
        session = AiohttpSession(proxy=_proxy_url)
        bot = Bot(token=BOT_TOKEN, session=session)
    else:
        logger.info("No proxy configured")
        bot = Bot(token=BOT_TOKEN)

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    fallback_router = Router()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())

    dp.include_router(auth_router)
    dp.include_router(student_router)
    dp.include_router(campaign_router)
    dp.include_router(expert_router)
    dp.include_router(organizer_router)
    dp.include_router(peer_router)

    @fallback_router.message()
    async def fallback_handler(message: types.Message):
        async with session_scope() as session:
            user = await get_user(tg_id=message.from_user.id, session=session)

        await message.answer(
            fallback_text(is_registered=bool(user)),
            parse_mode="HTML",
        )

    dp.include_router(fallback_router)

    logger.info("Starting bot...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await on_shutdown(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

"""Main bot entry point for the Telegram Expert Review Queue system.

This module initializes the bot, dispatcher, routers, and middleware.
It serves as the main application entry point.
"""

import asyncio
import logging
from typing import Any

from aiogram import Dispatcher, Router, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers import student_router, expert_router, organizer_router
from src.bot.middleware import AuthMiddleware


logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Main Telegram bot class for Expert Review Queue System.
    
    Handles initialization of bot, dispatcher, routers, and middleware.
    Manages bot lifecycle and error handling.
    """
    
    def __init__(self, token: str, approved_users: dict[int, str] | None = None):
        """
        Initialize the Telegram bot.
        
        Args:
            token: Telegram bot token
            approved_users: Dictionary mapping user IDs to roles
                           (student, expert, organizer)
        """
        self.token = token
        self.bot = Bot(token=token, parse_mode=ParseMode.HTML)
        self.storage = MemoryStorage()
        self.dispatcher = Dispatcher(storage=self.storage)
        self.router = Router()
        self.approved_users = approved_users or {}
        
        self._setup_middleware()
        self._register_routers()
        self._setup_error_handlers()
    
    def _setup_middleware(self) -> None:
        """Configure and add middleware to the dispatcher."""
        auth_middleware = AuthMiddleware(self.approved_users)
        self.dispatcher.message.middleware(auth_middleware)
    
    def _register_routers(self) -> None:
        """Register all sub-routers to the main router."""
        self.dispatcher.include_router(student_router)
        self.dispatcher.include_router(expert_router)
        self.dispatcher.include_router(organizer_router)
        self.dispatcher.include_router(self.router)
    
    def _setup_error_handlers(self) -> None:
        """Setup error handlers for the dispatcher."""
        @self.router.message()
        async def handle_unknown_command(message: types.Message) -> None:
            """Handle unknown commands with a helpful message."""
            help_text = (
                "❌ Unknown command!\n\n"
                "Available commands depend on your role:\n\n"
                "👨‍🎓 **Students:**\n"
                "/start, /submit, /status, /help\n\n"
                "👨‍🏫 **Experts:**\n"
                "/queue, /take, /submit_feedback, /rating, /stats\n\n"
                "🏢 **Organizers:**\n"
                "/create_session, /set_criteria, /view_results, /export, /manage_users, /analytics\n\n"
                "Need help? Type /help"
            )
            await message.answer(help_text)
    
    async def start(self) -> None:
        """
        Start the bot and begin polling for updates.
        
        This method starts the bot in polling mode and keeps it running.
        """
        logger.info("Starting Telegram bot...")
        
        try:
            await self.bot.delete_webhook(drop_pending_updates=True)
            await self.dispatcher.start_polling(
                self.bot,
                allowed_updates=self.dispatcher.resolve_used_update_types(),
            )
        except Exception as e:
            logger.error(f"Error during bot polling: {e}")
            raise
        finally:
            await self.bot.session.close()
    
    def set_approved_users(self, approved_users: dict[int, str]) -> None:
        """
        Update the approved users dictionary.
        
        Args:
            approved_users: Dictionary mapping user IDs to roles
        """
        self.approved_users = approved_users
    
    def add_user(self, user_id: int, role: str) -> None:
        """
        Add a user to the approved list.
        
        Args:
            user_id: Telegram user ID
            role: User role (student, expert, organizer)
        """
        self.approved_users[user_id] = role
        logger.info(f"Added user {user_id} with role {role}")
    
    def remove_user(self, user_id: int) -> None:
        """
        Remove a user from the approved list.
        
        Args:
            user_id: Telegram user ID
        """
        if user_id in self.approved_users:
            self.approved_users.pop(user_id)
            logger.info(f"Removed user {user_id}")


async def create_bot(
    token: str,
    approved_users: dict[int, str] | None = None,
) -> TelegramBot:
    """
    Factory function to create and initialize a bot instance.
    
    Args:
        token: Telegram bot token
        approved_users: Dictionary mapping user IDs to roles
        
    Returns:
        Initialized TelegramBot instance
    """
    bot = TelegramBot(token=token, approved_users=approved_users)
    return bot


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure logging for the bot application.
    
    Args:
        level: Logging level (default: INFO)
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler(),
        ],
    )


async def main() -> None:
    """
    Main entry point for the bot application.
    
    This function initializes logging, creates the bot, and starts polling.
    """
    setup_logging()
    
    # Example approved users (in production, load from database/config)
    approved_users = {
        123456789: "student",  # Replace with real Telegram IDs
        987654321: "expert",
        555555555: "organizer",
    }
    
    # Initialize bot with token from environment
    token = "YOUR_BOT_TOKEN_HERE"
    
    try:
        bot = await create_bot(token=token, approved_users=approved_users)
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

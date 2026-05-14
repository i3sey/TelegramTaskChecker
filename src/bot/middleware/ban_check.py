"""Ban check middleware for aiogram."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.db.engine import session_scope
from src.bot.services.user_service import get_user
from src.bot.utils.logging import logger


class BanCheckMiddleware(BaseMiddleware):
    """
    Middleware to check if user is banned.

    Allows /start command for banned users so they can see the ban message.
    """

    # Commands that are allowed even for banned users
    ALLOWED_COMMANDS = {"start", "cancel"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Check if user is banned before processing the event.

        Args:
            handler: Next handler in chain
            event: Telegram event (Message, CallbackQuery, etc.)
            data: Additional data passed to handler

        Returns:
            Result from handler or ban message if user is banned
        """
        # Get message from event (try different sources)
        message = data.get("message")
        callback = data.get("callback_query")

        # Determine what kind of message object we have
        if message is not None and hasattr(message, "from_user"):
            event_obj = message
        elif callback is not None and hasattr(callback, "from_user"):
            event_obj = callback
        else:
            # Not a message/callback event, allow it
            return await handler(event, data)

        # Extract command from message text
        command = self._extract_command(event_obj)

        # Allow certain commands even for banned users
        if command in self.ALLOWED_COMMANDS:
            return await handler(event, data)

        # Get user from database
        user = data.get("user")
        if user is None:
            # If user object not available, check from message
            tg_id = event_obj.from_user.id
            async with session_scope() as session:
                db_user = await get_user(tg_id=tg_id, session=session)
                if db_user is None:
                    # User not registered, let /start handle registration
                    return await handler(event, data)
                user = db_user

        # Check if user is banned
        if user.is_banned:
            logger.warning(f"Banned user {user.tg_id} tried to access bot")
            await event_obj.answer(
                "🚫 <b>Вы заблокированы.</b>\n\n"
                "Обратитесь к организатору для разблокировки.",
                parse_mode="HTML",
            )
            # Return None to prevent further handling
            return None

        # User is not banned, proceed with handler
        return await handler(event, data)

    def _extract_command(self, message) -> str | None:
        """Extract command name from message."""
        if hasattr(message, "text") and message.text:
            text = message.text.strip()
            if text.startswith("/"):
                # Remove / and get command name (without args)
                parts = text.split()
                if parts:
                    cmd = parts[0].lstrip("/")
                    # Remove any command suffix like @botname
                    if "@" in cmd:
                        cmd = cmd.split("@")[0]
                    return cmd.lower()
        return None

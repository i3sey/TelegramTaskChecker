"""Authentication middleware for verifying Telegram users and roles."""

from typing import Callable, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from aiogram.utils.i18n import I18nMiddleware


class AuthMiddleware(BaseMiddleware):
    """
    Middleware for authenticating Telegram users and checking user roles.
    
    Verifies that incoming messages are from authorized users and attaches
    user role information to the message context.
    """
    
    def __init__(self, approved_users: dict[int, str] | None = None):
        """
        Initialize AuthMiddleware.
        
        Args:
            approved_users: Dictionary mapping Telegram IDs to user roles
                           (student, expert, organizer)
        """
        super().__init__()
        self.approved_users = approved_users or {}
    
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        """
        Process middleware call to verify user authentication and role.
        
        Args:
            handler: Next handler in the middleware chain
            event: The update event from Telegram
            data: Middleware data dictionary
            
        Returns:
            Handler result or None if user is not authorized
        """
        message = event.message
        
        if not message or not message.from_user:
            return await handler(event, data)
        
        user_id = message.from_user.id
        
        if user_id not in self.approved_users:
            await message.answer(
                "❌ You are not authorized to use this bot.\n"
                "Please contact the administrator."
            )
            return
        
        user_role = self.approved_users[user_id]
        data["user_role"] = user_role
        data["user_id"] = user_id
        data["user_first_name"] = message.from_user.first_name or "User"
        
        return await handler(event, data)
    
    def set_approved_users(self, approved_users: dict[int, str]) -> None:
        """
        Update the approved users dictionary.
        
        Args:
            approved_users: Dictionary mapping Telegram IDs to user roles
        """
        self.approved_users = approved_users
    
    def add_approved_user(self, user_id: int, role: str) -> None:
        """
        Add a single approved user.
        
        Args:
            user_id: Telegram user ID
            role: User role (student, expert, organizer)
        """
        self.approved_users[user_id] = role
    
    def remove_approved_user(self, user_id: int) -> None:
        """
        Remove an approved user.
        
        Args:
            user_id: Telegram user ID to remove
        """
        self.approved_users.pop(user_id, None)

"""Authentication middleware."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update


class AuthMiddleware(BaseMiddleware):
    """Attach approved user data to handler context."""

    def __init__(self, approved_users: dict[int, str] | None = None):
        super().__init__()
        self.approved_users = approved_users or {}

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        message = event.message
        if not message or not message.from_user:
            return await handler(event, data)

        user_id = message.from_user.id
        if user_id not in self.approved_users:
            await message.answer(
                "❌ You are not authorized to use this bot.\n"
                "Please contact the administrator."
            )
            return None

        data["user_role"] = self.approved_users[user_id]
        data["user_id"] = user_id
        data["user_first_name"] = message.from_user.first_name or "User"
        return await handler(event, data)

    def set_approved_users(self, approved_users: dict[int, str]) -> None:
        self.approved_users = approved_users

    def add_approved_user(self, user_id: int, role: str) -> None:
        self.approved_users[user_id] = role

    def remove_approved_user(self, user_id: int) -> None:
        self.approved_users.pop(user_id, None)

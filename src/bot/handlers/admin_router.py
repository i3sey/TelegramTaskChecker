"""Admin router for user access management (ban/unban)."""

from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import config
from src.db.engine import session_scope
from src.db.models import User, UserRole
from src.bot.services.user_service import ban_user, get_user, unban_user
from src.bot.ui import role_label
from src.bot.utils.logging import logger


router = Router()
router.name = "admin_router"


PAGE_SIZE = 10


def _is_admin(tg_id: int) -> bool:
    """Return True if Telegram user is configured as bot admin."""
    return tg_id in config.admin_ids


async def _ensure_admin(message: types.Message) -> bool:
    """Check admin access and notify user on denial."""
    if not message.from_user or not _is_admin(message.from_user.id):
        await message.answer("⛔ Эта команда доступна только администраторам.")
        return False
    return True


async def _ensure_admin_callback(callback: types.CallbackQuery) -> bool:
    """Check admin access for callback handlers."""
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для администраторов", show_alert=True)
        return False
    return True


def _parse_tg_id(raw: str | None) -> int | None:
    """Parse Telegram ID from command args/callback payload."""
    if not raw:
        return None

    value = raw.strip().split(maxsplit=1)[0]
    if value.startswith("@"):
        return None

    try:
        tg_id = int(value)
    except ValueError:
        return None

    return tg_id if tg_id > 0 else None


def _format_user_line(user: User) -> str:
    """Format one user for admin list."""
    status = "⛔ забанен" if user.is_banned else "✅ активен"
    safe_name = html.escape(user.full_name)
    return (
        f"• <code>{user.tg_id}</code> — <b>{safe_name}</b>\n"
        f"  {role_label(user.role)} · {status}"
    )


def _format_user_card(user: User) -> str:
    """Format detailed user information for admins."""
    return (
        "👤 <b>Пользователь</b>\n\n"
        f"🆔 ID: <code>{user.tg_id}</code>\n"
        f"🙍 Имя: <b>{html.escape(user.full_name)}</b>\n"
        f"🎓 Группа: <b>{html.escape(user.study_group or 'Не указана')}</b>\n"
        f"🎭 Роль: <b>{role_label(user.role)}</b>\n"
        f"🎟 Инвайт: <b>{html.escape(user.invite_role or 'нет')}</b>\n"
        f"🔐 По коду: <b>{'да' if user.registered_by_code else 'нет'}</b>\n"
        f"📌 Статус: <b>{'⛔ Заблокирован' if user.is_banned else '✅ Активен'}</b>\n"
        f"🕒 Создан: <code>{user.created_at.strftime('%d.%m.%Y %H:%M')}</code>"
    )


def _build_user_actions_keyboard(user: User) -> types.InlineKeyboardMarkup:
    """Build ban/unban actions for a user card."""
    builder = InlineKeyboardBuilder()
    if user.is_banned:
        builder.button(text="✅ Разбанить", callback_data=f"admin_unban_{user.tg_id}")
    else:
        builder.button(text="⛔ Забанить", callback_data=f"admin_ban_{user.tg_id}")
    builder.button(text="🔄 Обновить", callback_data=f"admin_user_{user.tg_id}")
    builder.adjust(1)
    return builder.as_markup()


def _build_users_page_keyboard(users: list[User], page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    """Build inline keyboard for users list with actions and pagination."""
    builder = InlineKeyboardBuilder()

    for user in users:
        action = "✅ Разбанить" if user.is_banned else "⛔ Забанить"
        action_prefix = "admin_unban" if user.is_banned else "admin_ban"
        builder.button(
            text=f"{action}: {user.full_name[:24]}",
            callback_data=f"{action_prefix}_{user.tg_id}",
        )
        builder.button(
            text="👁",
            callback_data=f"admin_user_{user.tg_id}",
        )

    if total_pages > 1:
        nav_buttons: list[types.InlineKeyboardButton] = []
        if page > 0:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"admin_users_page_{page - 1}",
                )
            )
        nav_buttons.append(
            types.InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="admin_users_noop",
            )
        )
        if page < total_pages - 1:
            nav_buttons.append(
                types.InlineKeyboardButton(
                    text="Вперёд ➡️",
                    callback_data=f"admin_users_page_{page + 1}",
                )
            )

        builder.adjust(2)
        return types.InlineKeyboardMarkup(
            inline_keyboard=[
                *builder.export(),
                nav_buttons,
            ]
        )

    builder.adjust(2)
    return builder.as_markup()


async def _send_users_page(message: types.Message, page: int = 0) -> None:
    """Send paginated user list."""
    async with session_scope() as session:
        users = await get_all_users(session)

    users = sorted(users, key=lambda item: item.created_at, reverse=True)
    total = len(users)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    if not chunk:
        await message.answer("📭 Пользователи не найдены.")
        return

    lines = "\n\n".join(_format_user_line(user) for user in chunk)
    banned_count = sum(1 for user in users if user.is_banned)
    text = (
        "👥 <b>Пользователи</b>\n\n"
        f"Всего: <b>{total}</b> · Забанено: <b>{banned_count}</b>\n"
        f"Страница: <b>{page + 1}/{total_pages}</b>\n\n"
        f"{lines}"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=_build_users_page_keyboard(chunk, page, total_pages),
    )


async def _show_user(message: types.Message, tg_id: int) -> None:
    """Send detailed user card."""
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

    if not user:
        await message.answer(f"❌ Пользователь <code>{tg_id}</code> не найден.", parse_mode="HTML")
        return

    await message.answer(
        _format_user_card(user),
        parse_mode="HTML",
        reply_markup=_build_user_actions_keyboard(user),
    )


async def _set_ban_status(
    *,
    actor_id: int,
    target_id: int,
    banned: bool,
) -> tuple[bool, str, User | None]:
    """Ban or unban user and return operation result."""
    if target_id in config.admin_ids and banned:
        return False, "❌ Нельзя заблокировать администратора.", None

    if actor_id == target_id and banned:
        return False, "❌ Нельзя заблокировать самого себя.", None

    async with session_scope() as session:
        user = await get_user(tg_id=target_id, session=session)
        if not user:
            return False, f"❌ Пользователь <code>{target_id}</code> не найден.", None

        if user.is_banned == banned:
            status = "уже заблокирован" if banned else "уже активен"
            return False, f"ℹ️ Пользователь <code>{target_id}</code> {status}.", user

        user = await (ban_user(target_id, session) if banned else unban_user(target_id, session))

    action = "banned" if banned else "unbanned"
    logger.info("Admin %s %s user %s", actor_id, action, target_id)

    label = "заблокирован" if banned else "разблокирован"
    return True, f"✅ Пользователь <code>{target_id}</code> {label}.", user


@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    """Show admin help."""
    if not await _ensure_admin(message):
        return

    await message.answer(
        "🛡 <b>Админ-панель</b>\n\n"
        "<b>Команды:</b>\n"
        "/users — список пользователей с кнопками бан/разбан\n"
        "/user <telegram_id> — карточка пользователя\n"
        "/ban <telegram_id> — заблокировать пользователя\n"
        "/unban <telegram_id> — разблокировать пользователя\n\n"
        "Заблокированные пользователи не могут пользоваться функциями бота, кроме /start и /cancel.",
        parse_mode="HTML",
    )


@router.message(Command("users"))
async def cmd_users(message: types.Message) -> None:
    """Show paginated users list."""
    if not await _ensure_admin(message):
        return

    await _send_users_page(message)


@router.message(Command("user"))
async def cmd_user(message: types.Message, command: CommandObject) -> None:
    """Show one user by Telegram ID."""
    if not await _ensure_admin(message):
        return

    tg_id = _parse_tg_id(command.args)
    if tg_id is None:
        await message.answer(
            "❌ Укажите Telegram ID пользователя.\n"
            "Пример: <code>/user 123456789</code>",
            parse_mode="HTML",
        )
        return

    await _show_user(message, tg_id)


@router.message(Command("ban"))
async def cmd_ban(message: types.Message, command: CommandObject) -> None:
    """Ban a user by Telegram ID."""
    if not await _ensure_admin(message):
        return

    tg_id = _parse_tg_id(command.args)
    if tg_id is None:
        await message.answer(
            "❌ Укажите Telegram ID пользователя.\n"
            "Пример: <code>/ban 123456789</code>",
            parse_mode="HTML",
        )
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=message.from_user.id,
        target_id=tg_id,
        banned=True,
    )
    await message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=_build_user_actions_keyboard(user) if user else None,
    )


@router.message(Command("unban"))
async def cmd_unban(message: types.Message, command: CommandObject) -> None:
    """Unban a user by Telegram ID."""
    if not await _ensure_admin(message):
        return

    tg_id = _parse_tg_id(command.args)
    if tg_id is None:
        await message.answer(
            "❌ Укажите Telegram ID пользователя.\n"
            "Пример: <code>/unban 123456789</code>",
            parse_mode="HTML",
        )
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=message.from_user.id,
        target_id=tg_id,
        banned=False,
    )
    await message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=_build_user_actions_keyboard(user) if user else None,
    )


@router.callback_query(F.data.startswith("admin_users_page_"))
async def admin_users_page(callback: types.CallbackQuery) -> None:
    """Open users page from inline pagination."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    page_raw = callback.data.removeprefix("admin_users_page_")
    page = int(page_raw) if page_raw.isdigit() else 0
    await _send_users_page(callback.message, page)
    await callback.answer()


@router.callback_query(F.data == "admin_users_noop")
async def admin_users_noop(callback: types.CallbackQuery) -> None:
    """No-op pagination callback."""
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_"))
async def admin_user_callback(callback: types.CallbackQuery) -> None:
    """Show user details from inline action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_user_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    await _show_user(callback.message, tg_id)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_callback(callback: types.CallbackQuery) -> None:
    """Ban user from inline action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_ban_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=callback.from_user.id,
        target_id=tg_id,
        banned=True,
    )
    await callback.message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=_build_user_actions_keyboard(user) if user else None,
    )
    await callback.answer("Готово" if ok else "Не изменено")


@router.callback_query(F.data.startswith("admin_unban_"))
async def admin_unban_callback(callback: types.CallbackQuery) -> None:
    """Unban user from inline action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_unban_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=callback.from_user.id,
        target_id=tg_id,
        banned=False,
    )
    await callback.message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=_build_user_actions_keyboard(user) if user else None,
    )
    await callback.answer("Готово" if ok else "Не изменено")


# Local import at bottom avoids exposing get_all_users in handler imports above before module init.
from src.bot.services.user_service import get_all_users  # noqa: E402
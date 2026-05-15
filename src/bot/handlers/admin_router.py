"""Admin router for user access management (ban/unban, role changes, search)."""

from __future__ import annotations

import html

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.models import User, UserRole
from src.bot.services.user_service import ban_user, get_user, get_users, unban_user, update_user_role
from src.bot.ui import role_label
from src.bot.utils.logging import logger
from src.config import config
from src.db.engine import session_scope

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

def _parse_role(raw: str | None) -> UserRole | None:
    """Parse role value from text input."""
    if not raw:
        return None

    normalized = raw.strip().lower()
    if not normalized:
        return None

    try:
        return UserRole(normalized)
    except ValueError:
        return None

def _parse_users_filters(raw: str | None) -> tuple[str | None, int | None, UserRole | None]:
    """
    Parse admin users search filters.

    Supported formats:
        /users ivan
        /users id:123456789
        /users tg_id=123456789 role:student
        /users name:Иван роль:student
    """
    if not raw:
        return None, None, None

    query_parts: list[str] = []
    tg_id: int | None = None
    role: UserRole | None = None

    for token in raw.split():
        lowered = token.lower()
        if ":" in token:
            key, value = token.split(":", maxsplit=1)
        elif "=" in token:
            key, value = token.split("=", maxsplit=1)
        else:
            query_parts.append(token)
            continue

        key = key.strip().lower()
        value = value.strip()

        if key in {"id", "tg_id", "telegram_id"}:
            parsed_tg_id = _parse_tg_id(value)
            if parsed_tg_id is not None:
                tg_id = parsed_tg_id
            continue

        if key == "role":
            parsed_role = _parse_role(value)
            if parsed_role is not None:
                role = parsed_role
            continue

        if key in {"name", "query", "search"}:
            if value:
                query_parts.append(value)
            continue

        if lowered:
            query_parts.append(token)

    query = " ".join(query_parts).strip() or None
    if tg_id is None and query and query.isdigit():
        tg_id = int(query)
        query = None

    return query, tg_id, role

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
    """Build actions for a user card."""
    builder = InlineKeyboardBuilder()

    if user.is_banned:
        builder.button(text="✅ Разбанить", callback_data=f"admin_unban_{user.tg_id}")
    else:
        builder.button(text="⛔ Забанить", callback_data=f"admin_ban_{user.tg_id}")

    builder.button(text="✏️ Изменить роль", callback_data=f"admin_role_menu_{user.tg_id}")
    builder.button(text="🔄 Обновить", callback_data=f"admin_user_{user.tg_id}")
    builder.adjust(2)
    return builder.as_markup()

def _build_ban_confirm_keyboard(tg_id: int, banned: bool) -> types.InlineKeyboardMarkup:
    """Build confirmation keyboard for ban/unban actions."""
    builder = InlineKeyboardBuilder()
    confirm_callback = f"admin_ban_confirm_{tg_id}" if banned else f"admin_unban_confirm_{tg_id}"
    builder.button(text="✅ Подтвердить", callback_data=confirm_callback)
    builder.button(text="❌ Отмена", callback_data=f"admin_user_{tg_id}")
    builder.adjust(2)
    return builder.as_markup()

def _build_role_keyboard(user: User) -> types.InlineKeyboardMarkup:
    """Build role selection keyboard for a specific user."""
    builder = InlineKeyboardBuilder()
    for role in UserRole:
        marker = " • текущая" if role == user.role else ""
        builder.button(
            text=f"{role_label(role)}{marker}",
            callback_data=f"admin_role_set_{user.tg_id}_{role.value}",
        )
    builder.button(text="⬅️ Назад", callback_data=f"admin_user_{user.tg_id}")
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

async def _get_users_for_admin(
    *,
    query: str | None = None,
    tg_id: int | None = None,
    role: UserRole | None = None,
) -> list[User]:
    """Get users for admin view."""
    async with session_scope() as session:
        return await get_users(session, query=query, tg_id=tg_id, role=role)

def _build_users_text(
    users: list[User],
    *,
    query: str | None = None,
    tg_id: int | None = None,
    role: UserRole | None = None,
    page: int | None = None,
    total_pages: int | None = None,
) -> str:
    """Build users list text."""
    total = len(users)
    banned_count = sum(1 for user in users if user.is_banned)

    header = "👥 <b>Пользователи</b>\n\n"
    filters: list[str] = []

    if query:
        filters.append(f'поиск: <code>{html.escape(query)}</code>')
    if tg_id is not None:
        filters.append(f'ID: <code>{tg_id}</code>')
    if role is not None:
        filters.append(f'роль: <b>{html.escape(role_label(role))}</b>')

    if filters:
        header += f"Фильтры: {' · '.join(filters)}\n\n"

    header += f"Всего: <b>{total}</b> · Забанено: <b>{banned_count}</b>"

    if page is not None and total_pages is not None:
        header += f"\nСтраница: <b>{page + 1}/{total_pages}</b>"

    if not users:
        return header + "\n\n📭 Пользователи не найдены."

    lines = "\n\n".join(_format_user_line(user) for user in users)
    return header + f"\n\n{lines}"

async def _show_users_page(
    target: types.Message | types.CallbackQuery,
    page: int = 0,
) -> None:
    """Show paginated user list for unfiltered view."""
    users = await _get_users_for_admin()

    total = len(users)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    text = _build_users_text(
        chunk,
        page=page,
        total_pages=total_pages,
    )
    markup = _build_users_page_keyboard(chunk, page, total_pages) if chunk else None

    if isinstance(target, types.CallbackQuery):
        if not target.message:
            await target.answer("Сообщение недоступно", show_alert=True)
            return
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return

    await target.answer(text, parse_mode="HTML", reply_markup=markup)

async def _show_users_filtered(
    message: types.Message,
    *,
    query: str | None = None,
    tg_id: int | None = None,
    role: UserRole | None = None,
) -> None:
    """Show filtered users list without pagination."""
    users = await _get_users_for_admin(query=query, tg_id=tg_id, role=role)
    text = _build_users_text(users, query=query, tg_id=tg_id, role=role)
    await message.answer(text, parse_mode="HTML")

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

async def _change_user_role(
    *,
    actor_id: int,
    target_id: int,
    role: UserRole,
) -> tuple[bool, str, User | None]:
    """Change user role and return operation result."""
    async with session_scope() as session:
        user = await get_user(tg_id=target_id, session=session)
        if not user:
            return False, f"❌ Пользователь <code>{target_id}</code> не найден.", None

        if user.role == role:
            return False, f"ℹ️ Пользователь <code>{target_id}</code> уже имеет роль {role_label(role)}.", user

        user = await update_user_role(target_id, role, session)

    logger.info("Admin %s changed role for user %s to %s", actor_id, target_id, role.value)
    return True, f"✅ Роль пользователя <code>{target_id}</code> изменена на <b>{role_label(role)}</b>.", user

@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    """Show admin help."""
    if not await _ensure_admin(message):
        return

    await message.answer(
        "🛡 <b>Админ-панель</b>\n\n"
        "<b>Команды:</b>\n"
        "/users [query|id:123|role:student] — список пользователей и поиск\n"
        "/user <telegram_id> — карточка пользователя\n"
        "/ban <telegram_id> — заблокировать пользователя\n"
        "/unban <telegram_id> — разблокировать пользователя\n\n"
        "Подсказки для поиска:\n"
        "• <code>/users Иван</code>\n"
        "• <code>/users id:123456789</code>\n"
        "• <code>/users role:student</code>\n"
        "• <code>/users name:Иван role:expert</code>",
        parse_mode="HTML",
    )

@router.message(Command("users"))
async def cmd_users(message: types.Message, command: CommandObject) -> None:
    """Show users list with optional filters."""
    if not await _ensure_admin(message):
        return

    query, tg_id, role = _parse_users_filters(command.args)

    if query is None and tg_id is None and role is None:
        await _show_users_page(message)
        return

    await _show_users_filtered(message, query=query, tg_id=tg_id, role=role)

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

    await message.answer(
        f"Подтвердите блокировку пользователя <code>{tg_id}</code>.",
        parse_mode="HTML",
        reply_markup=_build_ban_confirm_keyboard(tg_id, banned=True),
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

    await message.answer(
        f"Подтвердите разблокировку пользователя <code>{tg_id}</code>.",
        parse_mode="HTML",
        reply_markup=_build_ban_confirm_keyboard(tg_id, banned=False),
    )

@router.callback_query(F.data.startswith("admin_users_page_"))
async def admin_users_page(callback: types.CallbackQuery) -> None:
    """Open users page from inline pagination."""
    if not await _ensure_admin_callback(callback):
        return

    page_raw = callback.data.removeprefix("admin_users_page_")
    page = int(page_raw) if page_raw.isdigit() else 0
    await _show_users_page(callback, page)
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
    """Ask for ban confirmation from inline action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_ban_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    await callback.message.answer(
        f"Подтвердите блокировку пользователя <code>{tg_id}</code>.",
        parse_mode="HTML",
        reply_markup=_build_ban_confirm_keyboard(tg_id, banned=True),
    )
    await callback.answer("Подтвердите действие")

@router.callback_query(F.data.startswith("admin_unban_"))
async def admin_unban_callback(callback: types.CallbackQuery) -> None:
    """Ask for unban confirmation from inline action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_unban_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    await callback.message.answer(
        f"Подтвердите разблокировку пользователя <code>{tg_id}</code>.",
        parse_mode="HTML",
        reply_markup=_build_ban_confirm_keyboard(tg_id, banned=False),
    )
    await callback.answer("Подтвердите действие")

@router.callback_query(F.data.startswith("admin_ban_confirm_"))
async def admin_ban_confirm_callback(callback: types.CallbackQuery) -> None:
    """Confirm ban action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_ban_confirm_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=callback.from_user.id,
        target_id=tg_id,
        banned=True,
    )
    await callback.message.edit_text(result_text, parse_mode="HTML")
    if user:
        await callback.message.answer(
            _format_user_card(user),
            parse_mode="HTML",
            reply_markup=_build_user_actions_keyboard(user),
        )
    await callback.answer("Готово" if ok else "Не изменено")

@router.callback_query(F.data.startswith("admin_unban_confirm_"))
async def admin_unban_confirm_callback(callback: types.CallbackQuery) -> None:
    """Confirm unban action."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_unban_confirm_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    ok, result_text, user = await _set_ban_status(
        actor_id=callback.from_user.id,
        target_id=tg_id,
        banned=False,
    )
    await callback.message.edit_text(result_text, parse_mode="HTML")
    if user:
        await callback.message.answer(
            _format_user_card(user),
            parse_mode="HTML",
            reply_markup=_build_user_actions_keyboard(user),
        )
    await callback.answer("Готово" if ok else "Не изменено")

@router.callback_query(F.data.startswith("admin_role_menu_"))
async def admin_role_menu_callback(callback: types.CallbackQuery) -> None:
    """Open role selection menu for a user."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    tg_id = _parse_tg_id(callback.data.removeprefix("admin_role_menu_"))
    if tg_id is None:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

    if not user:
        await callback.answer(f"Пользователь <code>{tg_id}</code> не найден", show_alert=True)
        return

    await callback.message.answer(
        f"Выберите новую роль для <b>{html.escape(user.full_name)}</b> (<code>{user.tg_id}</code>):",
        parse_mode="HTML",
        reply_markup=_build_role_keyboard(user),
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_role_set_"))
async def admin_role_set_callback(callback: types.CallbackQuery) -> None:
    """Apply selected role."""
    if not await _ensure_admin_callback(callback):
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    payload = callback.data.removeprefix("admin_role_set_")
    try:
        tg_id_raw, role_raw = payload.rsplit("_", maxsplit=1)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    tg_id = _parse_tg_id(tg_id_raw)
    role = _parse_role(role_raw)
    if tg_id is None or role is None:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    ok, result_text, user = await _change_user_role(
        actor_id=callback.from_user.id,
        target_id=tg_id,
        role=role,
    )
    await callback.message.edit_text(result_text, parse_mode="HTML")
    if user:
        await callback.message.answer(
            _format_user_card(user),
            parse_mode="HTML",
            reply_markup=_build_user_actions_keyboard(user),
        )
    await callback.answer("Готово" if ok else "Не изменено")
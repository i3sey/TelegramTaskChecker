"""Organizer handler router for session and results management."""

from html import escape
from typing import Any
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.engine import session_scope
from src.db.models import UserRole
from src.bot.services.user_service import get_user, ban_user, unban_user, get_all_users
from src.bot.services.campaign_service import get_campaign_results
from src.bot.utils.logging import logger
from src.bot.keyboards import (
    BTN_CREATE_CAMPAIGN,
    BTN_MY_CAMPAIGNS,
    BTN_MORE,
    BTN_SET_CRITERIA,
    BTN_VIEW_RESULTS,
    BTN_EXPORT,
    BTN_ANALYTICS,
    build_organizer_more_keyboard,
    get_keyboard_for_role,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


router = Router()
router.name = "organizer_router"


class OrganizerCriteriaState(StatesGroup):
    """FSM for collecting organizer evaluation criteria."""

    awaiting_criteria = State()


@router.message(Command("invites"))
async def cmd_invites(message: types.Message) -> None:
    """Explain that campaign invites are generated automatically."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    await message.answer(
        "🔗 <b>Инвайты привязаны к кампании.</b>\n\n"
        "Они создаются автоматически сразу после создания кампании и отправляются вместе с уведомлением.\n"
        "Чтобы получить новые ссылки, создайте кампанию или откройте её из списка кампаний.",
        parse_mode="HTML",
    )


@router.message(Command("set_criteria"))
async def cmd_set_criteria(
    message: types.Message, state: FSMContext
) -> None:
    """
    Handle /set_criteria command to define evaluation criteria.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    criteria_text = (
        "📋 <b>Критерии оценки</b>\n\n"
        "Отправьте каждый критерий с новой строки.\n\n"
        "Пример:\n"
        "Корректность\n"
        "Качество решения\n"
        "Оформление\n\n"
        "Отправьте список критериев:"
    )
    
    await message.answer(criteria_text, parse_mode="HTML")
    await state.set_state(OrganizerCriteriaState.awaiting_criteria)


@router.message(OrganizerCriteriaState.awaiting_criteria)
async def process_criteria(message: types.Message, state: FSMContext) -> None:
    """Process evaluation criteria from organizer."""
    if message.text.lower().strip() == "skip":
        criteria = [
            "Корректность",
            "Качество решения",
            "Оформление",
            "Тестирование",
            "Производительность",
        ]
        source = "стандартный набор"
    else:
        criteria = [c.strip() for c in message.text.split("\n") if c.strip()]
        source = "пользовательский набор"

    criteria_list = "\n".join(f"✓ {c}" for c in criteria)

    await message.answer(
        f"✅ <b>Критерии сохранены</b> ({source})\n\n"
        f"{criteria_list}\n\n"
        "Эксперты увидят эти критерии во время проверки.",
        parse_mode="HTML",
    )
    await state.clear()


def _format_results_text(results: list[dict]) -> str:
    if not results:
        return "📭 <b>Результаты кампаний отсутствуют</b>"

    blocks: list[str] = ["📊 <b>Результаты кампаний</b>"]
    for item in results:
        campaign = item["campaign"]
        status_summary = item["status_summary"]

        comments = item["comments"]
        comments_text = (
            "\n".join(f"• {escape(comment)}" for comment in comments[:5])
            if comments
            else "• нет комментариев"
        )

        status_text = "\n".join(
            [
                f"• Загружено: {status_summary.get('uploaded', 0)}",
                f"• На проверке: {status_summary.get('in_review', 0)}",
                f"• Проверено: {status_summary.get('reviewed', 0)}",
                f"• Отклонено: {status_summary.get('rejected', 0)}",
            ]
        )

        blocks.append(
            f"\n<b>{escape(campaign.title)}</b>\n"
            f"📌 Тип: {campaign.type.value}\n"
            f"📝 Работ: {item['total_submissions']}\n"
            f"✅ Проверено: {item['reviewed_submissions']}\n"
            f"⭐ Средняя оценка: {item['avg_score']:.2f}\n"
            f"💬 Комментарии:\n{comments_text}\n"
            f"📈 Сводка по статусам:\n{status_text}"
        )

    return "\n".join(blocks)

@router.message(Command("view_results"))
async def cmd_view_results(message: types.Message) -> None:
    """
    Handle /view_results command to see all feedback and results.

    Displays compiled feedback and ratings from all reviews.
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

        results = await get_campaign_results(session)

    await message.answer(_format_results_text(results), parse_mode="HTML")


@router.message(Command("export"))
async def cmd_export(message: types.Message) -> None:
    """Export results to Google Sheets when the integration is ready."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    await message.answer(
        "⚠️ Экспорт в Google Sheets временно недоступен.\n"
        "Функция будет добавлена позже."
    )


@router.message(Command("manage_users"))
async def cmd_manage_users(message: types.Message) -> None:
    """
    Handle /manage_users command to manage system users.
    
    Args:
        message: Telegram message object
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    # TODO: Добавить список пользователей, поиск, бан/разбан и при необходимости изменение ролей.
    await message.answer(
        "⚠️ Управление пользователями временно недоступно.\n"
        "Функция будет добавлена позже."
    )


@router.message(Command("analytics"))
async def cmd_analytics(message: types.Message) -> None:
    """
    Handle /analytics command to view system analytics.
    
    Args:
        message: Telegram message object
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    # TODO: Добавить аналитику по кампаниям и пользователям: метрики активности, проверок и результатов.
    await message.answer(
        "⚠️ Аналитика временно недоступна.\n"
        "Функция будет добавлена позже."
    )


@router.message(F.text == BTN_CREATE_CAMPAIGN)
async def btn_create_campaign(message: types.Message, state: FSMContext) -> None:
    from src.bot.handlers.campaign_router import cmd_create_campaign

    await cmd_create_campaign(message, state)


@router.message(F.text == BTN_MY_CAMPAIGNS)
async def btn_my_campaigns(message: types.Message) -> None:
    from src.bot.handlers.campaign_router import cmd_my_campaigns

    await cmd_my_campaigns(message)


@router.message(F.text == BTN_SET_CRITERIA)
async def btn_set_criteria(message: types.Message, state: FSMContext) -> None:
    await cmd_set_criteria(message, state)


@router.message(F.text == BTN_VIEW_RESULTS)
async def btn_view_results(message: types.Message) -> None:
    await cmd_view_results(message)


@router.message(F.text == BTN_EXPORT)
async def btn_export(message: types.Message) -> None:
    await cmd_export(message)


@router.message(F.text == BTN_ANALYTICS)
async def btn_analytics(message: types.Message) -> None:
    await cmd_analytics(message)


@router.message(F.text == BTN_MORE)
async def btn_more(message: types.Message) -> None:
    await message.answer(
        "⚙️ <b>Дополнительные действия</b>",
        parse_mode="HTML",
        reply_markup=build_organizer_more_keyboard(),
    )


@router.callback_query(F.data == "org_menu_set_criteria")
async def org_menu_set_criteria(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_set_criteria(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "org_menu_view_results")
async def org_menu_view_results(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_view_results(callback.message)
    await callback.answer()


@router.callback_query(F.data == "org_menu_export")
async def org_menu_export(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_export(callback.message)
    await callback.answer()


@router.callback_query(F.data == "org_menu_analytics")
async def org_menu_analytics(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_analytics(callback.message)
    await callback.answer()


@router.callback_query(F.data == "org_menu_banned_users")
async def org_menu_banned_users(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_banned_users(callback.message)
    await callback.answer()


# Ban/Unban management handlers
@router.callback_query(F.data.startswith("org_ban_student_"))
async def handle_ban_confirmation(callback: types.CallbackQuery, bot: Bot) -> None:
    """Handle ban confirmation from organizer."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    # Parse callback data: org_ban_student_{student_id}_{submission_id}
    parts = callback.data.removeprefix("org_ban_student_").split("_")
    if len(parts) < 2:
        await callback.answer("❌ Некорректный запрос", show_alert=True)
        return
    
    try:
        student_id = int(parts[0])
        submission_id = int(parts[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    async with session_scope() as session:
        student = await get_user(tg_id=student_id, session=session)
        if not student:
            await callback.answer(f"❌ Студент с ID {student_id} не найден", show_alert=True)
            return
        
        if student.is_banned:
            await callback.answer(f"⚠️ Студент {student.full_name} уже забанен", show_alert=True)
            return
        
        # Ban the student
        await ban_user(student_id, session)
    
    logger.info(f"Organizer {callback.from_user.id} banned student {student_id} (submission {submission_id})")
    
    # Notify organizer
    await callback.answer(f"✅ Студент {student.full_name} забанен", show_alert=True)
    
    # Update the message
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Студент забанен организатором {user.full_name}</b>",
        parse_mode="HTML",
    )
    
    # Try to notify the banned student
    try:
        await bot.send_message(
            chat_id=student_id,
            text="⛔ <b>Вы были заблокированы в системе</b>\n\n"
                 "Причина: нарушение правил платформы.\n\n"
                 "Если это ошибка, свяжитесь с администратором.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Failed to notify banned student {student_id}: {e}")


@router.callback_query(F.data.startswith("org_reject_ban_"))
async def handle_ban_rejection(callback: types.CallbackQuery) -> None:
    """Handle ban request rejection."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    submission_id_str = callback.data.removeprefix("org_reject_ban_")
    
    try:
        submission_id = int(submission_id_str)
    except ValueError:
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    logger.info(f"Organizer {callback.from_user.id} rejected ban request for submission {submission_id}")
    
    # Notify organizer
    await callback.answer("✅ Жалоба отклонена", show_alert=True)
    
    # Update the message
    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>Жалоба отклонена организатором {user.full_name}</b>",
        parse_mode="HTML",
    )


@router.message(Command("banned_users"))
async def cmd_banned_users(message: types.Message) -> None:
    """Show list of banned users and allow unban."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return
        
        all_users = await get_all_users(session)
        banned_users = [u for u in all_users if u.is_banned]
    
    if not banned_users:
        await message.answer("✅ Нет забанённых пользователей.")
        return
    
    text = "⛔ <b>Забанённые пользователи</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    
    for banned_user in banned_users:
        text += f"• <code>{banned_user.tg_id}</code> — <b>{banned_user.full_name}</b>\n"
        builder.button(
            text=f"✅ Разбанить {banned_user.full_name[:20]}",
            callback_data=f"org_unban_{banned_user.tg_id}",
        )
    
    builder.adjust(1)
    
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("org_unban_"))
async def handle_unban(callback: types.CallbackQuery) -> None:
    """Handle unban action."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    student_id_str = callback.data.removeprefix("org_unban_")
    
    try:
        student_id = int(student_id_str)
    except ValueError:
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    async with session_scope() as session:
        student = await get_user(tg_id=student_id, session=session)
        if not student:
            await callback.answer(f"❌ Студент с ID {student_id} не найден", show_alert=True)
            return
        
        if not student.is_banned:
            await callback.answer(f"⚠️ Студент {student.full_name} не забанен", show_alert=True)
            return
        
        # Unban the student
        await unban_user(student_id, session)
    
    logger.info(f"Organizer {callback.from_user.id} unbanned student {student_id}")
    
    # Notify organizer
    await callback.answer(f"✅ Студент {student.full_name} разбанен", show_alert=True)
    
    # Update the message
    text = callback.message.text or ""
    text = text.replace(f"<code>{student_id}</code> — <b>{student.full_name}</b>", "")
    
    # Show updated list or message about no banned users
    if len(text.strip()) < 50:
        await callback.message.edit_text("✅ Нет забанённых пользователей.")
    else:
        await callback.message.edit_text(text, parse_mode="HTML")
    
    # Try to notify the unbanned student
    keyboard = get_keyboard_for_role(student.role) if student else None
    
    try:
        await callback.bot.send_message(
            chat_id=student_id,
            text="✅ <b>Вы были разблокированы в системе</b>\n\n"
                 "Теперь вы можете снова использовать бота.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"Failed to notify unbanned student {student_id}: {e}")

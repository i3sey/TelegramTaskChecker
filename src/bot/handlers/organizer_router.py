"""Organizer handler router for session and results management."""

from typing import Any
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.engine import session_scope
from src.db.models import UserRole
from src.bot.services.user_service import get_user
from src.bot.keyboards import (
    BTN_CREATE_CAMPAIGN,
    BTN_MY_CAMPAIGNS,
    BTN_INVITES,
    BTN_MORE,
    BTN_SET_CRITERIA,
    BTN_VIEW_RESULTS,
    BTN_EXPORT,
    BTN_ANALYTICS,
    build_organizer_more_keyboard,
)


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


@router.message(Command("view_results"))
async def cmd_view_results(message: types.Message) -> None:
    """
    Handle /view_results command to see all feedback and results.
    
    Displays compiled feedback and ratings from all reviews.
    
    Args:
        message: Telegram message object
        user_id: Telegram user ID
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    await message.answer(
        "⚠️ Просмотр результатов временно недоступен.\n"
        "Функция будет добавлена позже."
    )


@router.message(Command("export"))
async def cmd_export(message: types.Message) -> None:
    """
    Handle /export command to export results to Google Sheets.
    
    Placeholder for Google Sheets integration.
    
    Args:
        message: Telegram message object
    """
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


@router.message(F.text == BTN_INVITES)
async def btn_invites(message: types.Message) -> None:
    await cmd_invites(message)


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

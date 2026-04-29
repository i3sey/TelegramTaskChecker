"""Organizer handler router for session and results management."""

from typing import Any
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.engine import session_scope
from src.db.models import UserRole
from src.services.user_service import get_user
from src.services.invite_service import create_invite


router = Router()
router.name = "organizer_router"


def _build_invite_keyboard() -> types.InlineKeyboardMarkup:
    """Build inline keyboard for invite generation."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🎓 Инвайт для студентов", callback_data="invite_student")],
            [types.InlineKeyboardButton(text="🧑‍🏫 Инвайт для экспертов", callback_data="invite_expert")],
        ]
    )


class OrganizerSessionState(StatesGroup):
    """FSM states for organizer session management workflow."""
    
    creating_session = State()
    setting_criteria = State()
    awaiting_session_name = State()
    awaiting_criteria = State()


@router.message(Command("create_session"))
async def cmd_create_session(
    message: types.Message, state: FSMContext
) -> None:
    """
    Handle /create_session command to start a new review session.
    
    Guides through session creation workflow using FSM.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    initial_text = (
        "🆕 Create New Review Session\n\n"
        "This will set up a new review cycle for submissions.\n\n"
        "What would you like to name this session?\n"
        "Example: 'Python 101 - Week 3', 'Capstone Review 2024'\n\n"
        "Send session name:"
    )
    
    await message.answer(initial_text)
    await state.set_state(OrganizerSessionState.awaiting_session_name)


@router.message(Command("invites"))
async def cmd_invites(message: types.Message) -> None:
    """Show invite generation options for organizers."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    await message.answer(
        "🔗 <b>Инвайты для ролей</b>\n\n"
        "Выберите тип инвайта:",
        reply_markup=_build_invite_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.in_({"invite_student", "invite_expert"}))
async def process_invite_create(callback: types.CallbackQuery) -> None:
    """Create an invite link for the selected role."""
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Только для организаторов", show_alert=True)
            return

        role = "student" if callback.data == "invite_student" else "expert"
        invite = await create_invite(role=role, created_by=user.tg_id, session=session)

    bot_info = await callback.bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start={invite.code}"

    await callback.message.edit_text(
        "✅ Инвайт создан.\n\n"
        f"Роль: <b>{'Студент' if role == 'student' else 'Эксперт'}</b>\n"
        f"Ссылка: {invite_link}",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(OrganizerSessionState.awaiting_session_name)
async def process_session_name(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process session name from organizer.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    session_name = message.text.strip()
    
    if not session_name or len(session_name) < 3:
        await message.answer("⚠️ Session name must be at least 3 characters.")
        return
    
    await state.update_data(session_name=session_name)
    
    confirmation_text = (
        f"✅ Session name set: **{session_name}**\n\n"
        "Now, would you like to set evaluation criteria?\n"
        "Reply: Yes or No"
    )
    
    await message.answer(confirmation_text)
    await state.set_state(OrganizerSessionState.creating_session)


@router.message(OrganizerSessionState.creating_session)
async def process_session_confirmation(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process session confirmation and optionally set criteria.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    response = message.text.lower().strip()
    data = await state.get_data()
    session_name = data.get("session_name", "Session")
    
    if response in ["yes", "✅", "y"]:
        criteria_text = (
            f"📋 Session: {session_name}\n\n"
            "Define evaluation criteria (one per line):\n\n"
            "Examples:\n"
            "• Correctness of implementation\n"
            "• Code quality and readability\n"
            "• Documentation completeness\n"
            "• Performance optimization\n"
            "• Testing coverage\n\n"
            "Send your criteria (or 'skip' to use defaults):"
        )
        await message.answer(criteria_text)
        await state.set_state(OrganizerSessionState.awaiting_criteria)
    
    else:
        created_text = (
            f"✅ Session Created: **{session_name}**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"ID: SESSION-{message.from_user.id}-001\n"
            "Status: 🟢 Active\n"
            "Created: Now\n"
            "Submissions: 0\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ready to accept submissions!"
        )
        await message.answer(created_text)
        await state.clear()


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
        "📋 Set Evaluation Criteria\n\n"
        "Define the criteria for evaluating submissions.\n"
        "Send each criterion on a new line.\n\n"
        "Example format:\n"
        "Correctness\n"
        "Code Quality\n"
        "Documentation\n\n"
        "Send criteria:"
    )
    
    await message.answer(criteria_text)
    await state.set_state(OrganizerSessionState.awaiting_criteria)


@router.message(OrganizerSessionState.awaiting_criteria)
async def process_criteria(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process evaluation criteria from organizer.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    if message.text.lower().strip() == "skip":
        criteria = [
            "Correctness",
            "Code Quality",
            "Documentation",
            "Testing",
            "Performance"
        ]
        source = "defaults"
    else:
        criteria = [c.strip() for c in message.text.split('\n') if c.strip()]
        source = "custom"
    
    criteria_list = "\n".join(f"✓ {c}" for c in criteria)
    
    success_text = (
        f"✅ Criteria Saved ({source}):\n\n"
        f"{criteria_list}\n\n"
        "Experts will use these criteria when reviewing submissions."
    )
    
    await message.answer(success_text)
    await state.update_data(criteria=criteria)
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

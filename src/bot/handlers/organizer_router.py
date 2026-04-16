"""Organizer handler router for session and results management."""

from typing import Any
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


router = Router()
router.name = "organizer_router"


class OrganizerSessionState(StatesGroup):
    """FSM states for organizer session management workflow."""
    
    creating_session = State()
    setting_criteria = State()
    awaiting_session_name = State()
    awaiting_criteria = State()


@router.message(Command("start"), F.text == "/start")
async def cmd_start(message: types.Message, user_role: str = "organizer") -> None:
    """
    Handle /start command for organizer users.
    
    Displays welcome message and administrative capabilities.
    
    Args:
        message: Telegram message object
        user_role: User's role in the system
    """
    welcome_text = (
        "👋 Welcome Organizer!\n\n"
        "You have administrative access to the review system.\n\n"
        "Available commands:\n"
        "🆕 /create_session - Start a new review session\n"
        "📋 /set_criteria - Define evaluation criteria\n"
        "📊 /view_results - See all feedback and results\n"
        "💾 /export - Export results to Google Sheets\n"
        "👥 /manage_users - Manage system users\n"
        "📈 /analytics - View system analytics\n\n"
        "Let's manage the review process! 🎯"
    )
    
    await message.answer(welcome_text)


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
    initial_text = (
        "🆕 Create New Review Session\n\n"
        "This will set up a new review cycle for submissions.\n\n"
        "What would you like to name this session?\n"
        "Example: 'Python 101 - Week 3', 'Capstone Review 2024'\n\n"
        "Send session name:"
    )
    
    await message.answer(initial_text)
    await state.set_state(OrganizerSessionState.awaiting_session_name)


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
async def cmd_view_results(message: types.Message, user_id: int) -> None:
    """
    Handle /view_results command to see all feedback and results.
    
    Displays compiled feedback and ratings from all reviews.
    
    Args:
        message: Telegram message object
        user_id: Telegram user ID
    """
    results_text = (
        "📊 Review Results Summary\n\n"
        "Session: Python 101 - Week 3\n"
        "Status: ✅ In Progress\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📈 Statistics:\n"
        "• Total Submissions: 23\n"
        "• Reviewed: 15\n"
        "• Pending: 8\n"
        "• Average Rating: 3.6/5\n\n"
        "👥 Top Performers:\n"
        "1. Alice M. - Average: 4.8/5 (3 reviews)\n"
        "2. Bob T. - Average: 4.2/5 (2 reviews)\n"
        "3. Carol S. - Average: 4.0/5 (2 reviews)\n\n"
        "Use /export to download detailed results."
    )
    
    await message.answer(results_text)


@router.message(Command("export"))
async def cmd_export(message: types.Message) -> None:
    """
    Handle /export command to export results to Google Sheets.
    
    Placeholder for Google Sheets integration.
    
    Args:
        message: Telegram message object
    """
    export_text = (
        "📊 Export Results\n\n"
        "This will create a Google Sheets document with all review results.\n\n"
        "🔗 Processing export...\n"
        "⏳ Authenticating with Google Sheets API...\n"
        "💾 Creating spreadsheet...\n\n"
        "[Simulated - Google Sheets integration would be implemented here]\n\n"
        "✅ Export complete!\n"
        "📋 Spreadsheet: python-101-week3-results\n"
        "🔗 Link: https://sheets.google.com/d/1234567890/edit"
    )
    
    await message.answer(export_text)


@router.message(Command("manage_users"))
async def cmd_manage_users(message: types.Message) -> None:
    """
    Handle /manage_users command to manage system users.
    
    Args:
        message: Telegram message object
    """
    users_text = (
        "👥 User Management\n\n"
        "Current Users:\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📚 Students: 45\n"
        "👨‍🏫 Experts: 8\n"
        "🏢 Organizers: 2\n\n"
        "Recent Activity:\n"
        "✅ Added: Alice M. (Student) - 2 hours ago\n"
        "✅ Added: Dr. Smith (Expert) - 1 day ago\n"
        "❌ Removed: Test User - 3 days ago\n\n"
        "Commands:\n"
        "/add_user <telegram_id> <role>\n"
        "/remove_user <telegram_id>\n"
        "/list_users"
    )
    
    await message.answer(users_text)


@router.message(Command("analytics"))
async def cmd_analytics(message: types.Message) -> None:
    """
    Handle /analytics command to view system analytics.
    
    Args:
        message: Telegram message object
    """
    analytics_text = (
        "📈 System Analytics\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Session: Python 101 - Week 3\n"
        "Duration: 5 days\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 Submission Analytics:\n"
        "• Total: 23\n"
        "• Avg. Score: 3.6/5\n"
        "• Distribution: 🟢8 🟡10 🔴5\n\n"
        "⏱️ Time Analytics:\n"
        "• Avg. Review Time: 28 minutes\n"
        "• Avg. Wait Time: 1.5 hours\n"
        "• Peak Hours: 2-4 PM\n\n"
        "👨‍🏫 Expert Performance:\n"
        "• Most Active: Dr. Johnson (12 reviews)\n"
        "• Highest Rated: Prof. Lee (4.8/5)\n"
        "• Fastest: Assistant Smith (18 min avg)"
    )
    
    await message.answer(analytics_text)

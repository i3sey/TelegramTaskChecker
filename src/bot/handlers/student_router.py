"""Student handler router for submission-related commands."""

from typing import Any
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


router = Router()
router.name = "student_router"


class StudentSubmissionState(StatesGroup):
    """FSM states for student submission workflow."""
    
    waiting_for_content = State()
    waiting_for_file = State()
    waiting_for_confirmation = State()


@router.message(Command("start"), F.text == "/start")
async def cmd_start(message: types.Message, user_role: str = "student") -> None:
    """
    Handle /start command to welcome the student.
    
    Displays welcome message and available commands.
    
    Args:
        message: Telegram message object
        user_role: User's role in the system
    """
    welcome_text = (
        "👋 Welcome to the Expert Review Queue System!\n\n"
        "I'm here to help you submit your work for expert review.\n\n"
        "Available commands:\n"
        "📝 /submit - Submit your work for review\n"
        "📊 /status - Check your submission status\n"
        "❓ /help - Get help\n\n"
        "Let's get started! 🚀"
    )
    
    await message.answer(welcome_text)


@router.message(Command("submit"))
async def cmd_submit(message: types.Message, state: FSMContext) -> None:
    """
    Handle /submit command to initiate file/document submission.
    
    Guides student through submission process using FSM.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    submission_text = (
        "📝 Let's submit your work!\n\n"
        "Please provide your submission content. You can:\n"
        "• Paste text directly\n"
        "• Upload a file (PDF, DOC, etc.)\n"
        "• Provide a link to Google Docs\n\n"
        "Send your content now:"
    )
    
    await message.answer(submission_text)
    await state.set_state(StudentSubmissionState.waiting_for_content)


@router.message(StudentSubmissionState.waiting_for_content)
async def process_submission_content(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process submitted content (text, file, or link).
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    submission_data = {
        "type": "text",
        "content": message.text,
        "timestamp": message.date,
    }
    
    if message.document:
        submission_data["type"] = "file"
        submission_data["file_id"] = message.document.file_id
        submission_data["file_name"] = message.document.file_name
    
    await state.update_data(submission=submission_data)
    
    confirmation_text = (
        "✅ Submission received!\n\n"
        "📋 Details:\n"
        f"• Type: {submission_data['type']}\n"
        "• Content: Processing...\n\n"
        "Confirm to submit for review? Reply with:\n"
        "✅ Yes\n"
        "❌ No"
    )
    
    await message.answer(confirmation_text)
    await state.set_state(StudentSubmissionState.waiting_for_confirmation)


@router.message(StudentSubmissionState.waiting_for_confirmation)
async def process_confirmation(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process confirmation to submit or cancel submission.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    response = message.text.lower().strip()
    
    if response in ["yes", "✅", "confirm"]:
        data = await state.get_data()
        submission = data.get("submission", {})
        
        position = 5
        
        success_text = (
            "🎉 Submission successful!\n\n"
            "📊 Queue Information:\n"
            f"• Your position: #{position}\n"
            f"• Estimated wait: ~2-3 hours\n"
            f"• Submission ID: SUB-{message.from_user.id}-001\n\n"
            "Use /status to check your position."
        )
        
        await message.answer(success_text)
        await state.clear()
    
    elif response in ["no", "❌", "cancel"]:
        await message.answer("❌ Submission cancelled. Feel free to /submit again!")
        await state.clear()
    
    else:
        await message.answer("⚠️ Please reply with Yes or No.")


@router.message(Command("status"))
async def cmd_status(message: types.Message, user_id: int) -> None:
    """
    Handle /status command to check submission status in queue.
    
    Displays current queue position and estimated wait time.
    
    Args:
        message: Telegram message object
        user_id: Telegram user ID
    """
    status_text = (
        "📊 Your Submission Status\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ID: SUB-123456-001\n"
        "Status: ⏳ In Queue\n"
        "Position: #3\n"
        "Submitted: 2 hours ago\n"
        "Estimated wait: ~1 hour\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔔 You'll be notified when an expert starts reviewing."
    )
    
    await message.answer(status_text)


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """
    Handle /help command to provide assistance.
    
    Args:
        message: Telegram message object
    """
    help_text = (
        "📚 Help & Information\n\n"
        "**Submitting Your Work:**\n"
        "1. Use /submit to start\n"
        "2. Send your content (text, file, or link)\n"
        "3. Confirm the submission\n"
        "4. Track progress with /status\n\n"
        "**What to Submit:**\n"
        "• Written assignments\n"
        "• Project code/files\n"
        "• Research papers\n"
        "• Any document format\n\n"
        "**Need More Help?**\n"
        "Contact: support@reviewqueue.local"
    )
    
    await message.answer(help_text)

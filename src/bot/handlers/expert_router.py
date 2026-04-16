"""Expert handler router for review and feedback commands."""

from typing import Any
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


router = Router()
router.name = "expert_router"


class ExpertReviewState(StatesGroup):
    """FSM states for expert review workflow."""
    
    viewing_queue = State()
    reviewing_submission = State()
    waiting_for_feedback = State()
    waiting_for_rating = State()
    waiting_for_voice = State()


@router.message(Command("start"), F.text == "/start")
async def cmd_start(message: types.Message, user_role: str = "expert") -> None:
    """
    Handle /start command for expert users.
    
    Displays welcome message and available expert commands.
    
    Args:
        message: Telegram message object
        user_role: User's role in the system
    """
    welcome_text = (
        "👋 Welcome Expert!\n\n"
        "You have access to the review queue system.\n\n"
        "Available commands:\n"
        "📋 /queue - View submissions to review\n"
        "✅ /take - Claim a submission for review\n"
        "💬 /submit_feedback - Provide feedback on a submission\n"
        "⭐ /rating - Submit a rating\n"
        "📊 /stats - View your review statistics\n\n"
        "Ready to help? Let's get started! 🚀"
    )
    
    await message.answer(welcome_text)


@router.message(Command("queue"))
async def cmd_queue(message: types.Message, state: FSMContext) -> None:
    """
    Handle /queue command to view available submissions for review.
    
    Displays list of pending submissions waiting for expert review.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    queue_text = (
        "📋 Available Submissions in Queue\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ SUB-987654-001 | Python Assignment\n"
        "   👤 Student: Alice M.\n"
        "   ⏱️ Waiting: 1 hour\n"
        "   📄 Type: Code file (Python)\n\n"
        "2️⃣ SUB-876543-002 | Research Paper\n"
        "   👤 Student: Bob T.\n"
        "   ⏱️ Waiting: 2 hours\n"
        "   📄 Type: PDF Document\n\n"
        "3️⃣ SUB-765432-003 | Project Report\n"
        "   👤 Student: Carol S.\n"
        "   ⏱️ Waiting: 30 minutes\n"
        "   📄 Type: Word Document\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Use /take <ID> to claim a submission for review."
    )
    
    await message.answer(queue_text)
    await state.set_state(ExpertReviewState.viewing_queue)


@router.message(Command("take"))
async def cmd_take(message: types.Message, state: FSMContext) -> None:
    """
    Handle /take command to claim a submission for review.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer(
            "Please specify submission ID:\n"
            "/take <SUBMISSION_ID>\n\n"
            "Example: /take SUB-987654-001"
        )
        return
    
    submission_id = args[1]
    
    claim_text = (
        f"✅ You've claimed submission: {submission_id}\n\n"
        "📋 Submission Details:\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Student: Alice M.\n"
        "Type: Python Code\n"
        "Description: Assignment implementation\n"
        "Submitted: 2 hours ago\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 Next steps:\n"
        "1. Review the content carefully\n"
        "2. Use /submit_feedback to provide feedback\n"
        "3. Use /rating to submit your score\n"
        "4. Feedback will be sent to the student"
    )
    
    await message.answer(claim_text)
    await state.update_data(current_submission=submission_id)
    await state.set_state(ExpertReviewState.reviewing_submission)


@router.message(Command("submit_feedback"))
async def cmd_submit_feedback(message: types.Message, state: FSMContext) -> None:
    """
    Handle /submit_feedback command to start feedback submission.
    
    Supports text and voice feedback input.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    feedback_text = (
        "📝 Submit Your Feedback\n\n"
        "You can provide feedback in two ways:\n\n"
        "1️⃣ **Text Feedback**\n"
        "   Just type your comments and I'll save them.\n\n"
        "2️⃣ **Voice Feedback**\n"
        "   Send a voice message and I'll transcribe it.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Feedback will be:\n"
        "• Reviewed for quality\n"
        "• Sent to the student\n"
        "• Stored in the system\n\n"
        "Send your feedback now:"
    )
    
    await message.answer(feedback_text)
    await state.set_state(ExpertReviewState.waiting_for_feedback)


@router.message(ExpertReviewState.waiting_for_feedback)
async def process_feedback(
    message: types.Message, state: FSMContext
) -> None:
    """
    Process text or voice feedback from expert.
    
    Handles transcription of voice messages and storage of feedback.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    feedback_data = {
        "type": "text",
        "content": message.text or "[Voice message]",
    }
    
    if message.voice:
        feedback_data["type"] = "voice"
        feedback_data["file_id"] = message.voice.file_id
        feedback_data["duration"] = message.voice.duration
        
        transcription_text = (
            "🔄 Processing voice message...\n"
            "⏳ Transcribing with Whisper AI...\n\n"
            "[Simulated transcription would appear here]"
        )
        await message.answer(transcription_text)
    
    await state.update_data(feedback=feedback_data)
    
    await message.answer(
        "✅ Feedback recorded!\n\n"
        "Now, please rate this submission using /rating"
    )
    await state.set_state(ExpertReviewState.waiting_for_rating)


@router.message(Command("rating"))
async def cmd_rating(message: types.Message, state: FSMContext) -> None:
    """
    Handle /rating command to submit a rating/score.
    
    Args:
        message: Telegram message object
        state: FSM context for managing conversation state
    """
    args = message.text.split()
    
    if len(args) < 2:
        rating_text = (
            "⭐ Submit Your Rating\n\n"
            "Please rate the submission from 1 to 5:\n"
            "1 - Poor\n"
            "2 - Fair\n"
            "3 - Good\n"
            "4 - Very Good\n"
            "5 - Excellent\n\n"
            "Usage: /rating <score>\n"
            "Example: /rating 4"
        )
        await message.answer(rating_text)
        return
    
    try:
        rating = int(args[1])
        if not (1 <= rating <= 5):
            await message.answer("⚠️ Rating must be between 1 and 5.")
            return
        
        data = await state.get_data()
        
        result_text = (
            "🎉 Review Submitted!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Rating: {'⭐' * rating} ({rating}/5)\n"
            f"Feedback Type: {data.get('feedback', {}).get('type', 'text')}\n"
            "Status: ✅ Completed\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "The student will receive your feedback shortly.\n"
            "Thank you for reviewing! 👏"
        )
        
        await message.answer(result_text)
        await state.clear()
    
    except ValueError:
        await message.answer("⚠️ Please provide a numeric rating (1-5).")


@router.message(Command("stats"))
async def cmd_stats(message: types.Message, user_id: int) -> None:
    """
    Handle /stats command to view expert's review statistics.
    
    Args:
        message: Telegram message object
        user_id: Telegram user ID
    """
    stats_text = (
        "📊 Your Review Statistics\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Total Reviews: 47\n"
        "Average Rating: 3.8/5\n"
        "This Week: 12\n"
        "This Month: 42\n"
        "Average Review Time: 25 min\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏆 Tier: Gold Expert\n"
        "⭐ Rating: 4.6/5 from students\n"
        "👥 Feedback: Excellent reviewer"
    )
    
    await message.answer(stats_text)

"""Expert handler router for review and feedback commands."""
import os
from typing import Any
from aiogram import Bot, Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.config import config
from src.db.engine import session_scope
from src.db.models import UserRole, SubmissionStatus, User, Campaign
from src.services.user_service import get_user
from src.services.submission_service import get_submission, update_submission_status
from src.services.review_service import create_review, count_pending_submissions, get_submission_pending
from src.services.campaign_service import get_campaign
from src.services.queue_service import queue_service, QueueService
from src.services.sheets_service import SheetsService
from src.services.notification_service import NotificationService
from src.utils.logging import logger


def _get_sheets_service() -> SheetsService | None:
    """Get SheetsService instance if configured."""
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID") or config.sheets.spreadsheet_id
    credentials_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or config.sheets.credentials_path
    if spreadsheet_id and credentials_path:
        return SheetsService(spreadsheet_id, credentials_path)
    return None


def _get_notification_service(bot: Bot) -> NotificationService:
    """Get NotificationService instance."""
    return NotificationService(bot)


# Create router
router = Router()
router.name = "expert_router"


class ExpertReviewState(StatesGroup):
    """FSM states for expert review workflow."""
    idle = State()
    reviewing_submission = State()
    waiting_for_score = State()
    waiting_for_comment = State()


def get_score_keyboard(min_score: int, max_score: int) -> InlineKeyboardMarkup:
    """Generate inline keyboard for score selection."""
    buttons = []
    step = max(1, (max_score - min_score) // 5)
    current = min_score

    while current <= max_score:
        row = []
        for _ in range(min(3, max_score - current + 1)):
            row.append(InlineKeyboardButton(
                text=str(current),
                callback_data=f"score_{current}"
            ))
            current += 1
            if current > max_score:
                break
        buttons.append(row)

    buttons.append([InlineKeyboardButton(
        text="Отмена",
        callback_data="cancel_review"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Generate confirmation keyboard for review submission."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="confirm_submit"),
            InlineKeyboardButton(text="Отмена", callback_data="cancel_review"),
        ]
    ])


async def check_expert_role(message: types.Message) -> bool:
    """Check if the user has EXPERT role."""
    tg_id = message.from_user.id
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start.")
            return False
        if user.role != UserRole.EXPERT:
            await message.answer("⛔ Эта команда доступна только для экспертов.")
            return False
        if user.is_banned:
            await message.answer("⛔ Ваш аккаунт заблокирован.")
            return False
    return True


async def send_submission_to_expert(
    message: types.Message,
    submission,
    campaign,
    author: User
) -> None:
    """Send submission file to expert with scoring interface."""
    try:
        await message.answer_document(
            document=submission.file_id,
            caption=(
                f"📄 <b>Новая работа для проверки</b>\n\n"
                f"📋 Кампания: <b>{campaign.title}</b>\n"
                f"👤 Студент: <b>{author.full_name}</b>\n"
                f"📚 Группа: <b>{author.study_group or 'Не указана'}</b>\n"
                f"🆔 ID: <code>{submission.id}</code>\n"
                f"📅 Загружено: <code>{submission.created_at.strftime('%d.%m.%Y %H:%M')}</code>\n\n"
                f"⬇️ Оцените работу от <b>{campaign.min_score}</b> до <b>{campaign.max_score}</b>:"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send file {submission.file_id}: {e}")
        await message.answer(
            f"📄 <b>Новая работа для проверки</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            f"👤 Студент: <b>{author.full_name}</b>\n"
            f"📚 Группа: <b>{author.study_group or 'Не указана'}</b>\n"
            f"🆔 ID: <code>{submission.id}</code>\n"
            f"⚠️ Файл недоступен для отправки",
            parse_mode="HTML",
        )

    await message.answer(
        "⬇️ Выберите оценку:",
        reply_markup=get_score_keyboard(campaign.min_score, campaign.max_score)
    )


# Command handlers
@router.message(Command("queue"))
async def cmd_queue(message: types.Message) -> None:
    """Handle /queue command - show count of submissions waiting in queue."""
    if not await check_expert_role(message):
        return

    logger.info(f"Expert {message.from_user.id} requested queue status")

    async with session_scope() as session:
        count = await count_pending_submissions(session)

    # Also show Redis-locked submissions
    locked = await queue_service.get_all_locked_submissions()

    await message.answer(
        f"📋 <b>Очередь проверки</b>\n\n"
        f"📦 Работ в очереди: <b>{count}</b>\n"
        f"🔒 На проверке сейчас: <b>{len(locked)}</b>\n\n"
        "Используйте /take для получения следующей работы.",
        parse_mode="HTML",
    )


@router.message(Command("take"))
async def cmd_take(message: types.Message, state: FSMContext) -> None:
    """Handle /take command - get next submission from queue with Redis lock."""
    if not await check_expert_role(message):
        return

    tg_id = message.from_user.id

    logger.info(f"Expert {tg_id} trying to take a submission")

    async with session_scope() as session:
        submissions = await get_submission_pending(session, limit=10)

        for submission in submissions:
            # Get campaign for TTL
            campaign = await get_campaign(submission.campaign_id, session)
            if not campaign:
                continue

            # Try to lock with Redis
            locked = await queue_service.lock_submission(
                submission_id=submission.id,
                expert_id=tg_id,
                ttl_minutes=campaign.ttl_minutes,
            )

            if locked:
                # Update DB status
                await update_submission_status(
                    submission.id,
                    SubmissionStatus.IN_REVIEW,
                    session
                )

                # Get author
                author = await get_user(tg_id=submission.author_id, session=session)

                # Update FSM state
                await state.set_state(ExpertReviewState.reviewing_submission)
                await state.update_data(
                    submission_id=submission.id,
                    campaign_id=submission.campaign_id,
                    ttl_minutes=campaign.ttl_minutes,
                )

                logger.info(f"Expert {tg_id} took submission {submission.id} (TTL: {campaign.ttl_minutes}m)")

                # Send to expert
                await send_submission_to_expert(message, submission, campaign, author)
                return

        await message.answer(
            "📭 <b>Очередь пуста</b>\n\n"
            "Нет доступных работ для проверки.",
            parse_mode="HTML",
        )


@router.message(Command("return"))
async def cmd_return(message: types.Message, state: FSMContext) -> None:
    """Handle /return command - return submission back to queue."""
    if not await check_expert_role(message):
        return

    tg_id = message.from_user.id
    data = await state.get_data()
    submission_id = data.get("submission_id")

    if not submission_id:
        await message.answer("⚠️ У вас нет работы на проверке.")
        return

    logger.info(f"Expert {tg_id} returning submission {submission_id}")

    # Unlock from Redis
    await queue_service.unlock_submission(submission_id)

    # Update DB status
    async with session_scope() as session:
        await update_submission_status(
            submission_id,
            SubmissionStatus.UPLOADED,
            session
        )

    await state.clear()

    await message.answer(
        f"✅ Работа (ID: <code>{submission_id}</code>) возвращена в очередь.",
        parse_mode="HTML",
    )


# Callback query handlers
@router.callback_query(F.data.startswith("score_"))
async def handle_score_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle score button callback."""
    if not callback.message or not isinstance(callback.message, types.Message):
        return

    tg_id = callback.from_user.id
    message = callback.message
    data = await state.get_data()
    submission_id = data.get("submission_id")

    if not submission_id:
        await callback.answer("У вас нет работы на проверке", show_alert=True)
        await message.answer("⚠️ У вас нет работы на проверке. Используйте /take.")
        return

    try:
        score = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора оценки", show_alert=True)
        return

    await state.update_data(score=score)
    await callback.answer(f"Оценка: {score}")

    await state.set_state(ExpertReviewState.waiting_for_comment)
    await message.answer(
        f"📝 <b>Вы выбрали оценку: {score}</b>\n\n"
        "Введите комментарий к работе (или отправьте 'пропустить' для пустого комментария):",
        parse_mode="HTML",
        reply_markup=get_confirm_keyboard()
    )


@router.callback_query(F.data == "confirm_submit")
async def handle_confirm_callback(callback: types.CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Handle confirm button callback - save review."""
    if not callback.message or not isinstance(callback.message, types.Message):
        return

    tg_id = callback.from_user.id
    message = callback.message
    data = await state.get_data()
    submission_id = data.get("submission_id")
    score = data.get("score")
    comment_text = data.get("comment_text", "")

    if not submission_id or score is None:
        await callback.answer("Сначала выберите оценку", show_alert=True)
        return

    if comment_text == "пропустить":
        comment_text = None

    logger.info(f"Expert {tg_id} submitting review for submission {submission_id}: score={score}")

    # Unlock from Redis
    await queue_service.unlock_submission(submission_id)

    # Save to DB and collect data for notifications
    async with session_scope() as session:
        await create_review(
            submission_id=submission_id,
            reviewer_id=tg_id,
            score=score,
            comment_text=comment_text,
            session=session,
        )
        await update_submission_status(submission_id, SubmissionStatus.REVIEWED, session)

        # Get submission with author info for notifications
        submission = await get_submission(submission_id, session)
        campaign = await get_campaign(submission.campaign_id, session)
        author = await get_user(tg_id=submission.author_id, session=session)
        reviewer = await get_user(tg_id=tg_id, session=session)

        # Send to Google Sheets
        sheets_service = _get_sheets_service()
        if sheets_service:
            review_data = {
                "submission_id": submission.id,
                "timestamp": submission.updated_at,
                "campaign": campaign.title if campaign else "",
                "author": author.full_name if author else "",
                "group": author.study_group if author else "",
                "reviewer": reviewer.full_name if reviewer else "",
                "score": score,
                "comment": comment_text,
            }
            try:
                await sheets_service.append_review(review_data)
            except Exception as e:
                logger.error(f"Failed to send review to Google Sheets: {e}")

        # Notify student about review
        if author and not author.is_banned:
            notification_service = _get_notification_service(bot)
            try:
                await notification_service.notify_student_reviewed(
                    student_tg_id=author.tg_id,
                    campaign_title=campaign.title if campaign else "",
                    score=score,
                    comment=comment_text,
                )
            except Exception as e:
                logger.error(f"Failed to notify student: {e}")

    await state.clear()

    await callback.answer("Рецензия сохранена!")
    await message.answer(
        f"✅ <b>Рецензия сохранена!</b>\n\n"
        f"📋 ID работы: <code>{submission_id}</code>\n"
        f"⭐ Оценка: <b>{score}</b>\n"
        f"💬 Комментарий: <b>{comment_text or 'Без комментария'}</b>\n\n"
        "Используйте /take для следующей работы.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cancel_review")
async def handle_cancel_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle cancel button callback."""
    if not callback.message or not isinstance(callback.message, types.Message):
        return

    await callback.answer("Отменено")
    await callback.message.answer(
        "❌ Действие отменено.\n\n"
        "Используйте /return для возврата работы в очередь.",
    )


@router.message(StateFilter(ExpertReviewState.waiting_for_comment))
async def process_comment(message: types.Message, state: FSMContext) -> None:
    """Process expert's comment input."""
    comment_text = message.text.strip()
    await state.update_data(comment_text=comment_text)

    await message.answer(
        "💬 Комментарий сохранен.\n\n"
        "Нажмите 'Подтвердить' для сохранения рецензии.",
        reply_markup=get_confirm_keyboard()
    )


@router.message(Command("expert_stats"))
async def cmd_expert_stats(message: types.Message) -> None:
    """Handle /expert_stats command - show expert's review statistics."""
    if not await check_expert_role(message):
        return

    tg_id = message.from_user.id
    logger.info(f"Expert {tg_id} requested stats")

    async with session_scope() as session:
        from src.services.review_service import get_expert_reviews
        reviews = await get_expert_reviews(tg_id, session)

        total_reviews = len(reviews)
        if total_reviews > 0:
            scores = [r.score for r in reviews if r.score]
            avg_score = sum(scores) / len(scores) if scores else 0
        else:
            avg_score = 0

    await message.answer(
        f"📊 <b>Ваша статистика</b>\n\n"
        f"📝 Всего рецензий: <b>{total_reviews}</b>\n"
        f"⭐ Средняя оценка: <b>{avg_score:.1f}</b>",
        parse_mode="HTML",
    )

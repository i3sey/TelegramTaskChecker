"""Expert handler router for review and feedback commands."""
from typing import Any
from aiogram import Bot, Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.db.engine import session_scope
from src.db.models import UserRole, SubmissionStatus, SubmissionFormat, User, Campaign
from src.bot.services.user_service import get_user, get_users_by_role
from src.bot.services.submission_service import get_submission, update_submission_status
from src.bot.services.review_service import create_review, count_pending_submissions, get_submission_pending
from src.bot.services.campaign_service import get_campaign
from src.bot.services.queue_service import queue_service, QueueService
from src.bot.services.notification_service import NotificationService
from src.bot.utils.logging import logger
from src.bot.keyboards import (
    BTN_QUEUE,
    BTN_TAKE,
    BTN_EXPERT_STATS,
    BTN_MORE,
    build_expert_more_keyboard,
    build_comment_decision_keyboard,
    build_comment_final_keyboard,
    build_comment_skip_keyboard,
    build_ban_comment_keyboard,
    build_review_confirmation_keyboard,
    build_post_review_keyboard,
    get_keyboard_for_role,
)
from src.bot.ui import format_ttl_minutes



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
    waiting_for_ban_reason = State()


def build_quick_score_keyboard() -> InlineKeyboardMarkup:
    """Inline buttons for common score values."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="0", callback_data="score_quick_0"),
                InlineKeyboardButton(text="20", callback_data="score_quick_20"),
                InlineKeyboardButton(text="40", callback_data="score_quick_40"),
            ],
            [
                InlineKeyboardButton(text="60", callback_data="score_quick_60"),
                InlineKeyboardButton(text="80", callback_data="score_quick_80"),
                InlineKeyboardButton(text="100", callback_data="score_quick_100"),
            ],
        ]
    )


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
    return build_review_confirmation_keyboard()


async def check_expert_role(message: types.Message) -> bool:
    """Check if the user has EXPERT role."""
    tg_id = message.from_user.id
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start.")
            return False
        if user.role not in (UserRole.EXPERT, UserRole.EXPERT_ORGANIZER):
            await message.answer("⛔ Эта команда доступна только для экспертов.")
            return False
        if user.role == UserRole.EXPERT and (
            not user.registered_by_code or user.invite_role != "expert"
        ):
            extra_hint = ""
            await message.answer(
                "⛔ Для роли эксперта нужен инвайт. "
                "Откройте ссылку приглашения"
                f"{extra_hint}",
                parse_mode="HTML",
            )
            return False
        if user.is_banned:
            await message.answer("⛔ Ваш аккаунт заблокирован.")
            return False
    return True


async def _send_submission_content(
    message: types.Message,
    submission,
    caption: str,
) -> None:
    submission_type = submission.submission_type or SubmissionFormat.DOCUMENT

    if submission_type == SubmissionFormat.TEXT:
        text_body = (submission.text_content or "").strip() or "—"
        await message.answer(
            f"{caption}\n\n📝 <b>Текст работы:</b>\n<blockquote>{text_body}</blockquote>",
            parse_mode="HTML",
        )
        return

    if submission_type == SubmissionFormat.LINK:
        await message.answer(
            f"{caption}\n\n🔗 <b>Ссылка:</b>\n{submission.external_url or '—'}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    try:
        if submission_type == SubmissionFormat.PHOTO and submission.file_id:
            await message.answer_photo(
                photo=submission.file_id,
                caption=caption,
                parse_mode="HTML",
            )
            return

        if submission.file_id:
            await message.answer_document(
                document=submission.file_id,
                caption=caption,
                parse_mode="HTML",
            )
            return

        await message.answer(
            caption + "\n\n⚠️ У работы отсутствует вложение для отправки.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(
            f"Failed to send submission {submission.id} "
            f"of type {submission_type.value}: {e}"
        )
        fallback = caption + "\n\n⚠️ Вложение не удалось отправить, но вы всё равно можете выставить оценку."
        if submission_type == SubmissionFormat.LINK and submission.external_url:
            fallback += f"\n🔗 Ссылка: {submission.external_url}"
        elif submission_type == SubmissionFormat.TEXT and submission.text_content:
            fallback += f"\n📝 Текст:\n<blockquote>{submission.text_content}</blockquote>"
        elif submission.file_name:
            fallback += f"\n📄 Файл: <b>{submission.file_name}</b>"
        await message.answer(fallback, parse_mode="HTML")

async def send_submission_to_expert(
    message: types.Message,
    submission,
    campaign,
    author: User
) -> None:
    """Send submission to expert with scoring interface."""
    caption = (
        f"📄 <b>Новая работа для проверки</b>\n\n"
        f"📋 Кампания: <b>{campaign.title}</b>\n"
        f"👤 Студент: <b>{author.full_name}</b>\n"
        f"📚 Группа: <b>{author.study_group or 'Не указана'}</b>\n"
        f"🆔 Работа: <code>{submission.id}</code>\n"
        f"🕒 Загружена: <code>{submission.created_at.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"⏳ Время на проверку: <b>{format_ttl_minutes(campaign.ttl_minutes)}</b>\n\n"
        f"Оценивание: от <b>{campaign.min_score}</b> до <b>{campaign.max_score}</b>.\n"
        "Дальше: введите оценку → напишите комментарий → подтвердите результат."
    )
    await _send_submission_content(message, submission, caption)

    reviewer_role = UserRole.EXPERT
    async with session_scope() as session:
        reviewer = await get_user(tg_id=message.from_user.id, session=session)
        if reviewer:
            reviewer_role = reviewer.role

    await message.answer(
        "⬇️ Введите оценку числом.\n"
        f"Допустимый диапазон: {campaign.min_score}–{campaign.max_score}.",
        reply_markup=get_keyboard_for_role(reviewer_role),
    )
    await message.answer(
        "Выберите оценку кнопкой или введите вручную:",
        reply_markup=build_quick_score_keyboard(),
    )


async def _deliver_current_submission(
    message: types.Message,
    state: FSMContext,
    submission_id: int,
) -> bool:
    """Resend the currently assigned submission to an expert."""
    tg_id = message.from_user.id

    async with session_scope() as session:
        submission = await get_submission(submission_id, session)
        if not submission:
            await message.answer("⚠️ Текущая работа не найдена. Нажмите /take еще раз.")
            await queue_service.clear_expert_current_submission(tg_id)
            await state.clear()
            return False

        campaign = await get_campaign(submission.campaign_id, session)
        author = await get_user(tg_id=submission.author_id, session=session)
        if not campaign or not author:
            await message.answer("⚠️ Не удалось восстановить текущую работу. Нажмите /take еще раз.")
            await queue_service.clear_expert_current_submission(tg_id)
            await state.clear()
            return False

    await state.set_state(ExpertReviewState.reviewing_submission)
    await state.update_data(
        submission_id=submission.id,
        campaign_id=submission.campaign_id,
        ttl_minutes=campaign.ttl_minutes,
    )
    await send_submission_to_expert(message, submission, campaign, author)
    await state.set_state(ExpertReviewState.waiting_for_score)
    return True


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
    current_submission_id = await queue_service.get_expert_current_submission(message.from_user.id)
    current_ttl = None
    if current_submission_id is not None:
        ttl_seconds = await queue_service.get_submission_ttl(current_submission_id)
        if ttl_seconds > 0:
            minutes = ttl_seconds // 60
            seconds = ttl_seconds % 60
            current_ttl = f"{minutes}м {seconds}с"

    current_block = ""
    if current_submission_id is not None:
        ttl_text = current_ttl or "истек или недоступен"
        current_block = (
            f"\n🧷 Текущая работа: <code>{current_submission_id}</code>\n"
            f"⏳ Осталось на проверку: <b>{ttl_text}</b>\n"
        )

    await message.answer(
        f"📋 <b>Очередь проверки</b>\n\n"
        f"📦 Работ в очереди: <b>{count}</b>\n"
        f"🔒 На проверке сейчас: <b>{len(locked)}</b>\n"
        f"{current_block}\n"
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

    current_submission_id = await queue_service.get_expert_current_submission(tg_id)
    if current_submission_id is not None:
        lock_info = await queue_service.get_lock_info(current_submission_id)
        if lock_info and lock_info.get("expert_id") == tg_id:
            await message.answer(
                "ℹ️ <b>У вас уже есть работа на проверке.</b>\n"
                "Показываю её ещё раз, чтобы вы могли продолжить.",
                parse_mode="HTML",
            )
            if await _deliver_current_submission(message, state, current_submission_id):
                return
        else:
            await queue_service.clear_expert_current_submission(tg_id)

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
                await state.set_state(ExpertReviewState.waiting_for_score)
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

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        reply_markup = get_keyboard_for_role(user.role) if user else None

    await message.answer(
        f"✅ Работа (ID: <code>{submission_id}</code>) возвращена в очередь.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


# Reply-keyboard handlers for expert actions
@router.message(F.text == BTN_QUEUE)
async def btn_queue(message: types.Message) -> None:
    await cmd_queue(message)


@router.message(F.text == BTN_TAKE)
async def btn_take(message: types.Message, state: FSMContext) -> None:
    await cmd_take(message, state)




@router.message(F.text == BTN_EXPERT_STATS)
async def btn_expert_stats(message: types.Message) -> None:
    await cmd_expert_stats(message)


@router.callback_query(F.data == "expert_take_next")
async def expert_take_next(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer("Ошибка: не удалось получить сообщение", show_alert=True)
        return
    if not await check_expert_role(callback.message):
        return
    await cmd_take(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "expert_show_stats")
async def expert_show_stats(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("Ошибка: не удалось получить сообщение", show_alert=True)
        return
    if not await check_expert_role(callback.message):
        return
    await cmd_expert_stats(callback.message)
    await callback.answer()


@router.message(F.text == BTN_MORE)
async def btn_more(message: types.Message) -> None:
    await message.answer(
        "⚙️ <b>Дополнительные действия</b>",
        parse_mode="HTML",
        reply_markup=build_expert_more_keyboard(),
    )


# Callback query handlers
@router.message(StateFilter(ExpertReviewState.waiting_for_score))
async def process_score_input(message: types.Message, state: FSMContext) -> None:
    """Process score input from expert."""
    data = await state.get_data()
    submission_id = data.get("submission_id")
    campaign_id = data.get("campaign_id")

    if not submission_id or not campaign_id:
        await message.answer("⚠️ У вас нет работы на проверке. Используйте /take.")
        return

    try:
        score = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Введите оценку числом.")
        return

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await message.answer("❌ Кампания не найдена.")
            return

        if score < campaign.min_score or score > campaign.max_score:
            await message.answer(
                f"❌ Оценка должна быть в диапазоне {campaign.min_score}–{campaign.max_score}."
            )
            return

    await state.update_data(score=score)
    await state.set_state(ExpertReviewState.waiting_for_comment)
    await message.answer(
        f"✅ <b>Оценка сохранена: {score}</b>\n\n"
        f"Диапазон оценок: {campaign.min_score}–{campaign.max_score}\n\n"
        "Что дальше?",
        parse_mode="HTML",
        reply_markup=build_comment_decision_keyboard(),
    )


@router.callback_query(F.data.startswith("score_quick_"))
async def process_quick_score(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Process quick score selection from inline buttons."""
    if not callback.message or not isinstance(callback.message, types.Message):
        return

    score_value = callback.data.removeprefix("score_quick_")
    if not score_value.isdigit():
        await callback.answer("Некорректная оценка", show_alert=True)
        return

    data = await state.get_data()
    submission_id = data.get("submission_id")
    campaign_id = data.get("campaign_id")

    if not submission_id or not campaign_id:
        await callback.answer("Сначала возьмите работу на проверку", show_alert=True)
        return

    score = int(score_value)
    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await callback.answer("Кампания не найдена", show_alert=True)
            return
        if score < campaign.min_score or score > campaign.max_score:
            await callback.answer(
                f"Диапазон: {campaign.min_score}-{campaign.max_score}",
                show_alert=True,
            )
            return

    await state.update_data(score=score)
    await state.set_state(ExpertReviewState.waiting_for_comment)
    await callback.answer(f"Оценка {score} сохранена")
    await callback.message.answer(
        f"✅ <b>Оценка сохранена: {score}</b>\n\n"
        f"Диапазон оценок: {campaign.min_score}–{campaign.max_score}\n\n"
        "Что дальше?",
        parse_mode="HTML",
        reply_markup=build_comment_decision_keyboard(),
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

        # Notify student about review
        if author and not author.is_banned:
            notification_service = _get_notification_service(bot)
            try:
                await notification_service.notify_student_reviewed(
                    student_tg_id=author.tg_id,
                    campaign_title=campaign.title if campaign else "",
                    score=score,
                    comment=comment_text,
                    reviewer_name=reviewer.full_name if reviewer else None,
                    is_expert_anon=campaign.is_expert_anon if campaign else True,
                )
            except Exception as e:
                logger.error(f"Failed to notify student: {e}")

    await state.clear()

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        reply_markup = get_keyboard_for_role(user.role) if user else None

    await callback.answer("Рецензия сохранена!")
    await message.answer(
        f"✅ <b>Рецензия сохранена!</b>\n\n"
        f"🆔 Работа: <code>{submission_id}</code>\n"
        f"⭐ Оценка: <b>{score}</b>\n"
        f"💬 Комментарий: <b>{comment_text or 'Без комментария'}</b>\n\n"
        "Можно сразу взять следующую работу или открыть статистику.",
        parse_mode="HTML",
        reply_markup=build_post_review_keyboard(),
    )
    if reply_markup:
        await message.answer("Меню эксперта обновлено.", reply_markup=reply_markup)


@router.callback_query(F.data == "cancel_review")
async def handle_cancel_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle cancel button callback."""
    if not callback.message or not isinstance(callback.message, types.Message):
        return

    data = await state.get_data()
    submission_id = data.get("submission_id")
    if submission_id:
        await queue_service.unlock_submission(submission_id)
        async with session_scope() as session:
            await update_submission_status(
                submission_id,
                SubmissionStatus.UPLOADED,
                session
            )
    await state.clear()

    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        reply_markup = get_keyboard_for_role(user.role) if user else None

    await callback.answer("Работа возвращена в очередь")
    await callback.message.answer(
        "↩️ <b>Работа возвращена в очередь.</b>\n\n"
        "Вы можете взять другую работу командой /take.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


@router.message(StateFilter(ExpertReviewState.waiting_for_comment))
async def process_comment(message: types.Message, state: FSMContext) -> None:
    """Process expert's comment input."""
    if not message.text:
        await message.answer(
            "⚠️ Сейчас можно отправить только текстовый комментарий.\n"
            "Либо напишите комментарий, либо пропустите его.",
            reply_markup=build_comment_skip_keyboard(),
        )
        return

    comment_text = message.text.strip()
    await state.update_data(comment_text=comment_text)

    await message.answer(
        "💬 <b>Комментарий сохранён.</b>\n\n"
        f"Текст: {comment_text}\n\n"
        "Выберите действие с работой:",
        parse_mode="HTML",
        reply_markup=build_comment_final_keyboard()
    )


@router.callback_query(F.data == "score_proceed_comment")
async def handle_score_proceed_comment(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle proceed to comment button - ask for comment."""
    await callback.answer()
    await callback.message.answer(
        "📝 <b>Напишите комментарий к работе</b>\n\n"
        "Комментарий должен содержать ваше мнение о работе, замечания и рекомендации.",
        parse_mode="HTML",
        reply_markup=build_comment_skip_keyboard(),
    )
    await state.set_state(ExpertReviewState.waiting_for_comment)


@router.callback_query(F.data == "score_proceed_ban")
async def handle_score_proceed_ban(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle proceed to ban button - ask for ban reason."""
    await callback.answer()
    await state.set_state(ExpertReviewState.waiting_for_ban_reason)
    await callback.message.answer(
        "⛔ <b>Пожалуйста, объясните причину жалобы на студента</b>\n\n"
        "Напишите комментарий (например: плагиат, нарушение правил, оскорбительный тон и т.д.)",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "comment_skip")
async def handle_comment_skip(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(comment_text=None)
    await callback.answer("Комментарий будет пропущен")
    await callback.message.answer(
        "💬 Комментарий будет пропущен.\n"
        "Выберите действие с работой:",
        parse_mode="HTML",
        reply_markup=build_comment_final_keyboard(),
    )


@router.callback_query(F.data == "ban_request_init")
async def handle_ban_request_init(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle ban request - ask for reason."""
    data = await state.get_data()
    submission_id = data.get("submission_id")
    
    if not submission_id:
        await callback.answer("Ошибка: работа не найдена", show_alert=True)
        return
    
    await state.set_state(ExpertReviewState.waiting_for_ban_reason)
    await callback.answer()
    await callback.message.answer(
        "⛔ <b>Пожалуйста, объясните причину жалобы на студента</b>\n\n"
        "Напишите комментарий (например: плагиат, нарушение правил, оскорбительный тон и т.д.)",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "ban_comment_cancel")
async def handle_ban_comment_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle ban reason input cancellation."""
    await callback.answer()
    data = await state.get_data()
    score = data.get("score")
    comment_text = data.get("comment_text")
    
    # Go back to comment decision menu
    await state.set_state(ExpertReviewState.waiting_for_comment)
    await callback.message.answer(
        f"⬅️ <b>Вернулись к выбору действия</b>\n\n"
        f"⭐ Оценка: <b>{score}</b>\n"
        f"💬 Комментарий: {comment_text or 'Нет'}\n\n"
        "Выберите действие с работой:",
        parse_mode="HTML",
        reply_markup=build_comment_final_keyboard(),
    )


@router.callback_query(F.data == "ban_comment_submit")
async def handle_ban_comment_submit(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle ban reason submission - trigger same as text input."""
    # This will be handled by message handler for waiting_for_ban_reason state
    await callback.answer()


@router.message(StateFilter(ExpertReviewState.waiting_for_ban_reason))
async def process_ban_reason(message: types.Message, state: FSMContext, bot: Bot) -> None:
    """Process ban reason from expert."""
    if not message.text:
        await message.answer("⚠️ Пожалуйста, напишите причину жалобы текстом.")
        return
    
    ban_reason = message.text.strip()
    data = await state.get_data()
    submission_id = data.get("submission_id")
    score = data.get("score")
    comment_text = data.get("comment_text")
    
    if not submission_id:
        await message.answer("❌ Ошибка: работа не найдена.")
        await state.clear()
        return
    
    tg_id = message.from_user.id
    
    logger.info(f"Expert {tg_id} submitting ban request for submission {submission_id}: reason={ban_reason}")
    
    # Unlock from Redis
    await queue_service.unlock_submission(submission_id)
    
    # Save review with ban_comment to DB
    async with session_scope() as session:
        await create_review(
            submission_id=submission_id,
            reviewer_id=tg_id,
            score=score,
            comment_text=comment_text,
            ban_comment=ban_reason,
            session=session,
        )
        await update_submission_status(submission_id, SubmissionStatus.REVIEWED, session)
        
        # Get all organizers to notify
        organizers = await get_users_by_role(UserRole.ORGANIZER, session)
        expert_organizers = await get_users_by_role(UserRole.EXPERT_ORGANIZER, session)
        all_organizers = organizers + expert_organizers
        
        # Get submission info
        submission = await get_submission(submission_id, session)
        campaign = await get_campaign(submission.campaign_id, session)
        author = await get_user(tg_id=submission.author_id, session=session)
        reviewer = await get_user(tg_id=tg_id, session=session)
    
    # Send ban notification to all organizers
    ban_notification_text = (
        "⛔ <b>Жалоба на студента от эксперта</b>\n\n"
        f"🆔 Студент: <b>{author.full_name if author else 'Unknown'}</b> "
        f"(<code>{submission.author_id}</code>)\n"
        f"📋 Кампания: <b>{campaign.title if campaign else 'Unknown'}</b>\n"
        f"👨‍⚖️ Эксперт: <b>{reviewer.full_name if reviewer else 'Unknown'}</b>\n"
        f"⭐ Оценка: <b>{score}</b>\n"
        f"💬 Комментарий эксперта: {comment_text or 'Нет'}\n"
        f"⚠️ Причина жалобы:\n<b>{ban_reason}</b>"
    )
    
    # Build inline keyboard for organizer to confirm ban
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="⛔ Забанить студента", callback_data=f"org_ban_student_{submission.author_id}_{submission_id}")
    builder.button(text="❌ Отклонить жалобу", callback_data=f"org_reject_ban_{submission_id}")
    builder.adjust(1)
    
    # Notify each organizer
    for org in all_organizers:
        try:
            await bot.send_message(
                chat_id=org.tg_id,
                text=ban_notification_text,
                parse_mode="HTML",
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            logger.error(f"Failed to notify organizer {org.tg_id}: {e}")
    
    await state.clear()
    
    # Show success message to expert
    await message.answer(
        "✅ <b>Жалоба отправлена организаторам</b>\n\n"
        "Спасибо за помощь в поддержании качества платформы.\n"
        "Организаторы рассмотрят вашу жалобу и примут решение.",
        parse_mode="HTML",
    )
    
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        reply_markup = get_keyboard_for_role(user.role) if user else None
    
    await message.answer(
        "Можно взять следующую работу или открыть статистику.",
        reply_markup=build_post_review_keyboard() if reply_markup is None else None,
    )


@router.message(Command("expert_stats"))
async def cmd_expert_stats(message: types.Message) -> None:
    """Handle /expert_stats command - show expert's review statistics."""
    if not await check_expert_role(message):
        return

    tg_id = message.from_user.id
    logger.info(f"Expert {tg_id} requested stats")

    async with session_scope() as session:
        from src.bot.services.review_service import get_expert_reviews
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

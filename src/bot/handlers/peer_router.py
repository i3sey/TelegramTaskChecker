"""Peer review and voting router for students."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import and_, exists, func, select

from src.db.engine import session_scope
from src.db.models import CampaignType, Review, Submission, UserRole
from src.bot.services.queue_service import queue_service
from src.bot.services.campaign_service import get_active_campaigns, get_campaign
from src.bot.services.review_service import (
    count_reviewer_reviews_for_campaign,
    create_review,
    get_review_by_submission_and_reviewer,
    get_submission_reviews,
)
from src.bot.services.submission_service import (
    check_submission_availability,
    create_submission,
    get_submission,
    get_user_submissions,
    replace_submission_content,
)
from src.db.models import SubmissionStatus
from src.bot.services.user_service import get_campaign_accesses, get_user
from src.bot.keyboards import (
    BTN_P2P_REVIEW,
    BTN_VOTE,
    build_post_submission_keyboard,
    get_keyboard_for_user,
)
from src.bot.ui import format_ttl_minutes, voting_type_label
from src.bot.utils.logging import logger
from src.bot.handlers.common_review_flow import (
    build_confirm_cancel_keyboard,
    format_comment_saved_text,
    format_review_saved_summary,
    format_score_saved_text,
    send_submission_content,
)


router = Router()
router.name = "peer_router"


class P2PReviewStates(StatesGroup):
    """FSM states for P2P review flow."""
    waiting_for_campaign = State()
    waiting_for_score = State()
    waiting_for_comment = State()
    waiting_for_confirm = State()


class VotingStates(StatesGroup):
    """FSM states for voting flow."""
    waiting_for_campaign = State()
    waiting_for_score = State()


def _build_campaign_keyboard(items: list[tuple[str, int]], prefix: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, campaign_id in items:
        builder.add(
            types.InlineKeyboardButton(
                text=label,
                callback_data=f"{prefix}_{campaign_id}",
            )
        )
    builder.adjust(1)
    return builder.as_markup()


def _build_p2p_comment_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Без комментария", callback_data="p2p_comment_skip")],
            [types.InlineKeyboardButton(text="↩️ Отменить проверку", callback_data="p2p_cancel")],
        ]
    )


def _build_p2p_confirm_keyboard() -> types.InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        confirm_callback="p2p_confirm",
        cancel_callback="p2p_cancel",
    )


def _build_p2p_continue_keyboard(campaign_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="▶️ Проверить следующую",
                    callback_data=f"p2p_next_{campaign_id}",
                )
            ]
        ]
    )


def _build_vote_like_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="👍 Голосовать", callback_data="vote_like")],
            [types.InlineKeyboardButton(text="⏭ Пропустить", callback_data="vote_skip")],
        ]
    )


def _build_vote_continue_keyboard(campaign_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="▶️ Следующая работа",
                    callback_data=f"vote_next_{campaign_id}",
                )
            ]
        ]
    )


async def _get_student(message: types.Message):
    tg_id = message.from_user.id
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start.")
            return None
        if user.role != UserRole.STUDENT:
            await message.answer("⛔ Эта команда доступна только студентам.")
            return None

        student_accesses = await get_campaign_accesses(tg_id=tg_id, session=session)
        has_student_access = any(
            access.invite_role == "student" for access in student_accesses
        )
        if not has_student_access:
            await message.answer(
                "⛔ Для доступа нужен студенческий инвайт. Откройте ссылку приглашения."
            )
            return None

        if user.is_banned:
            await message.answer("⛔ Ваш аккаунт заблокирован.")
            return None
        return user


async def _select_submission(
    campaign_id: int,
    reviewer_id: int,
    session,
    limit: int = 100,
) -> list[Submission]:
    """
    Select next submission for review using load-balanced algorithm.
    
    Prioritizes:
    1. Submissions with fewest reviews
    2. Oldest submissions first (fairness)
    3. Only UPLOADED status (not in review, not reviewed)
    4. Never select author's own submission
    5. Never select if reviewer already reviewed
    
    Args:
        campaign_id: Campaign to get submission from
        reviewer_id: Reviewer's Telegram ID
        session: Database session
    Returns:
            Candidate submissions ordered by fairness rules
    """
    review_count_subq = (
        select(
            Review.submission_id,
            func.count(Review.id).label("review_count"),
        )
        .group_by(Review.submission_id)
        .subquery()
    )

    query = (
        select(Submission)
        .outerjoin(review_count_subq, review_count_subq.c.submission_id == Submission.id)
        .where(
            and_(
                Submission.campaign_id == campaign_id,
                Submission.author_id != reviewer_id,  # Can't review own work
                Submission.status == SubmissionStatus.UPLOADED,  # Must be uploaded
            )
        )
        .where(
            ~exists(
                select(Review.id).where(
                    and_(
                        Review.submission_id == Submission.id,
                        Review.reviewer_id == reviewer_id,  # No duplicates
                    )
                )
            )
        )
        .order_by(
            review_count_subq.c.review_count.asc().nullsfirst(),  # Fairness: least reviewed first
            Submission.created_at.asc(),  # Then oldest first
        )
        .limit(limit)
    )

    result = await session.execute(query)
    return list(result.scalars().all())


async def _acquire_submission_for_review(
    campaign_id: int,
    reviewer_id: int,
    ttl_minutes: int,
    session,
) -> Submission | None:
    """Select and lock the next submission for a reviewer."""
    candidates = await _select_submission(campaign_id, reviewer_id, session)
    for submission in candidates:
        locked = await queue_service.lock_submission(
            submission_id=submission.id,
            expert_id=reviewer_id,
            ttl_minutes=ttl_minutes,
        )
        if locked:
            return submission
    return None


def _campaign_deadline(campaign) -> datetime | None:
    """Calculate campaign submission deadline."""
    deadline = getattr(campaign, "campaign_deadline_at", None)
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return deadline

    created_at = getattr(campaign, "created_at", None)
    ttl_minutes = getattr(campaign, "ttl_minutes", None)
    if not created_at or ttl_minutes is None:
        return None

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(minutes=ttl_minutes)


async def _send_p2p_submission(
    message: types.Message,
    submission: Submission,
    campaign,
) -> None:
    caption = (
        "🧑‍🤝‍🧑 <b>P2P-проверка</b>\n\n"
        f"📋 Кампания: <b>{campaign.title}</b>\n"
        f"🆔 Работа: <code>{submission.id}</code>\n"
        f"⏳ Время на проверку: <b>{format_ttl_minutes(campaign.ttl_minutes)}</b>\n\n"
        f"Оценивание: от <b>{campaign.min_score}</b> до <b>{campaign.max_score}</b>."
    )
    await send_submission_content(message, submission, caption)
    await message.answer(
        f"⬇️ Введите оценку числом ({campaign.min_score}–{campaign.max_score})."
    )


async def _send_voting_submission(
    message: types.Message,
    submission: Submission,
    campaign,
) -> None:
    caption = (
        "🗳 <b>Голосование</b>\n\n"
        f"📋 Кампания: <b>{campaign.title}</b>\n"
        f"🆔 Работа: <code>{submission.id}</code>\n"
        f"Тип: <b>{voting_type_label(campaign.voting_type)}</b>"
    )
    await send_submission_content(message, submission, caption)


def _is_mandatory_p2p_flow(data: dict) -> bool:
    return bool(data.get("pending_submission_payload"))

async def _finalize_pending_p2p_submission(
    message: types.Message,
    state: FSMContext,
    campaign,
    reviewer_id: int,
) -> bool:
    data = await state.get_data()
    payload = data.get("pending_submission_payload")
    submission_action = data.get("pending_submission_action")
    existing_submission_id = data.get("pending_existing_submission_id")

    if not payload:
        await state.clear()
        await message.answer(
            "❌ Данные работы потеряны. Отправьте работу заново через /submit."
        )
        return False

    try:
        async with session_scope() as session:
            action, existing_submission, error_message = await check_submission_availability(
                campaign,
                reviewer_id,
                session,
            )
            if action == "forbid":
                await state.clear()
                await message.answer(
                    error_message or "❌ Публикация работы сейчас недоступна."
                )
                return False

            if submission_action == "replace":
                if (
                    action != "replace"
                    or existing_submission is None
                    or existing_submission.id != existing_submission_id
                ):
                    await state.clear()
                    await message.answer(
                        "❌ Нельзя завершить замену работы: её статус уже изменился. "
                        "Начните заново через /submit."
                    )
                    return False

                submission = await replace_submission_content(
                    submission=existing_submission,
                    submission_type=payload["submission_type"],
                    file_id=payload.get("file_id"),
                    file_name=payload.get("file_name"),
                    mime_type=payload.get("mime_type"),
                    text_content=payload.get("text_content"),
                    external_url=payload.get("external_url"),
                    session=session,
                )
                success_title = "✅ <b>Работа успешно заменена после P2P-проверки!</b>"
                success_hint = (
                    "Что дальше: дождитесь, когда обновлённую работу возьмут на проверку."
                )
            else:
                submission = await create_submission(
                    campaign_id=campaign.id,
                    author_id=reviewer_id,
                    submission_type=payload["submission_type"],
                    file_id=payload.get("file_id"),
                    file_name=payload.get("file_name"),
                    mime_type=payload.get("mime_type"),
                    text_content=payload.get("text_content"),
                    external_url=payload.get("external_url"),
                    session=session,
                )
                success_title = "✅ <b>Работа успешно опубликована после P2P-проверки!</b>"
                success_hint = "Что дальше: дождитесь, когда работу возьмут на проверку."

            user = await get_user(tg_id=reviewer_id, session=session)

        await state.clear()
        await message.answer(
            f"{success_title}\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            f"🆔 Работа: <code>{submission.id}</code>\n"
            f"📌 Статус: 🟡 <b>Ожидает проверки</b>\n"
            f"{success_hint}",
            parse_mode="HTML",
            reply_markup=build_post_submission_keyboard(),
        )
        if user:
            await message.answer(
                "Главное меню:",
                reply_markup=await get_keyboard_for_user(user),
            )
        return True
    except Exception as exc:
        logger.error(f"Error finalizing pending P2P submission for user {reviewer_id}: {exc}")
        await message.answer(
            "❌ Произошла ошибка при публикации работы после P2P-проверки."
        )
        return False

async def start_mandatory_p2p_submission_flow(
    message: types.Message,
    state: FSMContext,
    campaign,
    reviewer_id: int,
    payload: dict,
    submission_action: str,
    existing_submission_id: int | None = None,
) -> None:
    async with session_scope() as session:
        done = await count_reviewer_reviews_for_campaign(
            reviewer_id,
            campaign.id,
            session,
        )

        await state.update_data(
            campaign_id=campaign.id,
            pending_submission_payload=payload,
            pending_submission_action=submission_action,
            pending_existing_submission_id=existing_submission_id,
        )

        if done >= campaign.p2p_reviews_required:
            submission = None
        else:
            submission = await _acquire_submission_for_review(
                campaign_id=campaign.id,
                reviewer_id=reviewer_id,
                ttl_minutes=campaign.ttl_minutes,
                session=session,
            )

    if submission is None:
        await message.answer(
            "ℹ️ <b>Обязательный этап P2P завершён без дополнительных проверок.</b>\n\n"
            "Сейчас нет доступных чужих работ для проверки, поэтому ваша работа будет опубликована сразу.",
            parse_mode="HTML",
        )
        await _finalize_pending_p2p_submission(message, state, campaign, reviewer_id)
        return

    await state.update_data(
        submission_id=submission.id,
        score=None,
        comment_text=None,
    )
    await message.answer(
        "🧑‍🤝‍🧑 <b>Перед публикацией работы нужно выполнить обязательные P2P-проверки.</b>\n\n"
        f"📋 Кампания: <b>{campaign.title}</b>\n"
        f"📈 Требуется рецензий: <b>{campaign.p2p_reviews_required}</b>\n"
        f"✅ Уже выполнено: <b>{done}</b>\n\n"
        "Сейчас откроется первая доступная работа для проверки.",
        parse_mode="HTML",
    )
    await _send_p2p_submission(message, submission, campaign)
    await state.set_state(P2PReviewStates.waiting_for_score)

@router.message(Command("p2p"))
async def cmd_p2p(message: types.Message, state: FSMContext) -> None:
    """Start P2P review flow."""
    await state.clear()
    user = await _get_student(message)
    if not user:
        return

    async with session_scope() as session:
        campaigns = await get_active_campaigns(session)
        submissions = await get_user_submissions(user.tg_id, session)

    submitted_campaign_ids = {s.campaign_id for s in submissions}
    p2p_campaigns = [
        c for c in campaigns
        if c.type == CampaignType.P2P and c.id in submitted_campaign_ids
    ]

    if not p2p_campaigns:
        await message.answer(
            "📭 <b>Нет доступных P2P-кампаний.</b>\n\n"
            "Сначала загрузите работу в P2P-кампанию.",
            parse_mode="HTML",
        )
        return

    items: list[tuple[str, int]] = []
    async with session_scope() as session:
        for campaign in p2p_campaigns:
            done = await count_reviewer_reviews_for_campaign(
                user.tg_id,
                campaign.id,
                session,
            )
            label = f"📋 {campaign.title} ({done}/{campaign.p2p_reviews_required})"
            items.append((label, campaign.id))

    await message.answer(
        "👥 <b>Выберите кампанию для P2P-проверки:</b>",
        reply_markup=_build_campaign_keyboard(items, "p2p_camp"),
        parse_mode="HTML",
    )
    await state.set_state(P2PReviewStates.waiting_for_campaign)


@router.message(F.text == BTN_P2P_REVIEW)
async def btn_p2p(message: types.Message, state: FSMContext) -> None:
    await cmd_p2p(message, state)


@router.callback_query(StateFilter(P2PReviewStates.waiting_for_campaign))
async def process_p2p_campaign(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.data.startswith("p2p_camp_"):
        await callback.answer()
        return

    campaign_id = int(callback.data.removeprefix("p2p_camp_"))
    tg_id = callback.from_user.id

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign or campaign.type != CampaignType.P2P:
            await callback.answer("Кампания не найдена", show_alert=True)
            return
        if not campaign.is_active:
            await callback.answer("Кампания неактивна", show_alert=True)
            return

        submissions = await get_user_submissions(tg_id, session)
        if campaign_id not in {s.campaign_id for s in submissions}:
            await callback.message.answer(
                "⛔ Сначала загрузите свою работу в эту кампанию.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return

        done = await count_reviewer_reviews_for_campaign(tg_id, campaign_id, session)
        if done >= campaign.p2p_reviews_required:
            await callback.message.answer(
                "✅ Вы уже выполнили все проверки для этой кампании.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return

        deadline = _campaign_deadline(campaign)
        if deadline and deadline < datetime.now(timezone.utc):
            await callback.message.answer(
                "⏰ <b>Время прохождения кампании истекло.</b>\n\n"
                "Добавлять рецензии больше нельзя.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return
        
        submission = await _acquire_submission_for_review(
            campaign_id=campaign_id,
            reviewer_id=tg_id,
            ttl_minutes=campaign.ttl_minutes,
            session=session,
        )
        if not submission:
            await callback.message.answer(
                "📭 <b>Нет доступных работ для проверки сейчас.</b>\n\n"
                "Все подходящие работы уже заняты или получили требуемое количество рецензий.\n"
                "Попробуйте позже или выберите другую кампанию.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return

    await state.update_data(
        campaign_id=campaign_id,
        submission_id=submission.id,
        score=None,
        comment_text=None,
    )
    await _send_p2p_submission(callback.message, submission, campaign)
    await state.set_state(P2PReviewStates.waiting_for_score)
    await callback.answer()


@router.message(StateFilter(P2PReviewStates.waiting_for_score))
async def process_p2p_score(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    campaign_id = data.get("campaign_id")

    if not submission_id or not campaign_id:
        await message.answer("⚠️ Не удалось найти работу. Используйте /p2p снова.")
        await state.clear()
        return

    try:
        score = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Введите целое число.")
        return

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await message.answer("❌ Кампания не найдена.")
            await state.clear()
            return
        if score < campaign.min_score or score > campaign.max_score:
            await message.answer(
                f"❌ Оценка должна быть в диапазоне {campaign.min_score}–{campaign.max_score}."
            )
            return

    await state.update_data(score=score)
    await state.set_state(P2PReviewStates.waiting_for_comment)
    await message.answer(
        format_score_saved_text(
            score=score,
            min_score=campaign.min_score,
            max_score=campaign.max_score,
            next_step_text="Теперь отправьте комментарий. Если он не нужен, нажмите кнопку ниже.",
        ),
        parse_mode="HTML",
        reply_markup=_build_p2p_comment_keyboard(),
    )


@router.message(StateFilter(P2PReviewStates.waiting_for_comment))
async def process_p2p_comment(message: types.Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer(
            "⚠️ Сейчас можно отправить только текстовый комментарий.",
            reply_markup=_build_p2p_comment_keyboard(),
        )
        return

    comment_text = message.text.strip()
    await state.update_data(comment_text=comment_text)
    await state.set_state(P2PReviewStates.waiting_for_confirm)
    await message.answer(
        format_comment_saved_text(
            comment_text=comment_text,
            next_step_text="Нажмите «Подтвердить», чтобы сохранить рецензию.",
        ),
        parse_mode="HTML",
        reply_markup=_build_p2p_confirm_keyboard(),
    )


@router.callback_query(F.data == "p2p_comment_skip")
async def p2p_comment_skip(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.update_data(comment_text=None)
    await state.set_state(P2PReviewStates.waiting_for_confirm)
    await callback.message.answer(
        "💬 Комментарий будет пропущен.\n"
        "Нажмите «Подтвердить», чтобы сохранить рецензию.",
        reply_markup=_build_p2p_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "p2p_cancel")
async def p2p_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    if submission_id:
        await queue_service.unlock_submission(int(submission_id))
        logger.info(
            f"P2P review cancelled: reviewer={callback.from_user.id}, "
            f"submission={submission_id}"
        )
    
    await state.clear()
    await callback.message.answer(
        "↩️ <b>Проверка отменена.</b>\n\n"
        "Используйте /p2p, чтобы начать снова.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "p2p_confirm")
async def p2p_confirm(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    campaign_id = data.get("campaign_id")
    score = data.get("score")
    comment_text = data.get("comment_text")
    reviewer_id = callback.from_user.id
    mandatory_flow = _is_mandatory_p2p_flow(data)

    if not submission_id or score is None or not campaign_id:
        await callback.answer("❌ Не хватает данных для сохранения", show_alert=True)
        return

    try:
        async with session_scope() as session:
            existing = await get_review_by_submission_and_reviewer(
                submission_id,
                reviewer_id,
                session,
            )
            if existing:
                await queue_service.unlock_submission(int(submission_id))
                if mandatory_flow:
                    await state.update_data(
                        submission_id=None,
                        score=None,
                        comment_text=None,
                    )
                else:
                    await state.clear()
                await callback.message.answer(
                    "⚠️ <b>Вы уже проверяли эту работу.</b>\n\n"
                    "Повторная рецензия не допускается.",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            submission = await get_submission(submission_id, session)
            if not submission or submission.status != SubmissionStatus.UPLOADED:
                await queue_service.unlock_submission(int(submission_id))
                if mandatory_flow:
                    await state.update_data(
                        submission_id=None,
                        score=None,
                        comment_text=None,
                    )
                else:
                    await state.clear()
                await callback.message.answer(
                    "⚠️ <b>Работа уже не доступна для проверки.</b>\n\n"
                    "Она могла быть завершена или удалена.",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            campaign = await get_campaign(campaign_id, session)
            if not campaign or not campaign.is_active:
                await queue_service.unlock_submission(int(submission_id))
                if mandatory_flow:
                    await state.update_data(
                        submission_id=None,
                        score=None,
                        comment_text=None,
                    )
                else:
                    await state.clear()
                await callback.message.answer(
                    "⚠️ <b>Кампания больше не активна.</b>",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            await create_review(
                submission_id=submission_id,
                reviewer_id=reviewer_id,
                score=score,
                comment_text=comment_text,
                session=session,
            )

            user_done = await count_reviewer_reviews_for_campaign(
                reviewer_id,
                campaign_id,
                session,
            )
            submission_reviews = await get_submission_reviews(submission_id, session)
            submission_review_count = len(submission_reviews)

        await queue_service.unlock_submission(int(submission_id))

        user_complete = user_done >= campaign.p2p_reviews_required
        submission_complete = submission_review_count >= campaign.p2p_reviews_required
        completion_emoji = "✅" if user_complete else "📝"
        progress_text = f"{user_done}/{campaign.p2p_reviews_required}"

        submission_status = (
            f"✅ <b>Эта работа получила все рецензии!</b>"
            if submission_complete
            else f"📊 <b>На этой работе {submission_review_count}/{campaign.p2p_reviews_required} рецензий</b>"
        )

        if mandatory_flow:
            await state.update_data(
                submission_id=None,
                score=None,
                comment_text=None,
            )
        else:
            await state.clear()

        await callback.message.answer(
            f"{completion_emoji} "
            + format_review_saved_summary(
                submission_id=submission_id,
                score=score,
                comment_summary=comment_text if comment_text else "Нет комментария",
                extra_text=f"📈 Ваш прогресс: <b>{progress_text}</b>\n{submission_status}",
            ),
            parse_mode="HTML",
            reply_markup=_build_p2p_continue_keyboard(campaign_id) if not user_complete else None,
        )

        if mandatory_flow:
            if user_complete:
                await callback.message.answer(
                    "🎉 <b>Требуемое число рецензий набрано.</b>\n\n"
                    "Теперь ваша работа будет опубликована.",
                    parse_mode="HTML",
                )
                await _finalize_pending_p2p_submission(
                    callback.message,
                    state,
                    campaign,
                    reviewer_id,
                )
            else:
                async with session_scope() as session:
                    next_submission = await _acquire_submission_for_review(
                        campaign_id=campaign_id,
                        reviewer_id=reviewer_id,
                        ttl_minutes=campaign.ttl_minutes,
                        session=session,
                    )

                if next_submission is None:
                    await callback.message.answer(
                        "ℹ️ <b>Доступные работы для обязательной проверки закончились.</b>\n\n"
                        "Ваша работа будет опубликована, так как новых подходящих работ больше нет.",
                        parse_mode="HTML",
                    )
                    await _finalize_pending_p2p_submission(
                        callback.message,
                        state,
                        campaign,
                        reviewer_id,
                    )
                else:
                    await state.update_data(
                        submission_id=next_submission.id,
                        score=None,
                        comment_text=None,
                    )
                    await callback.message.answer(
                        "➡️ <b>Переходим к следующей обязательной проверке.</b>",
                        parse_mode="HTML",
                    )
                    await _send_p2p_submission(
                        callback.message,
                        next_submission,
                        campaign,
                    )
                    await state.set_state(P2PReviewStates.waiting_for_score)
        else:
            if user_complete:
                await callback.message.answer(
                    "🎉 <b>Поздравляем!</b>\n\n"
                    "Вы выполнили все требуемые рецензии для этой кампании.",
                    parse_mode="HTML",
                )

        await callback.answer("✅ Рецензия сохранена")
    except Exception as exc:
        logger.error(f"Error saving review {submission_id}: {exc}")
        await queue_service.unlock_submission(int(submission_id))
        await callback.message.answer(
            "❌ <b>Не удалось сохранить рецензию.</b>\n\n"
            "Введённые оценка и комментарий сохранены в текущем шаге.\n"
            "Попробуйте подтвердить отправку ещё раз.\n"
            "Если ошибка повторится, перезапустите сценарий через /p2p.",
            parse_mode="HTML",
        )
        await callback.answer("Ошибка сохранения", show_alert=True)


@router.callback_query(F.data.startswith("p2p_next_"))
async def p2p_next(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle 'Next submission' button in P2P review."""
    campaign_id = int(callback.data.removeprefix("p2p_next_"))
    tg_id = callback.from_user.id

    try:
        async with session_scope() as session:
            campaign = await get_campaign(campaign_id, session)
            if not campaign or not campaign.is_active:
                await callback.answer(
                    "❌ Кампания больше не активна", 
                    show_alert=True
                )
                return

            done = await count_reviewer_reviews_for_campaign(tg_id, campaign_id, session)
            if done >= campaign.p2p_reviews_required:
                await callback.message.answer(
                    "✅ <b>Вы уже выполнили все проверки!</b>\n\n"
                    f"Выполнено: {done}/{campaign.p2p_reviews_required} рецензий",
                    parse_mode="HTML",
                )
                await callback.answer()
                await state.clear()
                return

            current_data = await state.get_data()
            current_submission_id = current_data.get("submission_id")
            if current_submission_id:
                await queue_service.unlock_submission(int(current_submission_id))

            submission = await _acquire_submission_for_review(
                campaign_id=campaign_id,
                reviewer_id=tg_id,
                ttl_minutes=campaign.ttl_minutes,
                session=session,
            )
            if not submission:
                await callback.message.answer(
                    "📭 <b>Сейчас нет доступных работ для проверки.</b>\n\n"
                    "Возможные причины:\n"
                    "• подходящие работы уже разобраны другими студентами;\n"
                    "• все работы набрали нужное число рецензий;\n"
                    "• новых работ в этой кампании пока нет.\n\n"
                    "Попробуйте вернуться позже или выберите другую активную кампанию.",
                    parse_mode="HTML",
                )
                await callback.answer()
                await state.clear()
                return

        await state.update_data(
            campaign_id=campaign_id,
            submission_id=submission.id,
            score=None,
            comment_text=None,
        )
        await _send_p2p_submission(callback.message, submission, campaign)
        await state.set_state(P2PReviewStates.waiting_for_score)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in p2p_next: {e}")
        await callback.message.answer(
            "❌ <b>Ошибка при загрузке следующей работы.</b>\n\n"
            "Используйте /p2p для перезагрузки.",
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer(show_alert=True)


@router.message(Command("vote"))
async def cmd_vote(message: types.Message, state: FSMContext) -> None:
    """Start voting flow."""
    await state.clear()
    user = await _get_student(message)
    if not user:
        return

    async with session_scope() as session:
        campaigns = await get_active_campaigns(session)

    voting_campaigns = [c for c in campaigns if c.type == CampaignType.VOTING]

    if not voting_campaigns:
        await message.answer(
            "📭 <b>Нет активных кампаний для голосования.</b>",
            parse_mode="HTML",
        )
        return

    items: list[tuple[str, int]] = []
    for campaign in voting_campaigns:
        label = f"📋 {campaign.title} ({voting_type_label(campaign.voting_type)})"
        items.append((label, campaign.id))

    await message.answer(
        "🗳 <b>Выберите кампанию для голосования:</b>",
        reply_markup=_build_campaign_keyboard(items, "vote_camp"),
        parse_mode="HTML",
    )
    await state.set_state(VotingStates.waiting_for_campaign)


@router.message(F.text == BTN_VOTE)
async def btn_vote(message: types.Message, state: FSMContext) -> None:
    await cmd_vote(message, state)


@router.callback_query(StateFilter(VotingStates.waiting_for_campaign))
async def process_vote_campaign(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.data.startswith("vote_camp_"):
        await callback.answer()
        return

    campaign_id = int(callback.data.removeprefix("vote_camp_"))
    tg_id = callback.from_user.id

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign or campaign.type != CampaignType.VOTING:
            await callback.answer("Кампания не найдена", show_alert=True)
            return
        if not campaign.is_active:
            await callback.answer("Кампания неактивна", show_alert=True)
            return

        voting_type = campaign.voting_type or "score"

        submission = await _acquire_submission_for_review(
            campaign_id=campaign_id,
            reviewer_id=tg_id,
            ttl_minutes=campaign.ttl_minutes,
            session=session,
        )
        if not submission:
            await callback.message.answer(
                "📭 Нет доступных работ для голосования сейчас.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return

    await state.update_data(
        campaign_id=campaign_id,
        submission_id=submission.id,
        voting_type=voting_type,
    )
    await _send_voting_submission(callback.message, submission, campaign)

    if voting_type == "like":
        await callback.message.answer(
            "Выберите вариант голосования:",
            reply_markup=_build_vote_like_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.answer(
        f"⬇️ Введите оценку числом ({campaign.min_score}–{campaign.max_score}).",
    )
    await state.set_state(VotingStates.waiting_for_score)
    await callback.answer()


@router.callback_query(F.data.in_({"vote_like", "vote_skip"}))
async def vote_like_or_skip(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle like-type voting (simple yes/no)."""
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    submission_id = data.get("submission_id")
    voter_id = callback.from_user.id

    if not campaign_id or not submission_id:
        await callback.answer(
            "❌ Ошибка: информация кампании потеряна", 
            show_alert=True
        )
        await state.clear()
        return

    if callback.data == "vote_skip":
        await queue_service.unlock_submission(int(submission_id))
        await state.clear()
        await callback.message.answer(
            "⏭️ <b>Голос пропущен.</b>\n\n"
            "Эта работа не будет учтена в вашем голосовании.",
            reply_markup=_build_vote_continue_keyboard(campaign_id),
        )
        await callback.answer()
        return

    # User clicked "Like"
    try:
        async with session_scope() as session:
            # Atomic check for duplicate
            existing = await get_review_by_submission_and_reviewer(
                submission_id,
                voter_id,
                session,
            )
            if existing:
                await queue_service.unlock_submission(int(submission_id))
                await state.clear()
                await callback.message.answer(
                    "⚠️ <b>Вы уже голосовали за эту работу.</b>\n\n"
                    "Повторное голосование не допускается.",
                    parse_mode="HTML",
                )
                await callback.answer()
                return

            await create_review(
                submission_id=submission_id,
                reviewer_id=voter_id,
                score=1,  # Like = score 1
                comment_text=None,
                session=session,
            )

        await queue_service.unlock_submission(int(submission_id))
        await state.clear()
        await callback.message.answer(
            "👍 <b>Голос учтён!</b>\n\n"
            "Ваша оценка была сохранена.",
            parse_mode="HTML",
            reply_markup=_build_vote_continue_keyboard(campaign_id),
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error saving vote for {submission_id}: {e}")
        await state.clear()
        await callback.message.answer(
            "❌ <b>Ошибка при сохранении голоса.</b>\n\n"
            "Пожалуйста, попробуйте снова.",
            parse_mode="HTML",
        )
        await callback.answer(show_alert=True)


@router.message(StateFilter(VotingStates.waiting_for_score))
async def process_vote_score(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    submission_id = data.get("submission_id")

    if not campaign_id or not submission_id:
        await message.answer("⚠️ Не удалось найти работу. Используйте /vote снова.")
        await state.clear()
        return

    try:
        score = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Введите целое число.")
        return

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await message.answer("❌ Кампания не найдена.")
            await state.clear()
            return
        if score < campaign.min_score or score > campaign.max_score:
            await message.answer(
                f"❌ Оценка должна быть в диапазоне {campaign.min_score}–{campaign.max_score}."
            )
            return

        existing = await get_review_by_submission_and_reviewer(
            submission_id,
            message.from_user.id,
            session,
        )
        if existing:
            await queue_service.unlock_submission(int(submission_id))
            await message.answer("⚠️ Вы уже голосовали за эту работу.")
            await state.clear()
            return

        await create_review(
            submission_id=submission_id,
            reviewer_id=message.from_user.id,
            score=score,
            comment_text=None,
            session=session,
        )

    await queue_service.unlock_submission(int(submission_id))
    await state.clear()
    await message.answer(
        "✅ Голос учтён!",
        reply_markup=_build_vote_continue_keyboard(campaign_id),
    )


@router.callback_query(F.data.startswith("vote_next_"))
async def vote_next(callback: types.CallbackQuery, state: FSMContext) -> None:
    campaign_id = int(callback.data.removeprefix("vote_next_"))
    tg_id = callback.from_user.id

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await callback.answer("Кампания не найдена", show_alert=True)
            return
        if not campaign.is_active:
            await callback.answer("Кампания неактивна", show_alert=True)
            return

        voting_type = campaign.voting_type or "score"

        submission = await _acquire_submission_for_review(
            campaign_id=campaign_id,
            reviewer_id=tg_id,
            ttl_minutes=campaign.ttl_minutes,
            session=session,
        )
        if not submission:
            await callback.message.answer(
                "📭 Нет доступных работ для голосования сейчас.",
                parse_mode="HTML",
            )
            await callback.answer()
            return

    await state.update_data(
        campaign_id=campaign_id,
        submission_id=submission.id,
        voting_type=voting_type,
    )
    await _send_voting_submission(callback.message, submission, campaign)

    if voting_type == "like":
        await callback.message.answer(
            "Выберите вариант голосования:",
            reply_markup=_build_vote_like_keyboard(),
        )
        await callback.answer()
        return

    await callback.message.answer(
        f"⬇️ Введите оценку числом ({campaign.min_score}–{campaign.max_score}).",
    )
    await state.set_state(VotingStates.waiting_for_score)
    await callback.answer()

"""Peer review router for students."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import and_, exists, func, or_, select

from src.db.engine import session_scope
from src.db.models import CampaignType, Review, Submission, UserRole
from src.bot.services.queue_service import queue_service
from src.bot.services.campaign_service import get_active_campaigns, get_campaign
from src.bot.services.review_service import (
    count_reviewer_reviews_for_campaign,
    create_p2p_review_atomic,
)
from src.bot.services.submission_service import (
    get_submission,
    get_user_submissions,
)
from src.db.models import SubmissionStatus
from src.bot.services.user_service import get_campaign_accesses, get_user
from src.bot.keyboards import (
    BTN_P2P_REVIEW,
    build_post_submission_keyboard,
)
from src.bot.ui import format_ttl_minutes
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


def _build_p2p_comment_keyboard(submission_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(
                text="✅ Без комментария",
                callback_data=f"p2p_comment_skip_{submission_id}",
            )],
            [types.InlineKeyboardButton(
                text="↩️ Отменить проверку",
                callback_data=f"p2p_cancel_{submission_id}",
            )],
        ]
    )


def _build_p2p_confirm_keyboard(submission_id: int) -> types.InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        confirm_callback=f"p2p_confirm_{submission_id}",
        cancel_callback=f"p2p_cancel_{submission_id}",
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
    required_reviews: int,
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
        .where(
            or_(
                review_count_subq.c.review_count.is_(None),
                review_count_subq.c.review_count < required_reviews,
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
    required_reviews: int,
    ttl_minutes: int,
    session,
) -> tuple[Submission, str] | None:
    """Select and lock the next submission for a reviewer."""
    candidates = await _select_submission(
        campaign_id,
        reviewer_id,
        required_reviews,
        session,
    )
    for submission in candidates:
        lock_token = await queue_service.lock_submission(
            submission_id=submission.id,
            expert_id=reviewer_id,
            ttl_minutes=ttl_minutes,
        )
        if lock_token:
            return submission, lock_token
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
        f"📋 Кампания: <b>{html.escape(campaign.title)}</b>\n"
        f"🆔 Работа: <code>{submission.id}</code>\n"
        f"⏳ Время на проверку: <b>{format_ttl_minutes(campaign.ttl_minutes)}</b>\n\n"
        f"Оценивание: от <b>{campaign.min_score}</b> до <b>{campaign.max_score}</b>."
    )
    await send_submission_content(message, submission, caption)
    await message.answer(
        f"⬇️ Введите оценку числом ({campaign.min_score}–{campaign.max_score})."
    )


async def start_mandatory_p2p_submission_flow(
    message: types.Message,
    state: FSMContext,
    campaign,
    reviewer_id: int,
    own_submission_id: int,
) -> None:
    async with session_scope() as session:
        done = await count_reviewer_reviews_for_campaign(
            reviewer_id,
            campaign.id,
            session,
        )

        await state.update_data(campaign_id=campaign.id, own_submission_id=own_submission_id)

        if done >= campaign.p2p_reviews_required:
            own_submission = await get_submission(own_submission_id, session)
            if own_submission and own_submission.p2p_completed_at is None:
                own_submission.p2p_completed_at = datetime.now(timezone.utc)
            acquired = None
        else:
            acquired = await _acquire_submission_for_review(
                campaign_id=campaign.id,
                reviewer_id=reviewer_id,
                required_reviews=campaign.p2p_reviews_required,
                ttl_minutes=campaign.ttl_minutes,
                session=session,
            )

    if done >= campaign.p2p_reviews_required:
        await state.clear()
        await message.answer(
            "✅ <b>P2P-этап уже завершён.</b>\n\n"
            "Ваша работа сохранена и считается сданной.",
            parse_mode="HTML",
            reply_markup=build_post_submission_keyboard(),
        )
        return

    if acquired is None:
        await state.clear()
        await message.answer(
            "⏳ <b>Работа сохранена и ожидает продолжения P2P.</b>\n\n"
            "Сейчас нет свободных чужих работ. Вернитесь позже через /p2p — "
            "повторно загружать свою работу не нужно.",
            parse_mode="HTML",
            reply_markup=_build_p2p_continue_keyboard(campaign.id),
        )
        return

    submission, lock_token = acquired
    await state.update_data(
        submission_id=submission.id,
        lock_token=lock_token,
        score=None,
        comment_text=None,
    )
    await message.answer(
        "🧑‍🤝‍🧑 <b>Перед публикацией работы нужно выполнить обязательные P2P-проверки.</b>\n\n"
        f"📋 Кампания: <b>{html.escape(campaign.title)}</b>\n"
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
        accesses = await get_campaign_accesses(tg_id=user.tg_id, session=session)

    submitted_campaign_ids = {s.campaign_id for s in submissions}
    accessible_campaign_ids = {
        access.campaign_id
        for access in accesses
        if access.invite_role == "student"
    }
    p2p_campaigns = [
        c for c in campaigns
        if (
            c.type == CampaignType.P2P
            and c.id in submitted_campaign_ids
            and c.id in accessible_campaign_ids
        )
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

        accesses = await get_campaign_accesses(tg_id=tg_id, session=session)
        if not any(
            access.campaign_id == campaign_id and access.invite_role == "student"
            for access in accesses
        ):
            await callback.answer("Нет доступа к кампании", show_alert=True)
            await state.clear()
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
            own_submission = next(
                (
                    submission
                    for submission in submissions
                    if submission.campaign_id == campaign_id
                ),
                None,
            )
            if own_submission and own_submission.p2p_completed_at is None:
                own_submission.p2p_completed_at = datetime.now(timezone.utc)
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
        
        acquired = await _acquire_submission_for_review(
            campaign_id=campaign_id,
            reviewer_id=tg_id,
            required_reviews=campaign.p2p_reviews_required,
            ttl_minutes=campaign.ttl_minutes,
            session=session,
        )
        if not acquired:
            await callback.message.answer(
                "📭 <b>Нет доступных работ для проверки сейчас.</b>\n\n"
                "Все подходящие работы уже заняты или получили требуемое количество рецензий.\n"
                "Попробуйте позже или выберите другую кампанию.",
                parse_mode="HTML",
            )
            await callback.answer()
            await state.clear()
            return

    submission, lock_token = acquired
    await state.update_data(
        campaign_id=campaign_id,
        submission_id=submission.id,
        lock_token=lock_token,
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
        reply_markup=_build_p2p_comment_keyboard(submission_id),
    )


@router.message(StateFilter(P2PReviewStates.waiting_for_comment))
async def process_p2p_comment(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    if not submission_id:
        await message.answer("⚠️ Работа больше не выбрана. Запустите /p2p снова.")
        await state.clear()
        return
    if not message.text:
        await message.answer(
            "⚠️ Сейчас можно отправить только текстовый комментарий.",
            reply_markup=_build_p2p_comment_keyboard(submission_id),
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
        reply_markup=_build_p2p_confirm_keyboard(submission_id),
    )


@router.callback_query(F.data.startswith("p2p_comment_skip_"))
async def p2p_comment_skip(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    callback_submission_id = callback.data.removeprefix("p2p_comment_skip_")
    if not submission_id or callback_submission_id != str(submission_id):
        await callback.answer("Эта кнопка устарела", show_alert=True)
        return
    await state.update_data(comment_text=None)
    await state.set_state(P2PReviewStates.waiting_for_confirm)
    await callback.message.answer(
        "💬 Комментарий будет пропущен.\n"
        "Нажмите «Подтвердить», чтобы сохранить рецензию.",
        reply_markup=_build_p2p_confirm_keyboard(submission_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("p2p_cancel_"))
async def p2p_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    lock_token = data.get("lock_token")
    callback_submission_id = callback.data.removeprefix("p2p_cancel_")
    if not submission_id or callback_submission_id != str(submission_id):
        await callback.answer("Эта кнопка устарела", show_alert=True)
        return
    if lock_token:
        await queue_service.unlock_submission(
            int(submission_id),
            expert_id=callback.from_user.id,
            lock_token=lock_token,
        )
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


@router.callback_query(F.data.startswith("p2p_confirm_"))
async def p2p_confirm(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    submission_id = data.get("submission_id")
    campaign_id = data.get("campaign_id")
    lock_token = data.get("lock_token")
    score = data.get("score")
    comment_text = data.get("comment_text")
    reviewer_id = callback.from_user.id
    callback_submission_id = callback.data.removeprefix("p2p_confirm_")

    if (
        not submission_id
        or callback_submission_id != str(submission_id)
        or score is None
        or not campaign_id
        or not lock_token
    ):
        await callback.answer("❌ Не хватает данных для сохранения", show_alert=True)
        return

    lock_info = await queue_service.get_lock_info(int(submission_id))
    if (
        not lock_info
        or lock_info.get("expert_id") != reviewer_id
        or lock_info.get("token") != lock_token
    ):
        await state.clear()
        await callback.answer("Время проверки истекло. Возьмите работу заново.", show_alert=True)
        return

    try:
        async with session_scope() as session:
            campaign = await get_campaign(campaign_id, session)
            result = await create_p2p_review_atomic(
                submission_id=submission_id,
                campaign_id=campaign_id,
                reviewer_id=reviewer_id,
                score=score,
                comment_text=comment_text,
                session=session,
            )
        await queue_service.unlock_submission(
            int(submission_id),
            expert_id=reviewer_id,
            lock_token=lock_token,
        )
        await state.clear()

        completion_emoji = "✅" if result.reviewer_completed else "📝"
        progress_text = (
            f"{result.reviewer_review_count}/{campaign.p2p_reviews_required}"
        )

        submission_status = (
            "✅ <b>Эта работа получила все рецензии!</b>"
            if result.submission_completed
            else f"📊 <b>На этой работе {result.submission_review_count}/{campaign.p2p_reviews_required} рецензий</b>"
        )

        await callback.message.answer(
            f"{completion_emoji} "
            + format_review_saved_summary(
                submission_id=submission_id,
                score=score,
                comment_summary=comment_text if comment_text else "Нет комментария",
                extra_text=f"📈 Ваш прогресс: <b>{progress_text}</b>\n{submission_status}",
            ),
            parse_mode="HTML",
            reply_markup=(
                _build_p2p_continue_keyboard(campaign_id)
                if not result.reviewer_completed
                else build_post_submission_keyboard()
            ),
        )

        if result.reviewer_completed:
            await callback.message.answer(
                "🎉 <b>P2P-этап завершён.</b>\n\n"
                "Ваша работа сохранена и теперь считается окончательно сданной.",
                parse_mode="HTML",
            )

        await callback.answer("✅ Рецензия сохранена")
    except ValueError as exc:
        reason = str(exc)
        await queue_service.unlock_submission(
            int(submission_id),
            expert_id=reviewer_id,
            lock_token=lock_token,
        )
        await state.clear()
        messages = {
            "duplicate_review": "Вы уже проверяли эту работу.",
            "submission_complete": "Работа уже получила все рецензии.",
            "submission_unavailable": "Работа больше недоступна.",
            "campaign_unavailable": "Кампания больше недоступна.",
            "reviewer_forbidden": "У вас больше нет доступа к этой кампании.",
            "own_submission": "Нельзя проверять собственную работу.",
            "invalid_score": "Оценка вышла за допустимый диапазон.",
        }
        await callback.message.answer(
            f"⚠️ <b>{messages.get(reason, 'Рецензию сохранить нельзя.')}</b>\n\n"
            "Выберите другую работу через /p2p.",
            parse_mode="HTML",
        )
        await callback.answer("Рецензия не сохранена", show_alert=True)
    except Exception as exc:
        logger.error(f"Error saving review {submission_id}: {exc}")
        await callback.message.answer(
            "❌ <b>Не удалось сохранить рецензию.</b>\n\n"
            "Введённые оценка и комментарий сохранены в текущем шаге.\n"
            "Попробуйте подтвердить отправку ещё раз.\n"
            "Если ошибка повторится, отмените проверку и запустите /p2p.",
            parse_mode="HTML",
        )
        await callback.answer("Ошибка сохранения", show_alert=True)


@router.callback_query(F.data.startswith("p2p_next_"))
async def p2p_next(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Handle 'Next submission' button in P2P review."""
    campaign_id_text = callback.data.removeprefix("p2p_next_")
    if not campaign_id_text.isdigit():
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    campaign_id = int(campaign_id_text)
    tg_id = callback.from_user.id

    try:
        async with session_scope() as session:
            campaign = await get_campaign(campaign_id, session)
            accesses = await get_campaign_accesses(tg_id=tg_id, session=session)
            has_access = any(
                access.campaign_id == campaign_id and access.invite_role == "student"
                for access in accesses
            )
            if (
                not campaign
                or campaign.type != CampaignType.P2P
                or not campaign.is_active
                or not has_access
            ):
                await callback.answer(
                    "❌ Кампания недоступна",
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
            current_lock_token = current_data.get("lock_token")
            if current_submission_id and current_lock_token:
                await queue_service.unlock_submission(
                    int(current_submission_id),
                    expert_id=tg_id,
                    lock_token=current_lock_token,
                )

            acquired = await _acquire_submission_for_review(
                campaign_id=campaign_id,
                reviewer_id=tg_id,
                required_reviews=campaign.p2p_reviews_required,
                ttl_minutes=campaign.ttl_minutes,
                session=session,
            )
            if not acquired:
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

        submission, lock_token = acquired
        await state.update_data(
            campaign_id=campaign_id,
            submission_id=submission.id,
            lock_token=lock_token,
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

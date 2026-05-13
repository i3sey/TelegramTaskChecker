"""Campaign management router for organizers."""
from datetime import datetime, timedelta, timezone
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from src.db.engine import session_scope
from src.db.models import UserRole, CampaignType, Campaign, Submission, Review, SubmissionStatus
from src.bot.services.user_service import get_user
from src.bot.services.campaign_service import (
    get_campaign,
    get_active_campaigns,
    create_campaign,
    get_campaigns_by_organizer,
)
from src.bot.services.invite_service import create_invite
from src.bot.utils.logging import logger
from src.bot.states import CampaignCreationStates, SubmissionStates
from src.bot.keyboards import (
    BTN_CAMPAIGNS,
    BTN_SUBMIT,
    BTN_MY_SUBMISSIONS,
    BTN_CREATE_CAMPAIGN,
    BTN_HOURS_12,
    BTN_HOURS_24,
    BTN_HOURS_48,
    BTN_HOURS_72,
    BTN_SCORE_0,
    BTN_SCORE_50,
    BTN_SCORE_100,
    BTN_SCORE_200,
    BTN_SCORE_500,
    BTN_ANON_YES,
    BTN_ANON_NO,
    build_campaign_anonymous_keyboard,
    build_post_submission_keyboard,
    build_post_campaign_created_keyboard,
)
from src.bot.ui import campaign_type_label, format_ttl_minutes, submission_status_meta, voting_type_label


# Create router
router = Router()


# Helper functions
def get_campaign_type_display(campaign_type: CampaignType) -> str:
    """Get human-readable campaign type."""
    return campaign_type_label(campaign_type)


def build_campaigns_list_keyboard(campaigns: list, prefix: str = "camp") -> InlineKeyboardBuilder:
    """Build inline keyboard for campaign selection."""
    builder = InlineKeyboardBuilder()
    for campaign in campaigns:
        builder.add(types.InlineKeyboardButton(
            text=f"📋 {campaign.title} ({get_campaign_type_display(campaign.type)})",
            callback_data=f"{prefix}_{campaign.id}"
        ))
    builder.adjust(1)
    return builder


def build_back_button() -> InlineKeyboardBuilder:
    """Build a back button."""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="back_to_menu"
    ))
    return builder


def _parse_choice(text: str | None, *, default: int | None = None, mapping: dict[str, int] | None = None) -> int | None:
    if not text:
        return None

    normalized = text.strip()
    if normalized.isdigit():
        return int(normalized)

    if mapping and normalized in mapping:
        return mapping[normalized]

    return None


async def _create_campaign_invites(
    campaign_id: int,
    organizer_id: int,
    session,
) -> tuple[str, str]:
    student_invite = await create_invite(
        role="student",
        created_by=organizer_id,
        campaign_id=campaign_id,
        session=session,
    )
    expert_invite = await create_invite(
        role="expert",
        created_by=organizer_id,
        campaign_id=campaign_id,
        session=session,
    )
    return student_invite.code, expert_invite.code


def _format_invite_block(bot_username: str, student_code: str, expert_code: str) -> str:
    student_link = f"https://t.me/{bot_username}?start={student_code}"
    expert_link = f"https://t.me/{bot_username}?start={expert_code}"
    return (
        "\n\n🔗 <b>Инвайты кампании:</b>\n"
        f"🎓 Студент: {student_link}\n"
        f"🧑‍🏫 Эксперт: {expert_link}"
    )


def _build_inline_keyboard(rows: list[list[tuple[str, str]]]):
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(
            *[
                types.InlineKeyboardButton(text=label, callback_data=data)
                for label, data in row
            ]
        )
    return builder.as_markup()


def _build_min_score_keyboard():
    return _build_inline_keyboard([
        [("0", "cam_min_0"), ("50", "cam_min_50"), ("100", "cam_min_100")],
        [("200", "cam_min_200")],
    ])


def _build_max_score_keyboard():
    return _build_inline_keyboard([
        [("100", "cam_max_100"), ("200", "cam_max_200"), ("500", "cam_max_500")],
    ])


def _build_ttl_keyboard():
    return _build_inline_keyboard([
        [("12 часов", "cam_ttl_720"), ("24 часа", "cam_ttl_1440")],
        [("48 часов", "cam_ttl_2880"), ("72 часа", "cam_ttl_4320")],
    ])


def _build_campaign_deadline_keyboard():
    return _build_inline_keyboard([
        [("1 день", "cam_deadline_days_1"), ("3 дня", "cam_deadline_days_3")],
        [("7 дней", "cam_deadline_days_7"), ("14 дней", "cam_deadline_days_14")],
    ])


def _campaign_deadline(campaign: Campaign) -> datetime | None:
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


def _campaign_deadline_from_days(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _format_time_left(deadline: datetime | None) -> str:
    if not deadline:
        return "не задан"
    now = datetime.now(timezone.utc)
    if deadline <= now:
        return "истек"
    delta = deadline - now
    total_hours = int(delta.total_seconds() // 3600)
    days, hours = divmod(total_hours, 24)
    if days > 0:
        return f"{days} д. {hours} ч."
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours} ч. {minutes} мин."


async def _campaign_stats(campaign_id: int, session) -> dict[str, float | int]:
    submissions_result = await session.execute(
        select(func.count(Submission.id)).where(Submission.campaign_id == campaign_id)
    )
    total_submissions = int(submissions_result.scalar_one() or 0)

    reviewed_result = await session.execute(
        select(func.count(Submission.id)).where(
            Submission.campaign_id == campaign_id,
            Submission.status == SubmissionStatus.REVIEWED,
        )
    )
    reviewed_submissions = int(reviewed_result.scalar_one() or 0)

    reviews_result = await session.execute(
        select(func.count(Review.id))
        .join(Submission, Review.submission_id == Submission.id)
        .where(Submission.campaign_id == campaign_id)
    )
    total_reviews = int(reviews_result.scalar_one() or 0)

    avg_result = await session.execute(
        select(func.avg(Review.score))
        .join(Submission, Review.submission_id == Submission.id)
        .where(Submission.campaign_id == campaign_id)
    )
    avg_score_raw = avg_result.scalar_one()
    avg_score = float(avg_score_raw) if avg_score_raw is not None else 0.0

    return {
        "total_submissions": total_submissions,
        "reviewed_submissions": reviewed_submissions,
        "total_reviews": total_reviews,
        "avg_score": avg_score,
    }


def _finish_campaigns_keyboard(campaigns: list[Campaign]) -> types.InlineKeyboardMarkup | None:
    active = [campaign for campaign in campaigns if campaign.is_active]
    if not active:
        return None

    builder = InlineKeyboardBuilder()
    for campaign in active:
        builder.row(
            types.InlineKeyboardButton(
                text=f"✅ Завершить: {campaign.title[:40]}",
                callback_data=f"finish_campaign_{campaign.id}",
            )
        )
    return builder.as_markup()


def _build_p2p_reviews_keyboard():
    return _build_inline_keyboard([
        [("1", "p2p_reviews_1"), ("2", "p2p_reviews_2"), ("3", "p2p_reviews_3")],
        [("5", "p2p_reviews_5")],
    ])


def _build_voting_type_keyboard():
    return _build_inline_keyboard([
        [("👍 Лайк", "vote_type_like")],
        [("⭐ Оценка", "vote_type_score")],
    ])


def _build_anonymous_keyboard():
    return _build_inline_keyboard([
        [(BTN_ANON_YES, "cam_anon_yes"), (BTN_ANON_NO, "cam_anon_no")],
    ])


# Organizer commands

@router.message(Command("create_campaign"))
async def cmd_create_campaign(message: types.Message, state: FSMContext):
    """Handle /create_campaign command - start campaign creation wizard."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /create_campaign")

    # Check if user is registered and is organizer
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )
            return

        if user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer(
                "❌ Только организаторы могут создавать кампании.\n"
                "Обратитесь к администратору для получения прав."
            )
            return

    # Start campaign creation wizard
    await message.answer(
        "🎯 <b>Создание новой кампании</b>\n\n"
        "Введите название кампании:",
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_title)


@router.message(F.text == BTN_CREATE_CAMPAIGN)
async def btn_create_campaign(message: types.Message, state: FSMContext):
    await cmd_create_campaign(message, state)


@router.message(StateFilter(CampaignCreationStates.waiting_for_title))
async def process_campaign_title(message: types.Message, state: FSMContext):
    """Process campaign title input."""
    title = message.text.strip()

    if len(title) < 3:
        await message.answer(
            "❌ Название слишком короткое (минимум 3 символа).\n"
            "Введите название кампании:"
        )
        return

    if len(title) > 500:
        await message.answer(
            "❌ Название слишком длинное (максимум 500 символов).\n"
            "Введите название кампании:"
        )
        return

    await state.update_data(title=title)
    logger.debug(f"Campaign title entered: {title}")

    # Show campaign types
    builder = InlineKeyboardBuilder()
    for ctype in CampaignType:
        builder.add(types.InlineKeyboardButton(
            text=get_campaign_type_display(ctype),
            callback_data=f"ctype_{ctype.value}"
        ))
    builder.adjust(1)

    await message.answer(
        "📋 <b>Выберите тип кампании:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_type)


@router.message(StateFilter(CampaignCreationStates.waiting_for_type))
async def process_campaign_type_message(message: types.Message, state: FSMContext):
    """Handle campaign type selection via text (fallback)."""
    await message.answer(
        "📋 <b>Выберите тип кампании, нажав на кнопку:</b>",
        parse_mode="HTML",
    )


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_type))
async def process_campaign_type_callback(callback: types.CallbackQuery, state: FSMContext):
    """Process campaign type selection via callback."""
    if not callback.data.startswith("ctype_"):
        await callback.answer()
        return

    try:
        campaign_type = CampaignType(callback.data.replace("ctype_", ""))
    except ValueError:
        await callback.answer("❌ Неизвестный тип кампании", show_alert=True)
        return

    await state.update_data(
        campaign_type=campaign_type.value,
        p2p_reviews_required=3,
        voting_type=None,
    )
    logger.debug(f"Campaign type selected: {campaign_type}")

    if campaign_type == CampaignType.P2P:
        await callback.message.answer(
            "👥 <b>Сколько работ должен проверить каждый участник?</b>\n"
            "Можно нажать кнопку под сообщением или ввести число вручную.",
            reply_markup=_build_p2p_reviews_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(CampaignCreationStates.waiting_for_p2p_reviews)
        await callback.answer()
        return

    if campaign_type == CampaignType.VOTING:
        await callback.message.answer(
            "🗳 <b>Выберите тип голосования:</b>",
            reply_markup=_build_voting_type_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(CampaignCreationStates.waiting_for_voting_type)
        await callback.answer()
        return

    await callback.message.answer(
        "📊 <b>Введите минимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_min_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_min_score)
    await callback.answer()


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_p2p_reviews))
async def process_p2p_reviews_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("p2p_reviews_"):
        await callback.answer()
        return

    value = callback.data.removeprefix("p2p_reviews_")
    if not value.isdigit():
        await callback.answer("Введите число", show_alert=True)
        return

    reviews_required = int(value)
    if reviews_required <= 0:
        await callback.answer("Число должно быть больше 0", show_alert=True)
        return

    await state.update_data(p2p_reviews_required=reviews_required)

    await callback.message.edit_text(
        "📊 <b>Введите минимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_min_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_min_score)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_p2p_reviews))
async def process_p2p_reviews_message(message: types.Message, state: FSMContext):
    reviews_required = _parse_choice(message.text)
    if reviews_required is None or reviews_required <= 0:
        await message.answer(
            "❌ Введите целое число больше 0 или выберите кнопку.",
            reply_markup=_build_p2p_reviews_keyboard(),
        )
        return

    await state.update_data(p2p_reviews_required=reviews_required)

    await message.answer(
        "📊 <b>Введите минимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_min_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_min_score)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_voting_type))
async def process_voting_type_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("vote_type_"):
        await callback.answer()
        return

    voting_type = callback.data.removeprefix("vote_type_")
    if voting_type not in {"like", "score"}:
        await callback.answer("Неизвестный тип", show_alert=True)
        return

    await state.update_data(voting_type=voting_type)

    if voting_type == "like":
        await state.update_data(min_score=1, max_score=1)
        await callback.message.edit_text(
            "⏱ <b>Введите время голосования (в минутах):</b>\n"
            "Можно нажать кнопку под сообщением или ввести число минут вручную.",
            reply_markup=_build_ttl_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(CampaignCreationStates.waiting_for_ttl)
        await callback.answer()
        return

    await callback.message.edit_text(
        "📊 <b>Введите минимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_min_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_min_score)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_voting_type))
async def process_voting_type_message(message: types.Message):
    await message.answer(
        "🗳 <b>Выберите тип голосования кнопкой ниже:</b>",
        reply_markup=_build_voting_type_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_min_score))
async def process_campaign_min_score_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("cam_min_"):
        await callback.answer()
        return

    value = callback.data.removeprefix("cam_min_")
    if not value.isdigit():
        await callback.answer("Некорректное значение", show_alert=True)
        return
    min_score = int(value)
    await state.update_data(min_score=min_score)
    logger.debug(f"Min score selected: {min_score}")

    await callback.message.edit_text(
        "📊 <b>Введите максимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_max_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_max_score)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_min_score))
async def process_min_score(message: types.Message, state: FSMContext):
    """Process minimum score input."""
    min_score = _parse_choice(
        message.text,
        mapping={BTN_SCORE_0: 0, BTN_SCORE_50: 50, BTN_SCORE_100: 100, BTN_SCORE_200: 200},
    )
    if min_score is None or min_score < 0:
        await message.answer(
            "❌ Введите целое неотрицательное число или выберите кнопку.",
            reply_markup=_build_min_score_keyboard(),
        )
        return

    await state.update_data(min_score=min_score)
    logger.debug(f"Min score entered: {min_score}")

    await message.answer(
        "📊 <b>Введите максимальный балл:</b>\n"
        "Можно нажать кнопку под сообщением или ввести число вручную.",
        reply_markup=_build_max_score_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_max_score)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_max_score))
async def process_campaign_max_score_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("cam_max_"):
        await callback.answer()
        return

    value = callback.data.removeprefix("cam_max_")
    if not value.isdigit():
        await callback.answer("Некорректное значение", show_alert=True)
        return
    max_score = int(value)

    data = await state.get_data()
    min_score = data.get("min_score", 0)
    if max_score < min_score:
        await callback.answer(
            f"Максимальный балл должен быть >= минимального ({min_score}).",
            show_alert=True,
        )
        return

    await state.update_data(max_score=max_score)
    logger.debug(f"Max score selected: {max_score}")

    await callback.message.edit_text(
        "⏱ <b>Введите время на проверку (в минутах):</b>\n"
        "Можно нажать кнопку под сообщением или ввести число минут вручную.",
        reply_markup=_build_ttl_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_ttl)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_max_score))
async def process_max_score(message: types.Message, state: FSMContext):
    """Process maximum score input."""
    max_score = _parse_choice(
        message.text,
        mapping={BTN_SCORE_100: 100, BTN_SCORE_200: 200, BTN_SCORE_500: 500},
    )
    if max_score is None or max_score < 0:
        await message.answer(
            "❌ Введите целое неотрицательное число или выберите кнопку.",
            reply_markup=_build_max_score_keyboard(),
        )
        return

    data = await state.get_data()
    min_score = data.get("min_score", 0)

    if max_score < min_score:
        await message.answer(
            f"❌ Максимальный балл должен быть >= минимального ({min_score})."
        )
        return

    await state.update_data(max_score=max_score)
    logger.debug(f"Max score entered: {max_score}")

    await message.answer(
        "⏱ <b>Введите время на проверку (в минутах):</b>\n"
        "Можно нажать кнопку под сообщением или ввести число минут вручную.",
        reply_markup=_build_ttl_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_ttl)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_ttl))
async def process_campaign_ttl_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("cam_ttl_"):
        await callback.answer()
        return

    value = callback.data.removeprefix("cam_ttl_")
    if not value.isdigit():
        await callback.answer("Некорректное значение", show_alert=True)
        return
    ttl_minutes = int(value)
    await state.update_data(ttl_minutes=ttl_minutes)
    logger.debug(f"TTL selected: {ttl_minutes}")

    await callback.message.edit_text(
        "📅 <b>Через сколько дней закрыть сдачу работ?</b>\n"
        "Можно выбрать кнопку или ввести число дней вручную.",
        reply_markup=_build_campaign_deadline_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_campaign_deadline_days)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_ttl))
async def process_ttl(message: types.Message, state: FSMContext):
    """Process TTL input."""
    ttl_minutes = _parse_choice(
        message.text,
        mapping={BTN_HOURS_12: 720, BTN_HOURS_24: 1440, BTN_HOURS_48: 2880, BTN_HOURS_72: 4320},
    )
    if ttl_minutes is None or ttl_minutes <= 0:
        await message.answer(
            "❌ Введите целое положительное число или выберите кнопку.",
            reply_markup=_build_ttl_keyboard(),
        )
        return

    await state.update_data(ttl_minutes=ttl_minutes)
    logger.debug(f"TTL entered: {ttl_minutes}")

    await message.answer(
        "📅 <b>Через сколько дней закрыть сдачу работ?</b>\n"
        "Можно выбрать кнопку или ввести число дней вручную.",
        reply_markup=_build_campaign_deadline_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_campaign_deadline_days)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_campaign_deadline_days))
async def process_campaign_deadline_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("cam_deadline_days_"):
        await callback.answer()
        return

    value = callback.data.removeprefix("cam_deadline_days_")
    if not value.isdigit() or int(value) <= 0:
        await callback.answer("Введите число дней > 0", show_alert=True)
        return

    days = int(value)
    await state.update_data(campaign_deadline_days=days)
    logger.debug(f"Campaign deadline days selected: {days}")

    await callback.message.edit_text(
        "🔒 <b>Сделать рецензии анонимными?</b>\n"
        "Если выбрать «Да», автор не увидит имя проверяющего.",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_anonymous)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_campaign_deadline_days))
async def process_campaign_deadline_message(message: types.Message, state: FSMContext):
    days = _parse_choice(message.text)
    if days is None or days <= 0:
        await message.answer(
            "❌ Введите целое число дней больше 0 или выберите кнопку.",
            reply_markup=_build_campaign_deadline_keyboard(),
        )
        return

    await state.update_data(campaign_deadline_days=days)
    logger.debug(f"Campaign deadline days entered: {days}")

    await message.answer(
        "🔒 <b>Сделать рецензии анонимными?</b>\n"
        "Если выбрать «Да», автор не увидит имя проверяющего.",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_anonymous)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_anonymous))
async def process_campaign_anonymous_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("cam_anon_"):
        await callback.answer()
        return

    is_anon = callback.data == "cam_anon_yes"
    await state.update_data(is_expert_anon=is_anon)

    data = await state.get_data()
    tg_id = callback.from_user.id
    campaign_deadline_days = int(data.get("campaign_deadline_days", 7))
    campaign_deadline_at = _campaign_deadline_from_days(campaign_deadline_days)

    async with session_scope() as session:
        try:
            campaign = await create_campaign(
                title=data["title"],
                campaign_type=CampaignType(data["campaign_type"]),
                min_score=data["min_score"],
                max_score=data["max_score"],
                ttl_minutes=data["ttl_minutes"],
                campaign_deadline_at=campaign_deadline_at,
                is_expert_anon=is_anon,
                p2p_reviews_required=data.get("p2p_reviews_required", 3),
                voting_type=data.get("voting_type"),
                organizer_id=tg_id,
                session=session,
            )

            bot_username = (await callback.bot.get_me()).username
            student_code, expert_code = await _create_campaign_invites(
                campaign_id=campaign.id,
                organizer_id=tg_id,
                session=session,
            )

            extra_lines = ""
            if campaign.type == CampaignType.P2P:
                extra_lines += f"\n👥 Проверок на участника: {campaign.p2p_reviews_required}"
            if campaign.type == CampaignType.VOTING:
                extra_lines += f"\n🗳 Тип голосования: {voting_type_label(campaign.voting_type)}"

            score_line = f"📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            if campaign.type == CampaignType.VOTING and campaign.voting_type == "like":
                score_line = "📈 Голос: 👍 Лайк\n"

            await state.clear()
            await callback.message.edit_text(
                "✅ <b>Кампания создана!</b>\n\n"
                f"📋 <b>{campaign.title}</b>\n"
                f"📊 Тип: {get_campaign_type_display(CampaignType(data['campaign_type']))}\n"
                f"{score_line}"
                f"⏱ Дедлайн проверки эксперта: {format_ttl_minutes(campaign.ttl_minutes)}\n"
                f"📅 Дедлайн сдачи работ: {campaign_deadline_at.astimezone().strftime('%d.%m.%Y %H:%M')}\n"
                f"🔒 Анонимность: {'Да' if is_anon else 'Нет'}"
                f"{extra_lines}"
                f"{_format_invite_block(bot_username, student_code, expert_code)}",
                parse_mode="HTML",
            )
            logger.info(f"Campaign created: id={campaign.id}, title={campaign.title}")
        except Exception as e:
            logger.error(f"Failed to create campaign: {e}")
            await callback.message.edit_text("❌ Произошла ошибка при создании кампании.")

    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_anonymous))
async def process_anonymous_message(message: types.Message, state: FSMContext):
    """Process anonymous selection from reply keyboard."""
    if message.text not in (BTN_ANON_YES, BTN_ANON_NO):
        await message.answer(
            "❌ Выберите вариант кнопкой.",
            reply_markup=_build_anonymous_keyboard(),
        )
        return

    is_anon = message.text == BTN_ANON_YES
    await state.update_data(is_expert_anon=is_anon)

    data = await state.get_data()
    tg_id = message.from_user.id
    campaign_deadline_days = int(data.get("campaign_deadline_days", 7))
    campaign_deadline_at = _campaign_deadline_from_days(campaign_deadline_days)

    async with session_scope() as session:
        try:
            campaign = await create_campaign(
                title=data["title"],
                campaign_type=CampaignType(data["campaign_type"]),
                min_score=data["min_score"],
                max_score=data["max_score"],
                ttl_minutes=data["ttl_minutes"],
                campaign_deadline_at=campaign_deadline_at,
                is_expert_anon=is_anon,
                p2p_reviews_required=data.get("p2p_reviews_required", 3),
                voting_type=data.get("voting_type"),
                organizer_id=tg_id,
                session=session,
            )

            bot_username = (await message.bot.get_me()).username
            student_code, expert_code = await _create_campaign_invites(
                campaign_id=campaign.id,
                organizer_id=tg_id,
                session=session,
            )
            extra_lines = ""
            if campaign.type == CampaignType.P2P:
                extra_lines += f"\n👥 Проверок на участника: {campaign.p2p_reviews_required}"
            if campaign.type == CampaignType.VOTING:
                extra_lines += f"\n🗳 Тип голосования: {voting_type_label(campaign.voting_type)}"

            score_line = f"📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            if campaign.type == CampaignType.VOTING and campaign.voting_type == "like":
                score_line = "📈 Голос: 👍 Лайк\n"
            await state.clear()
            await message.answer(
                "✅ <b>Кампания создана!</b>\n\n"
                f"📋 <b>{campaign.title}</b>\n"
                f"📊 Тип: {get_campaign_type_display(CampaignType(data['campaign_type']))}\n"
                f"{score_line}"
                f"⏱ Дедлайн проверки эксперта: {format_ttl_minutes(campaign.ttl_minutes)}\n"
                f"📅 Дедлайн сдачи работ: {campaign_deadline_at.astimezone().strftime('%d.%m.%Y %H:%M')}\n"
                f"🔒 Анонимность: {'Да' if is_anon else 'Нет'}"
                f"{extra_lines}"
                f"{_format_invite_block(bot_username, student_code, expert_code)}",
                parse_mode="HTML",
                reply_markup=build_post_campaign_created_keyboard(),
            )
            logger.info(f"Campaign created: id={campaign.id}, title={campaign.title}")
        except Exception as e:
            logger.error(f"Failed to create campaign: {e}")
            await message.answer(
                "❌ Произошла ошибка при создании кампании.",
                reply_markup=build_campaign_anonymous_keyboard(),
            )


# Campaign listing commands

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    """Handle /campaigns command - list active campaigns."""
    logger.info(f"User {message.from_user.id} triggered /campaigns")

    async with session_scope() as session:
        campaigns = await get_active_campaigns(session)

        if not campaigns:
            await message.answer(
                "📭 <b>Нет активных кампаний.</b>",
                parse_mode="HTML",
            )
            return

        text = "📋 <b>Активные кампании:</b>\n\n"
        for i, campaign in enumerate(campaigns, 1):
            deadline = _campaign_deadline(campaign)
            deadline_text = deadline.strftime('%d.%m.%Y %H:%M') if deadline else "не задан"
            text += f"{i}. <b>{campaign.title}</b>\n"
            text += f"   📊 Тип: {get_campaign_type_display(campaign.type)}\n"
            if campaign.type == CampaignType.VOTING and campaign.voting_type == "like":
                text += "   📈 Голос: 👍 Лайк\n"
            else:
                text += f"   📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            if campaign.type == CampaignType.P2P:
                text += f"   👥 Проверок на участника: {campaign.p2p_reviews_required}\n"
            if campaign.type == CampaignType.VOTING:
                text += f"   🗳 Тип голосования: {voting_type_label(campaign.voting_type)}\n"
            text += f"   ⏱ Дедлайн проверки эксперта: {format_ttl_minutes(campaign.ttl_minutes)}\n"
            text += f"   📅 Дедлайн сдачи: {deadline_text} ({_format_time_left(deadline)})\n\n"

        await message.answer(text, parse_mode="HTML")


@router.message(Command("my_campaigns"))
async def cmd_my_campaigns(message: types.Message):
    """Handle /my_campaigns command - list campaigns by this organizer."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /my_campaigns")

    # Check if user is registered and is organizer
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )
            return

        if user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer(
                "❌ Только организаторы могут просматривать свои кампании."
            )
            return

        campaigns = await get_campaigns_by_organizer(tg_id, session)

        if not campaigns:
            await message.answer(
                "📭 <b>У вас пока нет кампаний.</b>\n"
                "Используйте /create_campaign для создания.",
                parse_mode="HTML",
            )
            return

        submission_counts = {}
        campaign_ids = [campaign.id for campaign in campaigns]
        if campaign_ids:
            result = await session.execute(
                select(Submission.campaign_id, func.count(Submission.id))
                .where(Submission.campaign_id.in_(campaign_ids))
                .group_by(Submission.campaign_id)
            )
            submission_counts = {
                campaign_id: count for campaign_id, count in result.all()
            }

        text = "📋 <b>Ваши кампании:</b>\n\n"
        completed_campaign_stats: list[str] = []
        for i, campaign in enumerate(campaigns, 1):
            status = "🟢 Активна" if campaign.is_active else "🔴 Завершена"
            deadline = _campaign_deadline(campaign)
            deadline_text = deadline.strftime('%d.%m.%Y %H:%M') if deadline else "не задан"
            text += f"{i}. <b>{campaign.title}</b> {status}\n"
            text += f"   📊 Тип: {get_campaign_type_display(campaign.type)}\n"
            if campaign.type == CampaignType.VOTING and campaign.voting_type == "like":
                text += "   📈 Голос: 👍 Лайк\n"
            else:
                text += f"   📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            if campaign.type == CampaignType.P2P:
                text += f"   👥 Проверок на участника: {campaign.p2p_reviews_required}\n"
            if campaign.type == CampaignType.VOTING:
                text += f"   🗳 Тип голосования: {voting_type_label(campaign.voting_type)}\n"
            text += f"   ⏱ Дедлайн проверки эксперта: {format_ttl_minutes(campaign.ttl_minutes)}\n"
            text += f"   📅 Дедлайн сдачи: {deadline_text} ({_format_time_left(deadline)})\n"
            text += f"   📝 Сдано: {submission_counts.get(campaign.id, 0)} работ\n\n"

            if not campaign.is_active:
                stats = await _campaign_stats(campaign.id, session)
                completed_campaign_stats.append(
                    f"• <b>{campaign.title}</b>: "
                    f"работ {stats['total_submissions']}, "
                    f"проверено {stats['reviewed_submissions']}, "
                    f"средний балл {stats['avg_score']:.1f}"
                )

        if completed_campaign_stats:
            text += "📌 <b>Статистика завершённых кампаний:</b>\n"
            text += "\n".join(completed_campaign_stats)

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=_finish_campaigns_keyboard(campaigns),
        )


@router.callback_query(F.data == "menu_campaigns")
async def menu_campaigns(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_campaigns(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu_my_submissions")
async def menu_my_submissions(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_my_submissions(callback.message)
    await callback.answer()


@router.callback_query(F.data == "org_my_campaigns")
async def menu_org_my_campaigns(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_my_campaigns(callback.message)
    await callback.answer()


@router.callback_query(F.data == "org_create_campaign")
async def menu_org_create_campaign(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_create_campaign(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("finish_campaign_"))
async def finish_campaign(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return

    campaign_id_text = callback.data.removeprefix("finish_campaign_")
    if not campaign_id_text.isdigit():
        await callback.answer("Некорректный ID кампании", show_alert=True)
        return

    campaign_id = int(campaign_id_text)
    tg_id = callback.from_user.id

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("Доступно только организаторам", show_alert=True)
            return

        campaign = await get_campaign(campaign_id, session)
        if not campaign:
            await callback.answer("Кампания не найдена", show_alert=True)
            return

        campaign_title = campaign.title

        if not campaign.is_active:
            stats = await _campaign_stats(campaign_id, session)
            await callback.answer("Кампания уже завершена", show_alert=True)
            await callback.message.answer(
                "ℹ️ <b>Кампания уже завершена.</b>\n\n"
                f"📋 {campaign_title}\n"
                f"📝 Работ: <b>{stats['total_submissions']}</b>\n"
                f"✅ Проверено работ: <b>{stats['reviewed_submissions']}</b>\n"
                f"💬 Всего рецензий: <b>{stats['total_reviews']}</b>\n"
                f"⭐ Средний балл: <b>{stats['avg_score']:.1f}</b>",
                parse_mode="HTML",
            )
            return

        campaign.is_active = False
        await session.flush()
        stats = await _campaign_stats(campaign_id, session)

    await callback.answer("Кампания завершена")
    await callback.message.answer(
        "✅ <b>Кампания завершена организатором.</b>\n\n"
        f"📋 {campaign_title}\n"
        f"📝 Работ: <b>{stats['total_submissions']}</b>\n"
        f"✅ Проверено работ: <b>{stats['reviewed_submissions']}</b>\n"
        f"💬 Всего рецензий: <b>{stats['total_reviews']}</b>\n"
        f"⭐ Средний балл: <b>{stats['avg_score']:.1f}</b>",
        parse_mode="HTML",
    )


# Reply-keyboard handlers (buttons under input)
@router.message(F.text == BTN_CAMPAIGNS)
async def btn_campaigns(message: types.Message):
    await cmd_campaigns(message)


@router.message(F.text == BTN_SUBMIT)
async def btn_submit(message: types.Message, state: FSMContext):
    await cmd_submit(message, state)


@router.message(F.text == BTN_MY_SUBMISSIONS)
async def btn_my_submissions(message: types.Message):
    await cmd_my_submissions(message)


# Student commands

@router.message(Command("submit"))
async def cmd_submit(message: types.Message, state: FSMContext):
    """Handle /submit command - start file submission."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /submit")

    # Check if user is registered
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )
            return

        if user.role != UserRole.STUDENT:
            await message.answer(
                "❌ Сдача работ доступна только студентам."
            )
            return

        if user.role == UserRole.STUDENT and (not user.registered_by_code or user.invite_role != "student"):
            await message.answer(
                "❌ Для сдачи работ нужен код доступа. "
                "Откройте ссылку приглашения"
            )
            return

        # Get active campaigns
        campaigns = await get_active_campaigns(session)

        if not campaigns:
            await message.answer(
                "📭 <b>Нет активных кампаний для сдачи.</b>",
                parse_mode="HTML",
            )
            return

    # Show campaign selection
    builder = build_campaigns_list_keyboard(campaigns, "sel_camp")

    await message.answer(
        "📋 <b>Выберите кампанию для сдачи работы:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(SubmissionStates.waiting_for_campaign)


@router.callback_query(StateFilter(SubmissionStates.waiting_for_campaign))
async def process_campaign_selection(callback: types.CallbackQuery, state: FSMContext):
    """Process campaign selection for submission."""
    if callback.data == "back_to_menu":
        await state.clear()
        await callback.message.edit_text("❌ Отменено.")
        await callback.answer()
        return

    if not callback.data.startswith("sel_camp_"):
        await callback.answer()
        return

    try:
        campaign_id = int(callback.data.replace("sel_camp_", ""))
    except ValueError:
        await callback.answer("❌ Ошибка выбора кампании", show_alert=True)
        return

    # Verify campaign exists
    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)

        if not campaign:
            await callback.answer("❌ Кампания не найдена", show_alert=True)
            return

        if not campaign.is_active:
            await callback.answer("❌ Кампания неактивна", show_alert=True)
            return

    await state.update_data(campaign_id=campaign_id)

    await callback.message.edit_text(
        "📎 <b>Отправьте файл для проверки:</b>\n\n"
        f"📋 Кампания: <b>{campaign.title}</b>\n"
        f"📄 Форматы: .pdf, .docx, .doc, .txt, .jpg, .png\n"
        f"📦 Макс. размер: 50 МБ",
        parse_mode="HTML",
    )
    await state.set_state(SubmissionStates.waiting_for_file)
    await callback.answer()


@router.message(StateFilter(SubmissionStates.waiting_for_file))
async def process_submission_file(message: types.Message, state: FSMContext):
    """Process uploaded file as submission."""
    from src.bot.services.submission_service import (
        create_submission,
        check_user_has_submission,
    )
    

    tg_id = message.from_user.id

    # Check if message has document
    if not message.document:
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="back_to_menu"
        ))
        await message.answer(
            "❌ Пожалуйста, отправьте файл (документ).",
            reply_markup=builder.as_markup(),
        )
        return

    document = message.document
    file_name = document.file_name or "unknown"
    file_size = document.file_size or 0

    # Validate file
    from src.bot.utils.validators import validate_file

    is_valid, error_msg = validate_file(file_name, file_size)
    if not is_valid:
        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="back_to_menu"
        ))
        await message.answer(error_msg, reply_markup=builder.as_markup())
        return

    # Get campaign from state
    data = await state.get_data()
    campaign_id = data.get("campaign_id")

    if not campaign_id:
        await message.answer("❌ Ошибка: кампания не выбрана.")
        await state.clear()
        return

    # Create submission
    async with session_scope() as session:
        try:
            # Check if user already has submission
            has_submission = await check_user_has_submission(
                campaign_id, tg_id, session
            )
            if has_submission:
                await message.answer(
                    "❌ Вы уже сдавали работу в эту кампанию.\n"
                    "Можно сдать только одну работу на кампанию."
                )
                return

            submission = await create_submission(
                campaign_id=campaign_id,
                author_id=tg_id,
                file_id=document.file_id,
                session=session,
            )

            logger.info(
                f"Submission created: id={submission.id}, "
                f"campaign={campaign_id}, author={tg_id}"
            )

            campaign = await get_campaign(campaign_id, session)
            await message.answer(
                "✅ <b>Работа успешно загружена!</b>\n\n"
                f"📋 Кампания: <b>{campaign.title if campaign else f'Кампания #{campaign_id}'}</b>\n"
                f"📄 Файл: <b>{file_name}</b>\n"
                f"🆔 Работа: <code>{submission.id}</code>\n"
                f"📌 Статус: 🟡 <b>Ожидает проверки</b>\n"
                "Что дальше: дождитесь, когда работу возьмут на проверку.",
                parse_mode="HTML",
            )
            
            # Get user role for keyboard
            from src.db.models import UserRole
            from src.bot.services.user_service import get_user
            user = await get_user(tg_id=tg_id, session=session)
            if user:
                await message.answer(
                    "Главное меню:",
                    reply_markup=get_keyboard_for_role(user.role),
                )

        except Exception as e:
            logger.error(f"Failed to create submission: {e}")
            await message.answer(
                "❌ Произошла ошибка при сохранении работы."
            )

    await state.clear()


@router.message(Command("my_submissions"))
async def cmd_my_submissions(message: types.Message):
    """Handle /my_submissions command - view user's submissions."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /my_submissions")

    async with session_scope() as session:
        from src.bot.services.submission_service import get_user_submissions
        from src.bot.services.campaign_service import get_campaign

        submissions = await get_user_submissions(tg_id, session)

        if not submissions:
            await message.answer(
                "📭 <b>У вас пока нет загруженных работ.</b>\n"
                "Используйте /submit для загрузки.",
                parse_mode="HTML",
            )
            return

        text = "📎 <b>Ваши работы:</b>\n\n"
        for i, submission in enumerate(submissions, 1):
            campaign = await get_campaign(submission.campaign_id, session)
            campaign_title = campaign.title if campaign else f"Кампания #{submission.campaign_id}"

            status_emoji = {
                "uploaded": "🟡",
                "in_review": "🔵",
                "reviewed": "✅",
                "rejected": "❌",
            }.get(submission.status.value, "⚪")

            text += f"{i}. <b>{campaign_title}</b>\n"
            _, status_label, _ = submission_status_meta(submission.status)
            text += f"   📊 Статус: {status_emoji} {status_label}\n"
            text += f"   📝 ID: <code>{submission.id}</code>\n"
            text += f"   📅 Дата: {submission.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"

        await message.answer(text, parse_mode="HTML")

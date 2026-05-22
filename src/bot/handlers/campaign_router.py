"""Campaign management router for organizers."""
from datetime import datetime, timedelta, timezone
from html import escape
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select

from src.db.engine import session_scope
from src.db.models import (
    UserRole,
    CampaignType,
    Campaign,
    Submission,
    Review,
    SubmissionStatus,
    InviteCode,
    SubmissionFormat,
)
from src.bot.services.user_service import (
    get_user,
    get_campaign_accesses,
    has_campaign_access,
)
from src.bot.services.campaign_service import (
    CampaignService,
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
    BTN_VIEW_RESULTS,
    BTN_EXPORT,
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
    build_submission_confirmation_keyboard,
    build_finish_campaign_confirmation_keyboard,
    get_keyboard_for_user,
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
    builder.row(
        types.InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="back_to_menu",
        )
    )
    return builder.as_markup()


def _submission_format_label(submission_format: SubmissionFormat) -> str:
    labels = {
        SubmissionFormat.DOCUMENT: "Документ",
        SubmissionFormat.TEXT: "Текст",
        SubmissionFormat.PHOTO: "Фото",
        SubmissionFormat.PHOTO_DOCUMENT: "Фото документом",
        SubmissionFormat.LINK: "Ссылка",
    }
    return labels.get(submission_format, submission_format.value)

def _parse_criteria_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]

def _criteria_summary_text(criteria: list[str]) -> str:
    if not criteria:
        return "не заданы"
    if len(criteria) <= 2:
        return ", ".join(criteria)
    return f"{criteria[0]}, {criteria[1]} и ещё {len(criteria) - 2}"

def _criteria_count_line(criteria: list[str]) -> str:
    if not criteria:
        return "\n🧾 Критерии: не заданы"
    return f"\n🧾 Критерии ({len(criteria)}): {_criteria_summary_text(criteria)}"

def _build_submission_format_keyboard():
    return _build_inline_keyboard([
        [("📄 Документ", "subfmt_document"), ("📝 Текст", "subfmt_text")],
        [("🖼 Фото", "subfmt_photo"), ("🖼📎 Фото документом", "subfmt_photo_document")],
        [("🔗 Ссылка", "subfmt_link")],
    ])

def _build_criteria_skip_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="⏭️ Пропустить",
            callback_data="campaign_skip_criteria",
        )
    )
    return builder.as_markup()

def _submission_prompt_text(campaign: Campaign) -> str:
    prompts = {
        SubmissionFormat.DOCUMENT: (
            "📎 <b>Отправьте документ для проверки:</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "📄 Разрешённый формат: документ\n"
            "📦 Макс. размер: 50 МБ"
        ),
        SubmissionFormat.TEXT: (
            "📝 <b>Отправьте текст работы одним сообщением:</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "📌 Сообщение не должно быть пустым"
        ),
        SubmissionFormat.PHOTO: (
            "🖼 <b>Отправьте фото для проверки:</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "📌 Принимается Telegram photo"
        ),
        SubmissionFormat.PHOTO_DOCUMENT: (
            "🖼📎 <b>Отправьте фото как документ:</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "📄 Разрешённые расширения: .jpg, .jpeg, .png\n"
            "📦 Макс. размер: 50 МБ"
        ),
        SubmissionFormat.LINK: (
            "🔗 <b>Отправьте ссылку на работу:</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "📌 Поддерживается любой корректный URL"
        ),
    }
    return prompts.get(campaign.submission_format, prompts[SubmissionFormat.DOCUMENT])

def _submission_success_details(submission: Submission) -> str:
    if submission.submission_type == SubmissionFormat.TEXT:
        preview = (submission.text_content or "").strip()
        if len(preview) > 160:
            preview = f"{preview[:157]}..."
        return f"📝 Формат: <b>Текст</b>\n📄 Содержимое: <blockquote>{preview}</blockquote>"

    if submission.submission_type == SubmissionFormat.LINK:
        return (
            "🔗 Формат: <b>Ссылка</b>\n"
            f"🌐 URL: <code>{submission.external_url or '-'}</code>"
        )

    if submission.submission_type == SubmissionFormat.PHOTO:
        return "🖼 Формат: <b>Фото</b>"

    if submission.submission_type == SubmissionFormat.PHOTO_DOCUMENT:
        return (
            "🖼📎 Формат: <b>Фото документом</b>\n"
            f"📄 Файл: <b>{submission.file_name or 'image'}</b>"
        )

    return (
        "📄 Формат: <b>Документ</b>\n"
        f"📄 Файл: <b>{submission.file_name or 'document'}</b>"
    )

def _submission_error_text(campaign: Campaign) -> str:
    errors = {
        SubmissionFormat.DOCUMENT: "❌ Пожалуйста, отправьте документ.",
        SubmissionFormat.TEXT: "❌ Пожалуйста, отправьте текст одним сообщением.",
        SubmissionFormat.PHOTO: "❌ Пожалуйста, отправьте фото.",
        SubmissionFormat.PHOTO_DOCUMENT: "❌ Пожалуйста, отправьте изображение как документ.",
        SubmissionFormat.LINK: "❌ Пожалуйста, отправьте корректную ссылку.",
    }
    return errors.get(campaign.submission_format, "❌ Отправьте работу в требуемом формате.")

def _submission_preview_details(campaign: Campaign, payload: dict) -> str:
    submission_type = payload.get("submission_type", campaign.submission_format)

    if submission_type == SubmissionFormat.TEXT:
        preview = (payload.get("text_content") or "").strip()
        if len(preview) > 300:
            preview = f"{preview[:297]}..."
        return (
            "📝 Формат: <b>Текст</b>\n"
            f"📄 Содержимое: <blockquote>{escape(preview)}</blockquote>"
        )

    if submission_type == SubmissionFormat.LINK:
        return (
            "🔗 Формат: <b>Ссылка</b>\n"
            f"🌐 URL: <code>{escape(payload.get('external_url') or '-')}</code>"
        )

    if submission_type == SubmissionFormat.PHOTO:
        return "🖼 Формат: <b>Фото</b>"

    if submission_type == SubmissionFormat.PHOTO_DOCUMENT:
        file_name = escape(payload.get("file_name") or "image")
        return f"🖼📎 Формат: <b>Фото документом</b>\n📄 Файл: <b>{file_name}</b>"

    file_name = escape(payload.get("file_name") or "document")
    return f"📄 Формат: <b>Документ</b>\n📄 Файл: <b>{file_name}</b>"

def _submission_confirmation_text(campaign: Campaign, payload: dict) -> str:
    return (
        "📤 <b>Проверьте работу перед отправкой</b>\n\n"
        f"📋 Кампания: <b>{escape(campaign.title)}</b>\n"
        f"{_submission_preview_details(campaign, payload)}\n\n"
        "Если всё верно, подтвердите отправку."
    )

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


def _finish_campaigns_keyboard(campaigns: list[Campaign]) -> types.InlineKeyboardMarkup:
    active = [campaign for campaign in campaigns if campaign.is_active]

    builder = InlineKeyboardBuilder()
    for campaign in active:
        builder.row(
            types.InlineKeyboardButton(
                text=f"✅ Завершить: {campaign.title[:40]}",
                callback_data=f"finish_campaign_{campaign.id}",
            )
        )

    builder.row(
        types.InlineKeyboardButton(
            text=BTN_VIEW_RESULTS,
            callback_data="org_menu_view_results",
        ),
        types.InlineKeyboardButton(
            text=BTN_EXPORT,
            callback_data="org_menu_export",
        ),
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
    builder.add(types.InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="back_to_menu",
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


@router.callback_query(
    StateFilter(
        CampaignCreationStates.waiting_for_type,
        CampaignCreationStates.waiting_for_p2p_reviews,
        CampaignCreationStates.waiting_for_voting_type,
        CampaignCreationStates.waiting_for_min_score,
        CampaignCreationStates.waiting_for_max_score,
        CampaignCreationStates.waiting_for_ttl,
        CampaignCreationStates.waiting_for_campaign_deadline_days,
        CampaignCreationStates.waiting_for_submission_format,
        CampaignCreationStates.waiting_for_allow_resubmission_before_review,
        CampaignCreationStates.waiting_for_allow_resubmission_after_review,
        CampaignCreationStates.waiting_for_anonymous,
    ),
    F.data == "back_to_menu",
)
async def cancel_campaign_creation(callback: types.CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer()
        return

    await state.clear()
    await callback.message.edit_text("❌ Создание кампании отменено.")
    await callback.answer()

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
        "📥 <b>Выберите формат сдачи работы:</b>",
        reply_markup=_build_submission_format_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_submission_format)
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
        "📥 <b>Выберите формат сдачи работы:</b>",
        reply_markup=_build_submission_format_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_submission_format)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_submission_format))
async def process_submission_format_callback(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data or not callback.data.startswith("subfmt_"):
        await callback.answer()
        return

    format_value = callback.data.removeprefix("subfmt_")
    try:
        submission_format = SubmissionFormat(format_value)
    except ValueError:
        await callback.answer("❌ Неизвестный формат сдачи", show_alert=True)
        return

    await state.update_data(submission_format=submission_format.value)

    await callback.message.edit_text(
        "♻️ <b>Разрешить замену работы до проверки?</b>\n"
        "Если выбрать «Да», студент сможет заменить отправленную работу, пока её ещё не проверили.",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_allow_resubmission_before_review)
    await callback.answer()

@router.message(StateFilter(CampaignCreationStates.waiting_for_submission_format))
async def process_submission_format_message(message: types.Message):
    await message.answer(
        "📥 <b>Выберите формат сдачи кнопкой ниже:</b>",
        reply_markup=_build_submission_format_keyboard(),
        parse_mode="HTML",
    )

@router.callback_query(
    StateFilter(CampaignCreationStates.waiting_for_allow_resubmission_before_review)
)
async def process_allow_resubmission_before_review_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    if not callback.data or not callback.data.startswith("cam_anon_"):
        await callback.answer()
        return

    allow_resubmission_before_review = callback.data == "cam_anon_yes"
    await state.update_data(
        allow_resubmission_before_review=allow_resubmission_before_review
    )

    await callback.message.edit_text(
        "🔁 <b>Разрешить пересдачу после проверки?</b>\n"
        "Если выбрать «Да», студент сможет отправить новую работу после завершения проверки предыдущей.",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_allow_resubmission_after_review)
    await callback.answer()

@router.message(
    StateFilter(CampaignCreationStates.waiting_for_allow_resubmission_before_review)
)
async def process_allow_resubmission_before_review_message(message: types.Message):
    await message.answer(
        "♻️ <b>Выберите вариант кнопкой ниже:</b>",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )

@router.callback_query(
    StateFilter(CampaignCreationStates.waiting_for_allow_resubmission_after_review)
)
async def process_allow_resubmission_after_review_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
):
    if not callback.data or not callback.data.startswith("cam_anon_"):
        await callback.answer()
        return

    allow_resubmission_after_review = callback.data == "cam_anon_yes"
    await state.update_data(
        allow_resubmission_after_review=allow_resubmission_after_review
    )

    await callback.message.answer(
        "🧾 <b>Введите критерии оценки (необязательно):</b>\n"
        "Один критерий — одна строка.\n\n"
        "Пример:\n"
        "Оформление\n"
        "Аргументация\n"
        "Полнота ответа",
        parse_mode="HTML",
        reply_markup=_build_criteria_skip_keyboard(),
    )
    await state.set_state(CampaignCreationStates.waiting_for_criteria)
    await callback.answer()

@router.message(
    StateFilter(CampaignCreationStates.waiting_for_allow_resubmission_after_review)
)
async def process_allow_resubmission_after_review_message(message: types.Message):
    await message.answer(
        "🔁 <b>Выберите вариант кнопкой ниже:</b>",
        reply_markup=_build_anonymous_keyboard(),
        parse_mode="HTML",
    )

@router.callback_query(
    StateFilter(CampaignCreationStates.waiting_for_criteria),
    F.data == "campaign_skip_criteria",
)
async def process_campaign_criteria_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(criteria_text=None, criteria_count=0)
    if callback.message:
        await callback.message.answer(
            "🔒 <b>Сделать рецензии анонимными?</b>\n"
            "Если выбрать «Да», автор не увидит имя проверяющего.",
            reply_markup=_build_anonymous_keyboard(),
            parse_mode="HTML",
        )
    await state.set_state(CampaignCreationStates.waiting_for_anonymous)
    await callback.answer()

@router.message(StateFilter(CampaignCreationStates.waiting_for_criteria))
async def process_campaign_criteria(message: types.Message, state: FSMContext):
    criteria_input = (message.text or "").strip()
    criteria = _parse_criteria_lines(criteria_input)
    if not criteria:
        await message.answer(
            "❌ Введите хотя бы один непустой критерий в отдельных строках "
            "или нажмите кнопку «Пропустить».",
            parse_mode="HTML",
            reply_markup=_build_criteria_skip_keyboard(),
        )
        return

    await state.update_data(
        criteria_text=CampaignService.serialize_criteria(criteria),
        criteria_count=len(criteria),
    )

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
    criteria = CampaignService.deserialize_criteria(data.get("criteria_text"))

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
                submission_format=SubmissionFormat(
                    data.get("submission_format", SubmissionFormat.DOCUMENT.value)
                ),
                allow_resubmission_after_review=data.get(
                    "allow_resubmission_after_review",
                    False,
                ),
                allow_resubmission_before_review=data.get(
                    "allow_resubmission_before_review",
                    False,
                ),
                criteria_text=data.get("criteria_text"),
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
                f"🔒 Анонимность: {'Да' if is_anon else 'Нет'}\n"
                f"📥 Формат сдачи: {_submission_format_label(campaign.submission_format)}\n"
                f"🧾 Критерии: {_criteria_summary_text(criteria)}\n"
                f"♻️ Замена до проверки: {'Да' if campaign.allow_resubmission_before_review else 'Нет'}\n"
                f"🔁 Пересдача после проверки: {'Да' if campaign.allow_resubmission_after_review else 'Нет'}"
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
    criteria = CampaignService.deserialize_criteria(data.get("criteria_text"))

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
                submission_format=SubmissionFormat(
                    data.get("submission_format", SubmissionFormat.DOCUMENT.value)
                ),
                allow_resubmission_after_review=data.get(
                    "allow_resubmission_after_review",
                    False,
                ),
                allow_resubmission_before_review=data.get(
                    "allow_resubmission_before_review",
                    False,
                ),
                criteria_text=data.get("criteria_text"),
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
                f"🔒 Анонимность: {'Да' if is_anon else 'Нет'}\n"
                f"📥 Формат сдачи: {_submission_format_label(campaign.submission_format)}\n"
                f"🧾 Критерии: {_criteria_summary_text(criteria)}\n"
                f"♻️ Замена до проверки: {'Да' if campaign.allow_resubmission_before_review else 'Нет'}\n"
                f"🔁 Пересдача после проверки: {'Да' if campaign.allow_resubmission_after_review else 'Нет'}"
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
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /campaigns")

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )
            return

        if user.role == UserRole.STUDENT:
            await message.answer(
                "❌ Студентам список всех кампаний недоступен. Используйте инвайт-ссылку или кнопку «📤 Загрузить работу» для сдачи в разрешённую кампанию."
            )
            return

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
            text += (
                f"   🧾 Критерии: "
                f"{_criteria_summary_text(CampaignService.deserialize_criteria(campaign.criteria_text))}\n"
            )
            text += f"   📥 Формат сдачи: {_submission_format_label(campaign.submission_format)}\n"
            text += (
                f"   ♻️ Замена до проверки: "
                f"{'Да' if campaign.allow_resubmission_before_review else 'Нет'}\n"
            )
            text += (
                f"   🔁 Пересдача после проверки: "
                f"{'Да' if campaign.allow_resubmission_after_review else 'Нет'}\n"
            )
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
            text += f"   📥 Формат сдачи: {_submission_format_label(campaign.submission_format)}\n"
            text += (
                f"   ♻️ Замена до проверки: "
                f"{'Да' if campaign.allow_resubmission_before_review else 'Нет'}\n"
            )
            text += (
                f"   🔁 Пересдача после проверки: "
                f"{'Да' if campaign.allow_resubmission_after_review else 'Нет'}\n"
            )
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
        # Get invites for each campaign
        invites_by_campaign = {}
        if campaign_ids:
            result = await session.execute(
                select(InviteCode).where(InviteCode.campaign_id.in_(campaign_ids), InviteCode.is_active == True)
            )
            invites = result.scalars().all()
            for invite in invites:
                if invite.campaign_id not in invites_by_campaign:
                    invites_by_campaign[invite.campaign_id] = []
                invites_by_campaign[invite.campaign_id].append(invite)
        
        # Add invites to text
        if invites_by_campaign:
            text += "\n🔗 <b>Инвайты кампаний:</b>\n"
            for campaign in campaigns:
                if campaign.id in invites_by_campaign:
                    text += f"\n<b>{campaign.title}</b>:\n"
                    for invite in invites_by_campaign[campaign.id]:
                        used_text = f" ({invite.uses}" + (f"/{invite.max_uses}" if invite.max_uses else "") + ")"
                        text += f"   <code>{invite.code}</code>{used_text}\n"


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


@router.callback_query(F.data.regexp(r"^finish_campaign_\d+$"))
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

        if not campaign.is_active:
            stats = await _campaign_stats(campaign_id, session)
            await callback.answer("Кампания уже завершена", show_alert=True)
            await callback.message.answer(
                "ℹ️ <b>Кампания уже завершена.</b>\n\n"
                f"📋 {campaign.title}\n"
                f"📝 Работ: <b>{stats['total_submissions']}</b>\n"
                f"✅ Проверено работ: <b>{stats['reviewed_submissions']}</b>\n"
                f"💬 Всего рецензий: <b>{stats['total_reviews']}</b>\n"
                f"⭐ Средний балл: <b>{stats['avg_score']:.1f}</b>",
                parse_mode="HTML",
            )
            return

        await callback.answer()
        await callback.message.answer(
            "⚠️ <b>Подтвердите завершение кампании</b>\n\n"
            f"📋 Кампания: <b>{campaign.title}</b>\n"
            "После подтверждения кампания будет закрыта для новых работ.",
            parse_mode="HTML",
            reply_markup=build_finish_campaign_confirmation_keyboard(campaign.id),
        )

@router.callback_query(F.data.startswith("finish_campaign_confirm:"))
async def finish_campaign_confirm(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return

    campaign_id_text = callback.data.removeprefix("finish_campaign_confirm:")
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

@router.callback_query(F.data.startswith("finish_campaign_cancel:"))
async def finish_campaign_cancel(callback: types.CallbackQuery) -> None:
    await callback.answer("Завершение кампании отменено")


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

        student_accesses = await get_campaign_accesses(tg_id=tg_id, session=session)
        student_campaign_ids = {
            access.campaign_id
            for access in student_accesses
            if access.invite_role == "student"
        }

        campaigns = [
            campaign
            for campaign in await get_active_campaigns(session)
            if campaign.id in student_campaign_ids
        ]

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

    # Verify campaign exists and user has access to it
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role != UserRole.STUDENT:
            await callback.answer("❌ Сдача работ доступна только студентам", show_alert=True)
            return
        has_student_access = await has_campaign_access(
            tg_id=callback.from_user.id,
            campaign_id=campaign_id,
            invite_role="student",
            session=session,
        )
        if not has_student_access:
            await callback.answer("❌ У вас нет доступа к этой кампании", show_alert=True)
            return

        campaign = await get_campaign(campaign_id, session)

        if not campaign:
            await callback.answer("❌ Кампания не найдена", show_alert=True)
            return

        if not campaign.is_active:
            await callback.answer("❌ Кампания неактивна", show_alert=True)
            return

    await state.update_data(campaign_id=campaign_id)

    await callback.message.edit_text(
        _submission_prompt_text(campaign),
        parse_mode="HTML",
    )
    await state.set_state(SubmissionStates.waiting_for_submission)
    await callback.answer()


@router.message(StateFilter(SubmissionStates.waiting_for_submission))
async def process_submission_file(message: types.Message, state: FSMContext):
    """Validate uploaded submission and ask for confirmation."""
    from src.bot.services.public_link_validator import (
        build_public_link_error_message,
        validate_public_link,
    )
    from src.bot.services.submission_service import check_submission_availability
    from src.bot.utils.validators import validate_submission_message

    tg_id = message.from_user.id
    data = await state.get_data()
    campaign_id = data.get("campaign_id")

    if not campaign_id:
        await message.answer("❌ Ошибка: кампания не выбрана.")
        await state.clear()
        return

    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="back_to_menu"
    ))

    should_clear_state = True

    async with session_scope() as session:
        try:
            campaign = await get_campaign(campaign_id, session)
            if not campaign:
                await message.answer("❌ Кампания не найдена.")
                await state.clear()
                return

            action, existing_submission, error_message = await check_submission_availability(
                campaign, tg_id, session
            )
            if action == "forbid":
                await message.answer(error_message or "❌ Отправка работы недоступна.")
                return

            is_valid, error_msg, payload = validate_submission_message(campaign, message)
            if not is_valid:
                await message.answer(
                    error_msg or _submission_error_text(campaign),
                    reply_markup=builder.as_markup(),
                )
                return

            if campaign.submission_format == SubmissionFormat.LINK:
                public_link_result = await validate_public_link(
                    payload["external_url"]
                )
                if not public_link_result.is_accessible:
                    await message.answer(
                        build_public_link_error_message(public_link_result),
                        reply_markup=builder.as_markup(),
                    )
                    return

                payload["external_url"] = public_link_result.normalized_url

            await state.update_data(
                submission_payload=payload,
                submission_preview_campaign_title=campaign.title,
                submission_action=action,
                existing_submission_id=existing_submission.id if existing_submission else None,
            )
            await message.answer(
                _submission_confirmation_text(campaign, payload),
                parse_mode="HTML",
                reply_markup=build_submission_confirmation_keyboard(),
            )
            await state.set_state(SubmissionStates.confirming_submission)

        except Exception as e:
            logger.error(f"Failed to prepare submission confirmation: {e}")
            await message.answer(
                "❌ Произошла ошибка при подготовке работы к отправке."
            )

@router.callback_query(StateFilter(SubmissionStates.confirming_submission), F.data == "submission_retry")
async def submission_retry(callback: types.CallbackQuery, state: FSMContext):
    """Return user to submission input step without saving work."""
    if not callback.message:
        await callback.answer()
        return

    data = await state.get_data()
    campaign_id = data.get("campaign_id")

    if not campaign_id:
        await callback.message.answer("❌ Ошибка: кампания не выбрана.")
        await state.clear()
        await callback.answer()
        return

    async with session_scope() as session:
        campaign = await get_campaign(campaign_id, session)

    if not campaign:
        await callback.message.answer("❌ Кампания не найдена.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(submission_payload=None)
    await state.set_state(SubmissionStates.waiting_for_submission)
    await callback.message.answer(
        "✏️ Отправка отменена. Пришлите работу заново.\n\n"
        f"{_submission_prompt_text(campaign)}",
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(StateFilter(SubmissionStates.confirming_submission), F.data == "submission_confirm")
async def submission_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Create submission only after explicit confirmation."""
    from src.bot.services.submission_service import (
        check_submission_availability,
        create_submission,
        replace_submission_content,
    )
    from src.bot.handlers.peer_router import start_mandatory_p2p_submission_flow

    if not callback.message:
        await callback.answer()
        return

    tg_id = callback.from_user.id
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    payload = data.get("submission_payload")
    submission_action = data.get("submission_action")
    existing_submission_id = data.get("existing_submission_id")

    if not campaign_id or not payload:
        await callback.message.answer("❌ Данные отправки потеряны. Начните заново через /submit.")
        await state.clear()
        await callback.answer()
        return

    should_clear_state = True

    async with session_scope() as session:
        try:
            campaign = await get_campaign(campaign_id, session)
            if not campaign:
                await callback.message.answer("❌ Кампания не найдена.")
                await state.clear()
                await callback.answer()
                return

            action, existing_submission, error_message = await check_submission_availability(
                campaign, tg_id, session
            )
            if action == "forbid":
                await callback.message.answer(
                    error_message or "❌ Отправка работы недоступна."
                )
                await state.clear()
                await callback.answer()
                return

            if campaign.type == CampaignType.P2P:
                if submission_action == "replace":
                    if (
                        action != "replace"
                        or existing_submission is None
                        or existing_submission_id != existing_submission.id
                    ):
                        await callback.message.answer(
                            "❌ Нельзя заменить работу: её статус уже изменился. "
                            "Начните отправку заново."
                        )
                        await state.clear()
                        await callback.answer()
                        return

                    pending_submission_id = existing_submission.id
                else:
                    pending_submission_id = None

                await state.update_data(
                    pending_submission_payload=payload,
                    pending_submission_action=submission_action or action,
                    pending_existing_submission_id=pending_submission_id,
                )

                await callback.message.answer(
                    "🧑‍🤝‍🧑 <b>P2P-кампания требует обязательных взаимных проверок.</b>\n\n"
                    "Перед публикацией вашей работы нужно проверить чужие работы."
                    " После завершения обязательного этапа работа будет сохранена автоматически.",
                    parse_mode="HTML",
                )
                should_clear_state = False
                await callback.answer()
                await start_mandatory_p2p_submission_flow(
                    callback.message,
                    state,
                    campaign,
                    tg_id,
                    payload,
                    submission_action or action,
                    pending_submission_id,
                )
                return

            if submission_action == "replace":
                if (
                    action != "replace"
                    or existing_submission is None
                    or existing_submission_id != existing_submission.id
                ):
                    await callback.message.answer(
                        "❌ Нельзя заменить работу: её статус уже изменился. "
                        "Начните отправку заново."
                    )
                    await state.clear()
                    await callback.answer()
                    return

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
                success_title = "✅ <b>Работа успешно заменена!</b>"
                success_hint = "Что дальше: дождитесь, когда обновлённую работу возьмут на проверку."
            else:
                submission = await create_submission(
                    campaign_id=campaign_id,
                    author_id=tg_id,
                    submission_type=payload["submission_type"],
                    file_id=payload.get("file_id"),
                    file_name=payload.get("file_name"),
                    mime_type=payload.get("mime_type"),
                    text_content=payload.get("text_content"),
                    external_url=payload.get("external_url"),
                    session=session,
                )
                success_title = "✅ <b>Работа успешно загружена!</b>"
                success_hint = "Что дальше: дождитесь, когда работу возьмут на проверку."

            logger.info(
                f"Submission saved: id={submission.id}, "
                f"campaign={campaign_id}, author={tg_id}, "
                f"type={submission.submission_type.value}, action={submission_action or action}"
            )

            await callback.message.answer(
                f"{success_title}\n\n"
                f"📋 Кампания: <b>{campaign.title}</b>\n"
                f"{_submission_success_details(submission)}\n"
                f"🆔 Работа: <code>{submission.id}</code>\n"
                f"📌 Статус: 🟡 <b>Ожидает проверки</b>\n"
                f"{success_hint}",
                parse_mode="HTML",
                reply_markup=build_post_submission_keyboard(),
            )

            user = await get_user(tg_id=tg_id, session=session)
            if user:
                await callback.message.answer(
                    "Главное меню:",
                    reply_markup=await get_keyboard_for_user(user),
                )

        except Exception as e:
            logger.error(f"Failed to create submission after confirmation: {e}")
            await callback.message.answer(
                "❌ Произошла ошибка при сохранении работы."
            )
        finally:
            if should_clear_state:
                await state.clear()

    await callback.answer()


@router.message(Command("my_submissions"))
async def cmd_my_submissions(message: types.Message):
    """Handle /my_submissions command - view user's submissions."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /my_submissions")

    async with session_scope() as session:
        from src.bot.services.submission_service import (
            get_user_submissions_with_review_details,
        )

        submissions = await get_user_submissions_with_review_details(tg_id, session)

        if not submissions:
            await message.answer(
                "📭 <b>У вас пока нет загруженных работ.</b>\n"
                "Используйте /submit для загрузки.",
                parse_mode="HTML",
            )
            return

        text = "📎 <b>Ваши работы:</b>\n\n"
        for i, (submission, campaign_title, review) in enumerate(submissions, 1):
            _, status_label, _ = submission_status_meta(submission.status)

            if review is None:
                review_result = "⏳ Проверка ещё не завершена"
            else:
                score_text = (
                    f"{review.score}"
                    if review.score is not None
                    else "без оценки"
                )
                comment_text = (
                    escape(review.comment_text)
                    if review.comment_text
                    else "без комментария"
                )
                review_result = f"🧾 Результат: {score_text}\n   💬 Комментарий: {comment_text}"

            text += f"{i}. <b>{escape(campaign_title)}</b>\n"
            text += f"   📊 Статус: {status_label}\n"
            text += f"   {review_result}\n\n"

        await message.answer(text, parse_mode="HTML")

"""Campaign management router for organizers."""
from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db.engine import session_scope
from src.db.models import UserRole, CampaignType
from src.services.user_service import get_user
from src.services.campaign_service import (
    get_campaign,
    get_active_campaigns,
    create_campaign,
    get_campaigns_by_organizer,
)
from src.utils.logging import logger


# FSM States for campaign creation
class CampaignCreationStates(StatesGroup):
    """States for campaign creation flow."""
    waiting_for_title = State()
    waiting_for_type = State()
    waiting_for_min_score = State()
    waiting_for_max_score = State()
    waiting_for_ttl = State()
    waiting_for_anonymous = State()


# FSM States for submission
class SubmissionStates(StatesGroup):
    """States for submission flow."""
    waiting_for_campaign = State()
    waiting_for_file = State()


# Create router
router = Router()


# Helper functions
def get_campaign_type_display(campaign_type: CampaignType) -> str:
    """Get human-readable campaign type."""
    type_map = {
        CampaignType.EXPERT: "📊 Экспертная проверка",
        CampaignType.P2P: "👥 P2P проверка",
        CampaignType.VOTING: "🗳 Голосование",
    }
    return type_map.get(campaign_type, str(campaign_type))


def build_campaigns_list_keyboard(campaigns: list, prefix: str = "camp") -> InlineKeyboardBuilder:
    """Build inline keyboard for campaign selection."""
    builder = InlineKeyboardBuilder()
    for campaign in campaigns:
        builder.add(types.InlineKeyboardButton(
            text=f"📋 {campaign.title} ({campaign.type.value})",
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

        if user.role != UserRole.ORGANIZER:
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

    await state.update_data(campaign_type=campaign_type.value)
    logger.debug(f"Campaign type selected: {campaign_type}")

    await callback.message.edit_text(
        "📊 <b>Введите минимальный балл:</b>\n"
        "(по умолчанию: 0)",
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_min_score)
    await callback.answer()


@router.message(StateFilter(CampaignCreationStates.waiting_for_min_score))
async def process_min_score(message: types.Message, state: FSMContext):
    """Process minimum score input."""
    try:
        min_score = int(message.text.strip())
        if min_score < 0:
            raise ValueError("Score cannot be negative")
    except ValueError:
        await message.answer(
            "❌ Введите целое неотрицательное число."
        )
        return

    await state.update_data(min_score=min_score)
    logger.debug(f"Min score entered: {min_score}")

    await message.answer(
        "📊 <b>Введите максимальный балл:</b>\n"
        "(по умолчанию: 100)"
    )
    await state.set_state(CampaignCreationStates.waiting_for_max_score)


@router.message(StateFilter(CampaignCreationStates.waiting_for_max_score))
async def process_max_score(message: types.Message, state: FSMContext):
    """Process maximum score input."""
    try:
        max_score = int(message.text.strip())
        if max_score < 0:
            raise ValueError("Score cannot be negative")
    except ValueError:
        await message.answer(
            "❌ Введите целое неотрицательное число."
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
        "(по умолчанию: 1440 = 24 часа)"
    )
    await state.set_state(CampaignCreationStates.waiting_for_ttl)


@router.message(StateFilter(CampaignCreationStates.waiting_for_ttl))
async def process_ttl(message: types.Message, state: FSMContext):
    """Process TTL input."""
    try:
        ttl_minutes = int(message.text.strip())
        if ttl_minutes <= 0:
            raise ValueError("TTL must be positive")
    except ValueError:
        await message.answer(
            "❌ Введите целое положительное число."
        )
        return

    await state.update_data(ttl_minutes=ttl_minutes)
    logger.debug(f"TTL entered: {ttl_minutes}")

    # Ask about anonymous reviews
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="✅ Да, анонимно",
        callback_data="anon_yes"
    ))
    builder.add(types.InlineKeyboardButton(
        text="❌ Нет, открыто",
        callback_data="anon_no"
    ))

    await message.answer(
        "🔒 <b>Экспертные рецензии анонимны?</b>\n"
        "(автор не увидит кто проверил)",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(CampaignCreationStates.waiting_for_anonymous)


@router.callback_query(StateFilter(CampaignCreationStates.waiting_for_anonymous))
async def process_anonymous_callback(callback: types.CallbackQuery, state: FSMContext):
    """Process anonymous selection."""
    is_anon = callback.data == "anon_yes"
    await state.update_data(is_expert_anon=is_anon)

    # Get all data
    data = await state.get_data()
    tg_id = callback.from_user.id

    logger.info(f"Creating campaign for organizer {tg_id}")

    # Create campaign
    async with session_scope() as session:
        try:
            campaign = await create_campaign(
                title=data["title"],
                campaign_type=CampaignType(data["campaign_type"]),
                min_score=data["min_score"],
                max_score=data["max_score"],
                ttl_minutes=data["ttl_minutes"],
                is_expert_anon=is_anon,
                organizer_id=tg_id,
                session=session,
            )

            await callback.message.edit_text(
                "✅ <b>Кампания создана!</b>\n\n"
                f"📋 <b>{campaign.title}</b>\n"
                f"📊 Тип: {get_campaign_type_display(CampaignType(data['campaign_type']))}\n"
                f"📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
                f"⏱ Время: {campaign.ttl_minutes} мин\n"
                f"🔒 Анонимность: {'Да' if is_anon else 'Нет'}",
                parse_mode="HTML",
            )
            logger.info(f"Campaign created: id={campaign.id}, title={campaign.title}")

        except Exception as e:
            logger.error(f"Failed to create campaign: {e}")
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании кампании."
            )

    await state.clear()
    await callback.answer()


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
            text += f"{i}. <b>{campaign.title}</b>\n"
            text += f"   📊 Тип: {get_campaign_type_display(campaign.type)}\n"
            text += f"   📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            text += f"   ⏱ Время: {campaign.ttl_minutes} мин\n\n"

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

        if user.role != UserRole.ORGANIZER:
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

        text = "📋 <b>Ваши кампании:</b>\n\n"
        for i, campaign in enumerate(campaigns, 1):
            status = "🟢 Активна" if campaign.is_active else "🔴 Неактивна"
            text += f"{i}. <b>{campaign.title}</b> {status}\n"
            text += f"   📊 Тип: {get_campaign_type_display(campaign.type)}\n"
            text += f"   📈 Баллы: {campaign.min_score} - {campaign.max_score}\n"
            text += f"   📝 Сдано: {len(campaign.submissions)} работ\n\n"

        await message.answer(text, parse_mode="HTML")


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
    from src.services.submission_service import (
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

            await message.answer(
                "✅ <b>Работа успешно загружена!</b>\n\n"
                f"📋 Кампания: <b>{file_name}</b>\n"
                f"📎 ID: <code>{submission.id}</code>\n"
                f"📊 Статус: Ожидает проверки",
                parse_mode="HTML",
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
        from src.services.submission_service import get_user_submissions
        from src.services.campaign_service import get_campaign

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
            text += f"   📊 Статус: {status_emoji} {submission.status.value}\n"
            text += f"   📝 ID: <code>{submission.id}</code>\n"
            text += f"   📅 Дата: {submission.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"

        await message.answer(text, parse_mode="HTML")

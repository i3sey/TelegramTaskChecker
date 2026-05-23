"""Authentication router for user registration."""

import os

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.states import RegistrationStates, RoleChangeStates
from src.db.models import UserRole
from src.db.engine import session_scope
from src.bot.services.user_service import (
    create_user,
    ensure_web_access_token,
    get_campaign_accesses,
    get_user,
    grant_campaign_access,
    update_user_role,
)
from src.bot.services.invite_service import (
    get_invite_by_code,
    is_invite_valid,
    mark_invite_used,
)
from src.bot.utils.logging import logger
from src.bot.keyboards import (
    get_keyboard_for_user,
    build_full_name_confirmation_keyboard,
    build_study_group_confirmation_keyboard,
    BTN_PROFILE,
    BTN_HELP,
    BTN_ROLE,
)
from src.bot.ui import (
    role_label,
    registration_welcome_text,
    help_text_for_role,
    profile_text,
)

# Create router
router = Router()

def _role_label(role: UserRole) -> str:
    """Get human-readable label for role selection."""
    return role_label(role)

def _build_role_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for role selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_role_label(UserRole.STUDENT), callback_data="role_student")],
            [InlineKeyboardButton(text=_role_label(UserRole.EXPERT), callback_data="role_expert")],
            [InlineKeyboardButton(text=_role_label(UserRole.EXPERT_ORGANIZER), callback_data="role_expert_organizer")],
            [InlineKeyboardButton(text=_role_label(UserRole.ORGANIZER), callback_data="role_organizer")],
        ]
    )

def _extract_start_payload(text: str | None) -> str | None:
    """Extract payload from /start command text."""
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        return parts[1].strip()
    return None

def _role_requires_invite(role: UserRole) -> bool:
    """Return True if role requires invite access."""
    return role in (UserRole.STUDENT, UserRole.EXPERT)

def _invite_matches_role(invite_role: str | None, role: UserRole) -> bool:
    """Return True when invite role allows the requested role."""
    if role == UserRole.STUDENT:
        return invite_role == "student"
    if role == UserRole.EXPERT:
        return invite_role == "expert"
    return False

async def _has_invite_access(user, session) -> bool:
    """Check if user has valid invite access for their role."""
    if not _role_requires_invite(user.role):
        return True

    if user.registered_by_code and _invite_matches_role(user.invite_role, user.role):
        return True

    accesses = await get_campaign_accesses(user.tg_id, session)
    return any(_invite_matches_role(access.invite_role, user.role) for access in accesses)

def _build_web_app_url(token: str) -> str | None:
    """Build organizer frontend URL from environment."""
    base_url = (
        os.getenv("WEB_APP_URL")
        or os.getenv("APP_URL")
        or os.getenv("PUBLIC_URL")
    )
    if not base_url:
        return None

    normalized = base_url.rstrip("/")
    return f"{normalized}/organizer/{token}"

def _build_organizer_web_message(token: str) -> str:
    """Build message with personal organizer frontend URL."""
    web_url = _build_web_app_url(token)
    if not web_url:
        return (
            "\n\n🌐 <b>Персональная ссылка организатора создана.</b>\n"
            "Чтобы открыть фронтенд, укажите публичный адрес приложения "
            "в переменной окружения <code>WEB_APP_URL</code>."
        )

    return (
        "\n\n🌐 <b>Ваша персональная панель организатора:</b>\n"
        f"{web_url}"
    )

# Command handlers
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Handle /start command."""
    tg_id = message.from_user.id
    payload = _extract_start_payload(message.text)
    invite_role = None

    # Check if user exists in database
    async with session_scope() as session:
        invite = None
        if payload:
            invite = await get_invite_by_code(payload, session)
        invite_ok = is_invite_valid(invite)
        invite_role = invite.role if invite_ok else None
        invite_campaign_id = invite.campaign_id if invite_ok else None

        existing_user = await get_user(tg_id=tg_id, session=session)

        if existing_user:
            if invite_ok and invite_campaign_id is not None and invite_role is not None:
                await grant_campaign_access(
                    tg_id=tg_id,
                    campaign_id=invite_campaign_id,
                    invite_role=invite_role,
                    invite_code=payload,
                    session=session,
                )
                await mark_invite_used(invite, session)

                if invite_role == "student":
                    await message.answer(
                        "✅ Инвайт активирован. Доступ к сдаче работ открыт.",
                        parse_mode="HTML",
                    )
                elif invite_role == "expert":
                    await message.answer(
                        "✅ Инвайт активирован. Доступ к проверке работ открыт.",
                        parse_mode="HTML",
                    )

            extra_notice = ""
            # Don't show invite warning if we just validated an invite
            if not invite_ok and not await _has_invite_access(existing_user, session):
                extra_notice = (
                    "\n\n🔐 <b>Для полного доступа нужен код приглашения.</b>\n"
                    "Что делать:\n"
                    "• попросите код или ссылку приглашения у преподавателя / организатора;\n"
                    "• откройте ссылку-приглашение, если вам её прислали;\n"
                    "• либо отправьте команду <code>/start ВАШ_КОД</code>.\n\n"
                    "Без кода вы сможете войти в бота, но некоторые действия для выбранной роли будут недоступны.\n"
                    "Режимы организатора открываются только реальными правами организатора, а не student/expert-инвайтом."
                )

            commands_text = (
                "Доступные команды:\n"
                "👤 /profile - Профиль\n"
                "🎭 /role - Изменить роль\n"
                "❓ /help - Помощь"
            )
            if existing_user.role != UserRole.STUDENT:
                commands_text = (
                    "Доступные команды:\n"
                    "📋 /campaigns - Активные кампании\n"
                    "👤 /profile - Профиль\n"
                    "🎭 /role - Изменить роль\n"
                    "❓ /help - Помощь"
                )

            await message.answer(
                f"👋 <b>Добро пожаловать, {existing_user.full_name}!</b>\n\n"
                f"Вы успешно авторизованы как <b>{_role_label(existing_user.role)}</b>.\n"
                f"Группа: <b>{existing_user.study_group}</b>\n\n"
                f"{commands_text}"
                f"{extra_notice}",
                parse_mode="HTML",
                reply_markup=await get_keyboard_for_user(existing_user),
            )

        else:
            await state.update_data(
                invite_role=invite_role,
                invite_ok=invite_ok,
                invite_code=payload,
                invite_campaign_id=invite_campaign_id,
            )
            if invite_ok:
                role = UserRole.STUDENT if invite_role == "student" else UserRole.EXPERT
                await state.update_data(role=role)
                await message.answer(
                    "🎓 <b>Добро пожаловать в Telegram Task Checker!</b>\n\n"
                    "Для регистрации введите ваше <b>полное имя</b> (ФИО):",
                    parse_mode="HTML",
                )
                await state.set_state(RegistrationStates.waiting_for_full_name)
            else:
                await message.answer(
                    registration_welcome_text()
                    + "\n\n"
                    + "🔐 <b>Для роли студента или эксперта может понадобиться код приглашения.</b>\n"
                    + "Если у вас его пока нет, попросите код или ссылку у преподавателя / организатора.\n"
                    + "Режимы организатора открываются только реальными правами в системе.\n"
                    + "Код можно будет отправить позже командой <code>/start ВАШ_КОД</code>.",
                    reply_markup=_build_role_keyboard(),
                    parse_mode="HTML",
                )
                await state.set_state(RegistrationStates.waiting_for_role)

@router.message(StateFilter(RegistrationStates.waiting_for_full_name))
async def process_full_name(message: types.Message, state: FSMContext):
    """Process user's full name input."""
    full_name = message.text.strip()

    # Validate input
    if len(full_name) < 2:
        await message.answer(
            "❌ Имя слишком короткое. Введите полное имя (минимум 2 символа):"
        )
        return

    if len(full_name) > 100:
        await message.answer(
            "❌ Имя слишком длинное. Введите полное имя (максимум 100 символов):"
        )
        return

    # Save full name to FSM context
    await state.update_data(full_name=full_name)
    logger.debug(f"User {message.from_user.id} entered full_name: {full_name}")

    data = await state.get_data()
    role = data.get("role")

    if role is None:
        await message.answer("❌ Сначала выберите роль через /start.")
        await state.clear()
        return

    role_line = f"🎭 Роль: <b>{_role_label(role)}</b>\n" if role else ""
    group_hint = ""
    if role == UserRole.STUDENT:
        group_hint = "\nПосле подтверждения бот попросит ввести учебную группу."

    await message.answer(
        "🪪 <b>Проверьте ФИО</b>\n\n"
        f"👤 <b>{full_name}</b>\n"
        f"{role_line}"
        f"{group_hint}\n\n"
        "Если всё верно, подтвердите. Если есть опечатка — введите заново.",
        parse_mode="HTML",
        reply_markup=build_full_name_confirmation_keyboard(),
    )
    await state.set_state(RegistrationStates.confirming_full_name)

@router.callback_query(StateFilter(RegistrationStates.confirming_full_name), F.data == "reg_reenter_full_name")
async def reg_reenter_full_name(callback: types.CallbackQuery, state: FSMContext):
    """Allow user to re-enter full name during registration."""
    if not callback.message:
        await callback.answer()
        return

    await state.set_state(RegistrationStates.waiting_for_full_name)
    await callback.message.answer(
        "✏️ Введите ваше <b>полное имя</b> (ФИО) заново:",
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(StateFilter(RegistrationStates.confirming_full_name), F.data == "reg_confirm_full_name")
async def reg_confirm_full_name(callback: types.CallbackQuery, state: FSMContext):
    """Confirm full name and continue registration flow."""
    if not callback.message:
        await callback.answer()
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    role = data.get("role")
    invite_ok = data.get("invite_ok", False)
    invite_role = data.get("invite_role")
    invite_code = data.get("invite_code")
    invite_campaign_id = data.get("invite_campaign_id")

    if not full_name or role is None:
        await callback.message.answer(
            "❌ Данные регистрации потеряны. Используйте /start для повторной попытки."
        )
        await state.clear()
        await callback.answer()
        return

    if role == UserRole.STUDENT:
        await callback.message.answer(
            "📚 Отлично! Теперь введите вашу <b>учебную группу</b>:\n"
            "(например: ИВТ-101, ИС-201)",
            parse_mode="HTML",
        )
        await state.set_state(RegistrationStates.waiting_for_study_group)
        await callback.answer()
        return

    try:
        async with session_scope() as session:
            invite = None
            if invite_ok and invite_code:
                invite = await get_invite_by_code(invite_code, session)

            user = await create_user(
                tg_id=callback.from_user.id,
                full_name=full_name,
                study_group=None,
                session=session,
                role=role,
                registered_by_code=False,
                invite_role=None,
                campaign_id=None,
            )
            if (
                invite_ok
                and invite
                and _role_requires_invite(role)
                and invite_campaign_id is not None
                and invite_role is not None
            ):
                await grant_campaign_access(
                    tg_id=callback.from_user.id,
                    campaign_id=invite_campaign_id,
                    invite_role=invite_role,
                    invite_code=invite_code,
                    session=session,
                )
                await mark_invite_used(invite, session)

            organizer_note = ""
            if role in {UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER}:
                web_access_token = await ensure_web_access_token(user, session)
                organizer_note = _build_organizer_web_message(web_access_token)

        await state.clear()

        access_note = ""
        if invite_ok and invite_role == "expert":
            access_note = "\n\n✅ Инвайт активирован. Доступ к проверке работ открыт."

        await callback.message.answer(
            "✅ <b>Регистрация успешна!</b>\n\n"
            f"👤 <b>{full_name}</b>\n"
            f"🎭 Роль: <b>{_role_label(role)}</b>"
            f"{access_note}"
            f"{organizer_note}\n\n"
            "Используйте /help для списка команд.",
            parse_mode="HTML",
            reply_markup=await get_keyboard_for_user(user),
        )
    except Exception as e:
        logger.error(f"Failed to create user {callback.from_user.id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при регистрации. Попробуйте позже.\n"
            "Используйте /start для повторной попытки."
        )
        await state.clear()

    await callback.answer()

@router.message(StateFilter(RegistrationStates.waiting_for_study_group))
async def process_study_group(message: types.Message, state: FSMContext):
    """Process user's study group input."""
    study_group = message.text.strip().upper()

    # Validate input
    if len(study_group) < 2:
        await message.answer(
            "❌ Название группы слишком короткое. Введите учебную группу:"
        )
        return

    if len(study_group) > 50:
        await message.answer(
            "❌ Название группы слишком длинное. Введите учебную группу:"
        )
        return

    data = await state.get_data()
    role = data.get("role")

    if role != UserRole.STUDENT:
        await message.answer("❌ Некорректная роль для ввода группы.")
        await state.clear()
        return

    await state.update_data(study_group=study_group)
    await state.set_state(RegistrationStates.confirming_study_group)

    await message.answer(
        "🪪 <b>Проверьте учебную группу</b>\n\n"
        f"📚 <b>{study_group}</b>\n\n"
        "Если всё верно, подтвердите. Если есть опечатка — введите заново.",
        parse_mode="HTML",
        reply_markup=build_study_group_confirmation_keyboard(),
    )

@router.callback_query(
    StateFilter(RegistrationStates.confirming_study_group),
    F.data == "reg_reenter_study_group",
)
async def reg_reenter_study_group(callback: types.CallbackQuery, state: FSMContext):
    """Allow user to re-enter study group during registration."""
    if not callback.message:
        await callback.answer()
        return

    await state.set_state(RegistrationStates.waiting_for_study_group)
    await callback.message.answer(
        "✏️ Введите вашу <b>учебную группу</b> заново:\n"
        "(например: ИВТ-101, ИС-201)",
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(
    StateFilter(RegistrationStates.confirming_study_group),
    F.data == "reg_confirm_study_group",
)
async def reg_confirm_study_group(callback: types.CallbackQuery, state: FSMContext):
    """Confirm study group and finish student registration."""
    if not callback.message:
        await callback.answer()
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    study_group = data.get("study_group")
    role = data.get("role")
    invite_ok = data.get("invite_ok", False)
    invite_role = data.get("invite_role")
    invite_code = data.get("invite_code")
    invite_campaign_id = data.get("invite_campaign_id")

    tg_id = callback.from_user.id

    if role != UserRole.STUDENT or not full_name or not study_group:
        await callback.message.answer(
            "❌ Данные регистрации потеряны. Используйте /start для повторной попытки."
        )
        await state.clear()
        await callback.answer()
        return

    try:
        async with session_scope() as session:
            invite = None
            if invite_ok and invite_code:
                invite = await get_invite_by_code(invite_code, session)

            user = await create_user(
                tg_id=tg_id,
                full_name=full_name,
                study_group=study_group,
                session=session,
                role=UserRole.STUDENT,
                registered_by_code=False,
                invite_role=None,
                campaign_id=None,
            )
            if invite_ok and invite and invite_campaign_id is not None and invite_role is not None:
                await grant_campaign_access(
                    tg_id=tg_id,
                    campaign_id=invite_campaign_id,
                    invite_role=invite_role,
                    invite_code=invite_code,
                    session=session,
                )
                await mark_invite_used(invite, session)
            logger.info(
                f"New user registered: tg_id={tg_id}, "
                f"name={full_name}, group={study_group}"
            )

        await state.clear()

        access_note = ""
        if invite_ok:
            access_note = "\n\n✅ Инвайт активирован. Доступ к сдаче работ открыт."

        await callback.message.answer(
            "✅ <b>Регистрация успешна!</b>\n\n"
            f"👤 <b>{full_name}</b>\n"
            f"📚 Группа: <b>{study_group}</b>\n"
            f"🎭 Роль: <b>{_role_label(UserRole.STUDENT)}</b>"
            f"{access_note}\n\n"
            "Теперь вы можете выбрать кампанию и загрузить работу.",
            parse_mode="HTML",
            reply_markup=await get_keyboard_for_user(user),
        )

    except Exception as e:
        logger.error(f"Failed to create user {tg_id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при регистрации. Попробуйте позже.\n"
            "Используйте /start для повторной попытки."
        )
        await state.clear()

    await callback.answer()

@router.callback_query(StateFilter(RegistrationStates.waiting_for_role))
async def process_role_selection(callback: types.CallbackQuery, state: FSMContext):
    """Process role selection before registration."""
    if not callback.data or not callback.data.startswith("role_"):
        await callback.answer()
        return

    role_value = callback.data.replace("role_", "")
    try:
        role = UserRole(role_value)
    except ValueError:
        await callback.answer("❌ Неизвестная роль", show_alert=True)
        return

    data = await state.get_data()
    invite_ok = data.get("invite_ok", False)
    invite_role = data.get("invite_role")

    await state.update_data(role=role)
    await callback.message.answer(
        "Для регистрации введите ваше <b>полное имя</b> (ФИО):",
        parse_mode="HTML",
    )
    await state.set_state(RegistrationStates.waiting_for_full_name)
    await callback.answer()

@router.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    """Handle /help command."""
    current_state = await state.get_state()

    if current_state is not None:
        await message.answer(
            "❌ Используйте /cancel для отмены текущей операции."
        )
        return

    user_role = None
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if user:
            user_role = user.role

    await message.answer(
        help_text_for_role(user_role),
        parse_mode="HTML",
    )

@router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    """Handle /profile command."""
    tg_id = message.from_user.id

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if user:
            await message.answer(
                profile_text(user),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )

@router.message(F.text == BTN_PROFILE)
async def btn_profile(message: types.Message):
    await cmd_profile(message)

@router.message(Command("role"))
async def cmd_role(message: types.Message, state: FSMContext):
    """Handle /role command to change user role."""
    tg_id = message.from_user.id

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )
            return

    await message.answer(
        "🎭 Выберите новую роль:",
        reply_markup=_build_role_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(RoleChangeStates.waiting_for_role)

@router.message(F.text == BTN_ROLE)
async def btn_role(message: types.Message, state: FSMContext):
    await cmd_role(message, state)

@router.callback_query(StateFilter(RoleChangeStates.waiting_for_role))
async def process_role_change(callback: types.CallbackQuery, state: FSMContext):
    """Process role change for existing users."""
    if not callback.data or not callback.data.startswith("role_"):
        await callback.answer()
        return

    role_value = callback.data.replace("role_", "")
    try:
        role = UserRole(role_value)
    except ValueError:
        await callback.answer("❌ Неизвестная роль", show_alert=True)
        return

    tg_id = callback.from_user.id

    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return

        user = await update_user_role(tg_id=tg_id, role=role, session=session)
        has_access = await _has_invite_access(user, session)
        organizer_note = ""
        if role in {UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER}:
            web_access_token = await ensure_web_access_token(user, session)
            organizer_note = _build_organizer_web_message(web_access_token)

    await state.clear()

    message_text = (
        "✅ Роль обновлена.\n\n"
        f"Теперь вы: <b>{_role_label(role)}</b>"
    )
    if _role_requires_invite(role) and not has_access:
        message_text += (
            "\n\nДоступ к функциям роли будет открыт после инвайта. "
            "Откройте ссылку приглашения"
        )
    message_text += organizer_note

    await callback.message.edit_text(
        message_text,
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Главное меню обновлено.",
        reply_markup=await get_keyboard_for_user(user),
    )
    await callback.answer()

@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Handle /cancel command to cancel registration."""
    current_state = await state.get_state()

    if current_state is not None:
        await state.clear()
        logger.info(f"User {message.from_user.id} cancelled registration")
        await message.answer(
            "❌ <b>Операция отменена.</b>\n\n"
            "Используйте /start для начала заново или /help для подсказок.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "ℹ️ Нет активной операции для отмены."
        )

@router.message(F.text == BTN_HELP)
async def btn_help(message: types.Message, state: FSMContext):
    await cmd_help(message, state)

@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return

    tg_id = callback.from_user.id
    async with session_scope() as session:
        user = await get_user(tg_id=tg_id, session=session)

        if user:
            await callback.message.answer(
                profile_text(user),
                parse_mode="HTML",
            )
        else:
            await callback.message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )

    await callback.answer()

@router.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return

    await cmd_help(callback.message, state)
    await callback.answer()
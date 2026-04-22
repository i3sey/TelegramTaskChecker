"""Authentication router for user registration."""
from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.engine import session_scope
from src.services.user_service import get_user, create_user
from src.db.models import UserRole
from src.utils.logging import logger


# FSM States for registration
class RegistrationStates(StatesGroup):
    """States for user registration flow."""
    waiting_for_full_name = State()
    waiting_for_study_group = State()


# Create router
router = Router()


# Command handlers
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Handle /start command."""
    tg_id = message.from_user.id
    logger.info(f"User {tg_id} triggered /start command")

    # Check if user exists in database
    async with session_scope() as session:
        existing_user = await get_user(tg_id=tg_id, session=session)

        if existing_user:
            # User already registered - show main menu
            logger.info(f"Existing user {tg_id} ({existing_user.full_name}) started bot")
            await message.answer(
                f"👋 <b>Добро пожаловать, {existing_user.full_name}!</b>\n\n"
                f"Вы успешно авторизованы как <b>{existing_user.role.value}</b>.\n"
                f"Группа: <b>{existing_user.study_group}</b>\n\n"
                "Доступные команды:\n"
                "📋 /campaigns - Мои кампании\n"
                "👤 /profile - Профиль\n"
                "❓ /help - Помощь",
                parse_mode="HTML",
            )
        else:
            # New user - start registration
            logger.info(f"New user {tg_id} starting registration")
            await message.answer(
                "🎓 <b>Добро пожаловать в Telegram Task Checker!</b>\n\n"
                "Для регистрации введите ваше <b>полное имя</b> (ФИО):",
                parse_mode="HTML",
            )
            await state.set_state(RegistrationStates.waiting_for_full_name)


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

    # Ask for study group
    await message.answer(
        "📚 Отлично! Теперь введите вашу <b>учебную группу</b>:\n"
        "(например: ИВТ-101, ИС-201)",
        parse_mode="HTML",
    )
    await state.set_state(RegistrationStates.waiting_for_study_group)


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

    # Get full name from FSM context
    data = await state.get_data()
    full_name = data.get("full_name")

    tg_id = message.from_user.id

    # Create user in database
    try:
        async with session_scope() as session:
            user = await create_user(
                tg_id=tg_id,
                full_name=full_name,
                study_group=study_group,
                session=session,
                role=UserRole.STUDENT,
            )
            logger.info(
                f"New user registered: tg_id={tg_id}, "
                f"name={full_name}, group={study_group}"
            )

        # Clear FSM state
        await state.clear()

        # Send success message
        await message.answer(
            "✅ <b>Регистрация успешна!</b>\n\n"
            f"👤 <b>{full_name}</b>\n"
            f"📚 Группа: <b>{study_group}</b>\n"
            f"🎭 Роль: <b>Студент</b>\n\n"
            "Используйте /help для списка команд.",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Failed to create user {tg_id}: {e}")
        await message.answer(
            "❌ Произошла ошибка при регистрации. Попробуйте позже.\n"
            "Используйте /start для повторной попытки."
        )
        await state.clear()


@router.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    """Handle /help command."""
    current_state = await state.get_state()

    if current_state is not None:
        await message.answer(
            "❌ Используйте /cancel для отмены текущей операции."
        )
        return

    await message.answer(
        "📖 <b>Справка по командам:</b>\n\n"
        "<b>Общие:</b>\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/profile - Информация о профиле\n"
        "/campaigns - Активные кампании\n\n"
        "<b>Для студентов:</b>\n"
        "/submit - Загрузить работу на проверку\n"
        "/my_submissions - Мои загруженные работы\n\n"
        "<b>Для экспертов:</b>\n"
        "/queue - Очередь работ на проверку\n"
        "/take - Взять работу на проверку\n"
        "/return - Вернуть работу в очередь\n"
        "/expert_stats - Ваша статистика\n\n"
        "<b>Для организаторов:</b>\n"
        "/create_campaign - Создать новую кампанию\n"
        "/my_campaigns - Мои кампании",
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
                "👤 <b>Ваш профиль:</b>\n\n"
                f"ID: <code>{user.tg_id}</code>\n"
                f"Имя: <b>{user.full_name}</b>\n"
                f"Группа: <b>{user.study_group or 'Не указана'}</b>\n"
                f"Роль: <b>{user.role.value if hasattr(user.role, 'value') else user.role}</b>\n"
                f"Статус: {'✅ Активен' if not user.is_banned else '⛔ Заблокирован'}",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "❌ Вы не зарегистрированы. Используйте /start для регистрации."
            )


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Handle /cancel command to cancel registration."""
    current_state = await state.get_state()

    if current_state is not None:
        await state.clear()
        logger.info(f"User {message.from_user.id} cancelled registration")
        await message.answer(
            "❌ <b>Регистрация отменена.</b>\n\n"
            "Используйте /start для начала заново.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "ℹ️ Нет активной операции для отмены."
        )
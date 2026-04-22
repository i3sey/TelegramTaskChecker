"""Mock message factories for integration testing."""
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock


def create_mock_user(tg_id: int, full_name: str = "Test User") -> MagicMock:
    """Create mock Telegram User object.

    Args:
        tg_id: Telegram user ID
        full_name: User's full name

    Returns:
        MagicMock configured as Telegram User
    """
    user = MagicMock()
    user.id = tg_id
    user.full_name = full_name
    user.first_name = full_name.split()[0] if full_name else "Test"
    user.last_name = " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else None
    user.is_bot = False
    user.language_code = "ru"
    return user


def create_mock_message(
    tg_id: int,
    text: str = "/start",
    full_name: str = "Test User",
) -> MagicMock:
    """Create mock Telegram Message object.

    Args:
        tg_id: Telegram user ID
        text: Message text
        full_name: User's full name

    Returns:
        MagicMock configured as Telegram Message
    """
    message = MagicMock()
    message.from_user = create_mock_user(tg_id, full_name)
    message.text = text
    message.document = None
    message.photo = None
    message.answer = AsyncMock()
    message.answer_document = AsyncMock()
    message.edit_text = AsyncMock()
    message.bot = MagicMock()
    message.chat = MagicMock()
    message.chat.id = tg_id
    message.message_id = 1
    message.date = MagicMock()
    return message


def create_mock_document(
    file_id: str = "test_file_id_123",
    file_name: str = "test.pdf",
    file_size: int = 1024,
) -> MagicMock:
    """Create mock Telegram Document object.

    Args:
        file_id: Telegram file ID
        file_name: Name of the file
        file_size: Size in bytes

    Returns:
        MagicMock configured as Telegram Document
    """
    doc = MagicMock()
    doc.file_id = file_id
    doc.file_name = file_name
    doc.file_size = file_size
    doc.mime_type = "application/pdf"
    return doc


def create_mock_callback(
    data: str,
    tg_id: int = 123456789,
    full_name: str = "Test User",
) -> MagicMock:
    """Create mock CallbackQuery object.

    Args:
        data: Callback data string
        tg_id: Telegram user ID
        full_name: User's full name

    Returns:
        MagicMock configured as CallbackQuery
    """
    callback = MagicMock()
    callback.from_user = create_mock_user(tg_id, full_name)
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.bot = MagicMock()
    callback.bot = MagicMock()
    return callback


def create_mock_fsm_context() -> MagicMock:
    """Create mock FSMContext for state testing.

    Returns:
        MagicMock configured as FSMContext
    """
    fsm = MagicMock()
    fsm.set_state = AsyncMock()
    fsm.update_data = AsyncMock()
    fsm.get_data = AsyncMock(return_value={})
    fsm.clear = AsyncMock()
    return fsm


def create_mock_inline_button(text: str, callback_data: str) -> MagicMock:
    """Create mock InlineKeyboardButton.

    Args:
        text: Button text
        callback_data: Callback data

    Returns:
        MagicMock configured as InlineKeyboardButton
    """
    button = MagicMock()
    button.text = text
    button.callback_data = callback_data
    return button


def create_mock_inline_keyboard_markup(buttons: list[list[MagicMock]]) -> MagicMock:
    """Create mock InlineKeyboardMarkup.

    Args:
        buttons: 2D list of button mocks

    Returns:
        MagicMock configured as InlineKeyboardMarkup
    """
    markup = MagicMock()
    markup.inline_keyboard = buttons
    return markup

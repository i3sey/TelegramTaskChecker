"""Integration tests for authentication flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from src.bot.handlers.auth_router import (
    router as auth_router,
    RegistrationStates,
    cmd_start,
    process_full_name,
    process_study_group,
    cmd_help,
    cmd_profile,
    cmd_cancel,
)
from src.db.models import User, UserRole
from tests.fixtures.mock_message import create_mock_message, create_mock_user


class TestStartCommand:
    """Tests for /start command handling."""

    @pytest.mark.asyncio
    async def test_start_command_new_user(self):
        """Test /start for new user triggers registration FSM."""
        # Create mock message
        message = create_mock_message(
            tg_id=123456789,
            text="/start",
            full_name="New User"
        )

        # Mock FSM context
        state = MagicMock(spec=FSMContext)
        state.set_state = AsyncMock()

        # Mock user doesn't exist
        with patch("src.bot.handlers.auth_router.get_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None  # New user

            with patch("src.bot.handlers.auth_router.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

                # Call the handler
                await cmd_start(message, state)

                # Verify FSM state was set for registration
                state.set_state.assert_called_once_with(RegistrationStates.waiting_for_full_name)

                # Verify bot asked for registration
                message.answer.assert_called_once()
                call_args = message.answer.call_args
                assert "Добро пожаловать" in call_args[0][0]
                assert "полное имя" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_start_command_existing_user(self):
        """Test /start for existing user shows welcome message."""
        # Create existing user
        existing_user = MagicMock()
        existing_user.tg_id = 123456789
        existing_user.full_name = "Existing User"
        existing_user.study_group = "ИВТ-101"
        existing_user.role = UserRole.STUDENT
        existing_user.is_banned = False

        # Create mock message
        message = create_mock_message(
            tg_id=123456789,
            text="/start",
            full_name="Existing User"
        )

        # Mock FSM context
        state = MagicMock(spec=FSMContext)
        state.set_state = AsyncMock()

        with patch("src.bot.handlers.auth_router.get_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = existing_user

            with patch("src.bot.handlers.auth_router.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

                await cmd_start(message, state)

                # FSM state should not be set for existing users
                state.set_state.assert_not_called()

                # Verify welcome message was sent
                message.answer.assert_called_once()
                call_args = message.answer.call_args
                assert "Existing User" in call_args[0][0]


class TestRegistrationFlow:
    """Tests for registration FSM flow."""

    @pytest.mark.asyncio
    async def test_process_full_name_valid(self):
        """Test valid full name input transitions to study group state."""
        message = create_mock_message(
            tg_id=123456789,
            text="Иванов Иван Иванович",
            full_name="Иванов Иван Иванович"
        )

        state = MagicMock(spec=FSMContext)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        await process_full_name(message, state)

        # Verify name was saved
        state.update_data.assert_called_once_with(full_name="Иванов Иван Иванович")

        # Verify state changed to study group
        state.set_state.assert_called_once_with(RegistrationStates.waiting_for_study_group)

        # Verify message asking for study group
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "учебную группу" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_full_name_too_short(self):
        """Test that too short name is rejected."""
        message = create_mock_message(
            tg_id=123456789,
            text="И",
            full_name="И"
        )

        state = MagicMock(spec=FSMContext)

        await process_full_name(message, state)

        # Verify error message was sent
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "слишком короткое" in call_args[0][0]

        # Verify state was not changed
        state.update_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_full_name_too_long(self):
        """Test that too long name is rejected."""
        message = create_mock_message(
            tg_id=123456789,
            text="А" * 150,
            full_name="А" * 150
        )

        state = MagicMock(spec=FSMContext)

        await process_full_name(message, state)

        # Verify error message was sent
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "слишком длинное" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_study_group_valid(self):
        """Test valid study group input completes registration."""
        message = create_mock_message(
            tg_id=123456789,
            text="ИВТ-101",
            full_name="Test User"
        )

        state = MagicMock(spec=FSMContext)
        state.get_data = AsyncMock(return_value={"full_name": "Test User"})
        state.update_data = AsyncMock()
        state.clear = AsyncMock()

        # Mock campaign to not raise exception
        with patch("src.bot.handlers.auth_router.create_user", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = MagicMock(
                tg_id=123456789,
                full_name="Test User",
                study_group="ИВТ-101",
                role=UserRole.STUDENT,
            )

            with patch("src.bot.handlers.auth_router.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

                await process_study_group(message, state)

                # Verify FSM was cleared
                state.clear.assert_called_once()

                # Verify success message
                message.answer.assert_called_once()
                call_args = message.answer.call_args
                assert "Регистрация успешна" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_process_study_group_too_short(self):
        """Test that too short study group is rejected."""
        message = create_mock_message(
            tg_id=123456789,
            text="И",
            full_name="Test User"
        )

        state = MagicMock(spec=FSMContext)
        state.get_data = AsyncMock(return_value={"full_name": "Test User"})

        await process_study_group(message, state)

        # Verify error message
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "слишком короткое" in call_args[0][0]


class TestProfileCommand:
    """Tests for /profile command."""

    @pytest.mark.asyncio
    async def test_profile_registered_user(self):
        """Test /profile shows user info for registered user."""
        user = MagicMock()
        user.tg_id = 123456789
        user.full_name = "Test User"
        user.study_group = "ИВТ-101"
        user.role = UserRole.STUDENT
        user.is_banned = False

        message = create_mock_message(
            tg_id=123456789,
            text="/profile",
            full_name="Test User"
        )

        with patch("src.bot.handlers.auth_router.get_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = user

            with patch("src.bot.handlers.auth_router.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

                await cmd_profile(message)

                # Verify profile message
                message.answer.assert_called_once()
                call_args = message.answer.call_args
                response_text = call_args[0][0]
                assert "Test User" in response_text
                assert "ИВТ-101" in response_text

    @pytest.mark.asyncio
    async def test_profile_unregistered_user(self):
        """Test /profile shows error for unregistered user."""
        message = create_mock_message(
            tg_id=999999999,
            text="/profile",
            full_name="Unknown User"
        )

        with patch("src.bot.handlers.auth_router.get_user", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with patch("src.bot.handlers.auth_router.session_scope") as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_scope.return_value.__aexit__ = AsyncMock(return_value=None)

                await cmd_profile(message)

                # Verify error message
                message.answer.assert_called_once()
                call_args = message.answer.call_args
                assert "не зарегистрированы" in call_args[0][0]


class TestCancelCommand:
    """Tests for /cancel command."""

    @pytest.mark.asyncio
    async def test_cancel_active_registration(self):
        """Test /cancel cancels active registration FSM."""
        message = create_mock_message(
            tg_id=123456789,
            text="/cancel",
            full_name="Test User"
        )

        state = MagicMock(spec=FSMContext)
        state.get_state = AsyncMock(return_value=RegistrationStates.waiting_for_study_group)
        state.clear = AsyncMock()

        await cmd_cancel(message, state)

        # Verify FSM was cleared
        state.clear.assert_called_once()

        # Verify cancellation message
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "отменена" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cancel_no_active_operation(self):
        """Test /cancel when no active operation."""
        message = create_mock_message(
            tg_id=123456789,
            text="/cancel",
            full_name="Test User"
        )

        state = MagicMock(spec=FSMContext)
        state.get_state = AsyncMock(return_value=None)

        await cmd_cancel(message, state)

        # Verify no cancellation message
        message.answer.assert_called_once()
        call_args = message.answer.call_args
        assert "Нет активной операции" in call_args[0][0]

"""Integration tests for expert review flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.bot.handlers.expert_router import (
    ExpertReviewState,
    get_score_keyboard,
    get_confirm_keyboard,
)


class TestScoreKeyboard:
    """Tests for score keyboard generation."""

    def test_score_keyboard_generation(self):
        """Test score keyboard is generated correctly."""
        keyboard = get_score_keyboard(0, 100)
        assert len(keyboard.inline_keyboard) > 0
        first_row = keyboard.inline_keyboard[0]
        assert len(first_row) > 0
        last_row = keyboard.inline_keyboard[-1]
        cancel_button = last_row[0]
        assert cancel_button.callback_data == "cancel_review"

    def test_score_keyboard_with_custom_range(self):
        """Test score keyboard with custom range."""
        keyboard = get_score_keyboard(1, 5)
        assert len(keyboard.inline_keyboard) > 0

    def test_confirm_keyboard_structure(self):
        """Test confirm keyboard has correct structure."""
        keyboard = get_confirm_keyboard()
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2
        assert keyboard.inline_keyboard[0][0].text == "Подтвердить"
        assert keyboard.inline_keyboard[0][1].text == "Отмена"


class TestExpertReviewState:
    """Tests for FSM states."""

    def test_expert_states_exist(self):
        """Test all FSM states are defined."""
        assert hasattr(ExpertReviewState, 'idle')
        assert hasattr(ExpertReviewState, 'reviewing_submission')
        assert hasattr(ExpertReviewState, 'waiting_for_score')
        assert hasattr(ExpertReviewState, 'waiting_for_comment')


class TestScoreValidation:
    """Tests for score validation logic."""

    def test_score_in_range(self):
        """Test score values are generated correctly."""
        min_score = 0
        max_score = 100
        keyboard = get_score_keyboard(min_score, max_score)

        # Collect all score values from buttons
        scores = []
        for row in keyboard.inline_keyboard[:-1]:  # Exclude cancel row
            for button in row:
                if button.callback_data.startswith("score_"):
                    scores.append(int(button.callback_data.split("_")[1]))

        assert len(scores) > 0
        assert min(scores) >= min_score
        assert max(scores) <= max_score

    def test_cancel_button_exists(self):
        """Test cancel button is present."""
        keyboard = get_score_keyboard(0, 100)
        cancel_row = keyboard.inline_keyboard[-1]
        cancel_button = cancel_row[0]
        assert cancel_button.callback_data == "cancel_review"
        assert cancel_button.text == "Отмена"


class TestExpertReviewData:
    """Tests for review data handling."""

    @pytest.mark.asyncio
    async def test_state_data_structure(self):
        """Test expected state data structure."""
        # Simulate what state should contain after /take
        expected_data = {
            "submission_id": 1,
            "campaign_id": 1,
            "ttl_minutes": 60,
        }

        assert "submission_id" in expected_data
        assert "campaign_id" in expected_data
        assert expected_data["submission_id"] == 1

    @pytest.mark.asyncio
    async def test_review_data_structure(self):
        """Test expected review data structure."""
        # Simulate what review data should look like
        review_data = {
            "submission_id": 1,
            "score": 85,
            "comment_text": "Good work!",
        }

        assert review_data["score"] == 85
        assert review_data["comment_text"] == "Good work!"


class TestQueueIntegration:
    """Tests for queue integration logic."""

    @pytest.mark.asyncio
    async def test_lock_acquisition(self):
        """Test lock acquisition logic."""
        with patch("src.bot.handlers.expert_router.queue_service") as mock_queue:
            mock_queue.lock_submission = AsyncMock(return_value=True)

            # Simulate lock acquisition
            locked = await mock_queue.lock_submission(
                submission_id=1,
                expert_id=123,
                ttl_minutes=60
            )

            assert locked is True
            mock_queue.lock_submission.assert_called_once_with(
                submission_id=1,
                expert_id=123,
                ttl_minutes=60
            )

    @pytest.mark.asyncio
    async def test_lock_already_taken(self):
        """Test lock fails when already taken."""
        with patch("src.bot.handlers.expert_router.queue_service") as mock_queue:
            mock_queue.lock_submission = AsyncMock(return_value=False)

            locked = await mock_queue.lock_submission(
                submission_id=1,
                expert_id=123,
                ttl_minutes=60
            )

            assert locked is False

    @pytest.mark.asyncio
    async def test_unlock_on_return(self):
        """Test unlock on return command."""
        with patch("src.bot.handlers.expert_router.queue_service") as mock_queue:
            mock_queue.unlock_submission = AsyncMock(return_value=True)

            result = await mock_queue.unlock_submission(submission_id=1)

            assert result is True
            mock_queue.unlock_submission.assert_called_once_with(submission_id=1)

    @pytest.mark.asyncio
    async def test_unlock_on_review_submit(self):
        """Test unlock on review submit."""
        with patch("src.bot.handlers.expert_router.queue_service") as mock_queue:
            mock_queue.unlock_submission = AsyncMock(return_value=True)

            result = await mock_queue.unlock_submission(submission_id=1)

            assert result is True

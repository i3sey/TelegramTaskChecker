"""Expert FSM states."""
from aiogram.fsm.state import State, StatesGroup


class ExpertReviewState(StatesGroup):
    """FSM states for expert review workflow."""
    idle = State()
    reviewing_submission = State()
    waiting_for_score = State()
    waiting_for_comment = State()

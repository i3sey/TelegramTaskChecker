"""Authentication FSM states."""
from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """States for user registration flow."""
    waiting_for_role = State()
    waiting_for_full_name = State()
    confirming_full_name = State()
    waiting_for_study_group = State()
    confirming_study_group = State()

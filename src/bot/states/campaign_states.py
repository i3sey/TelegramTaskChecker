"""Campaign FSM states."""
from aiogram.fsm.state import State, StatesGroup


class CampaignCreationStates(StatesGroup):
    """States for campaign creation flow."""
    waiting_for_title = State()
    waiting_for_type = State()
    waiting_for_p2p_reviews = State()
    waiting_for_voting_type = State()
    waiting_for_min_score = State()
    waiting_for_max_score = State()
    waiting_for_ttl = State()
    waiting_for_campaign_deadline_days = State()
    waiting_for_anonymous = State()
    waiting_for_submission_format = State()


class SubmissionStates(StatesGroup):
    """States for submission flow."""
    waiting_for_campaign = State()
    waiting_for_submission = State()
    confirming_submission = State()


class OrganizerSessionState(StatesGroup):
    """FSM states for organizer session management workflow."""
    creating_session = State()
    setting_criteria = State()
    awaiting_session_name = State()
    awaiting_criteria = State()

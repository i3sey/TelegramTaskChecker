"""Keyboard templates and button-label constants."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.db.engine import session_scope
from src.db.models import CampaignType, User, UserRole
from src.bot.services.campaign_service import get_active_campaigns
from src.bot.services.review_service import count_reviewer_reviews_for_campaign
from src.bot.services.submission_service import get_user_submissions

BTN_HELP = "❓ Помощь"
BTN_PROFILE = "👤 Профиль"
BTN_ROLE = "🎭 Роль"

BTN_SUBMIT = "📤 Загрузить работу"
BTN_MY_SUBMISSIONS = "📎 Мои работы"
BTN_CAMPAIGNS = "📋 Кампании"
BTN_P2P_REVIEW = "👥 Проверить работы"
BTN_VOTE = "🗳 Голосование"

BTN_QUEUE = "📥 Очередь"
BTN_TAKE = "🟢 Взять работу"
BTN_EXPERT_STATS = "📈 Статистика"

BTN_CREATE_CAMPAIGN = "🆕 Создать кампанию"
BTN_MY_CAMPAIGNS = "📁 Мои кампании"
BTN_VIEW_RESULTS = "🔎 Результаты"
BTN_EXPORT = "📤 Экспорт"
BTN_ANALYTICS = "📊 Аналитика"
BTN_MORE = "⋯ Ещё"

BTN_HOURS_12 = "12 часов"
BTN_HOURS_24 = "24 часа"
BTN_HOURS_48 = "48 часов"
BTN_HOURS_72 = "72 часа"
BTN_SCORE_0 = "0"
BTN_SCORE_50 = "50"
BTN_SCORE_100 = "100"
BTN_SCORE_200 = "200"
BTN_SCORE_500 = "500"
BTN_ANON_YES = "✅ Да"
BTN_ANON_NO = "❌ Нет"

def _mk_markup(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=label) for label in row] for row in rows]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
    )



def build_campaign_title_keyboard() -> ReplyKeyboardMarkup:
    return _mk_markup([[BTN_PROFILE, BTN_ROLE, BTN_HELP]])

def build_campaign_min_score_keyboard() -> ReplyKeyboardMarkup:
    return _mk_markup(
        [
            [BTN_SCORE_0, BTN_SCORE_50, BTN_SCORE_100],
            [BTN_SCORE_200, BTN_PROFILE, BTN_ROLE, BTN_HELP],
        ]
    )

def build_campaign_max_score_keyboard() -> ReplyKeyboardMarkup:
    return _mk_markup(
        [
            [BTN_SCORE_100, BTN_SCORE_200, BTN_SCORE_500],
            [BTN_PROFILE, BTN_ROLE, BTN_HELP],
        ]
    )

def build_campaign_ttl_keyboard() -> ReplyKeyboardMarkup:
    return _mk_markup(
        [
            [BTN_HOURS_12, BTN_HOURS_24, BTN_HOURS_48, BTN_HOURS_72],
            [BTN_PROFILE, BTN_ROLE, BTN_HELP],
        ]
    )

def build_campaign_anonymous_keyboard() -> ReplyKeyboardMarkup:
    return _mk_markup([[BTN_ANON_YES, BTN_ANON_NO], [BTN_PROFILE, BTN_ROLE, BTN_HELP]])

def build_organizer_more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BTN_VIEW_RESULTS, callback_data="org_menu_view_results")],
            [InlineKeyboardButton(text=BTN_EXPORT, callback_data="org_menu_export")],
            [InlineKeyboardButton(text=BTN_ANALYTICS, callback_data="org_menu_analytics")],
            [InlineKeyboardButton(text="🔐 Управлять банами", callback_data="org_menu_banned_users")],
        ]
    )

def build_expert_more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Взять следующую", callback_data="expert_take_next"),
                InlineKeyboardButton(text="📈 Статистика", callback_data="expert_show_stats"),
            ],
        ]
    )

def build_post_registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_CAMPAIGNS, callback_data="menu_campaigns"),
            ],
        ]
    )

def build_full_name_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="reg_confirm_full_name"),
                InlineKeyboardButton(text="✏️ Ввести заново", callback_data="reg_reenter_full_name"),
            ]
        ]
    )

def build_study_group_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="reg_confirm_study_group"),
                InlineKeyboardButton(text="✏️ Ввести заново", callback_data="reg_reenter_study_group"),
            ]
        ]
    )

def build_submission_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="submission_confirm"),
                InlineKeyboardButton(text="✏️ Отменить и отправить заново", callback_data="submission_retry"),
            ]
        ]
    )

def build_take_submission_confirmation_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Взять на проверку",
                    callback_data=f"expert_confirm_take:{submission_id}",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="expert_cancel_take"),
            ]
        ]
    )

def build_finish_campaign_confirmation_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Завершить кампанию",
                    callback_data=f"finish_campaign_confirm:{campaign_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"finish_campaign_cancel:{campaign_id}",
                ),
            ]
        ]
    )

def build_post_submission_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_MY_SUBMISSIONS, callback_data="menu_my_submissions"),
            ]
        ]
    )

def build_post_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Взять следующую", callback_data="expert_take_next"),
                InlineKeyboardButton(text="📈 Статистика", callback_data="expert_show_stats"),
            ],
        ]
    )

def build_post_campaign_created_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_MY_CAMPAIGNS, callback_data="org_my_campaigns"),
                InlineKeyboardButton(text=BTN_CREATE_CAMPAIGN, callback_data="org_create_campaign"),
            ]
        ]
    )

def build_comment_decision_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard after score selection - comment, skip comment, ban, or cancel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Оставить комментарий", callback_data="score_proceed_comment")],
            [InlineKeyboardButton(text="✅ Отправить без комментария", callback_data="comment_skip")],
            [InlineKeyboardButton(text="⛔ Пожаловаться на студента", callback_data="score_proceed_ban")],
            [InlineKeyboardButton(text="↩️ Вернуть работу в очередь", callback_data="cancel_review")],
        ]
    )

def build_comment_final_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard after comment entry - confirm, ban, or cancel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оценку", callback_data="confirm_submit")],
            [InlineKeyboardButton(text="⛔ Пожаловаться на студента", callback_data="ban_request_init")],
            [InlineKeyboardButton(text="↩️ Вернуть работу в очередь", callback_data="cancel_review")],
        ]
    )

def build_voice_comment_action_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for expert voice comment handling."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎤 Отправить как голосовое", callback_data="voice_comment_send_raw")],
            [InlineKeyboardButton(text="📝 Распознать в текст", callback_data="voice_comment_transcribe")],
            [InlineKeyboardButton(text="↩️ Ввести заново", callback_data="voice_comment_retry")],
        ]
    )

def build_transcribed_comment_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard after transcription result is shown."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Использовать этот текст", callback_data="voice_comment_use_transcription")],
            [InlineKeyboardButton(text="✏️ Отредактировать текст", callback_data="voice_comment_edit_transcription")],
            [InlineKeyboardButton(text="🎤 Отправить как голосовое", callback_data="voice_comment_send_raw")],
            [InlineKeyboardButton(text="↩️ Ввести заново", callback_data="voice_comment_retry")],
        ]
    )

def build_ban_comment_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for entering ban reason comment."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data="ban_comment_submit")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="ban_comment_cancel")],
        ]
    )

def build_comment_skip_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for skipping comment after score selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить комментарий", callback_data="comment_skip")],
        ]
    )

def build_skip_criteria_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for skipping the whole criteria scoring stage."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить критерии", callback_data="skip_criteria_scores")],
        ]
    )

def build_review_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_submit"),
                InlineKeyboardButton(text="↩️ Вернуть в очередь", callback_data="cancel_review"),
            ]
        ]
    )

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Alias for build_review_confirmation_keyboard for compatibility."""
    return build_review_confirmation_keyboard()

def _get_student_keyboard(show_p2p_review: bool = False) -> ReplyKeyboardMarkup:
    rows = [[BTN_SUBMIT, BTN_MY_SUBMISSIONS]]

    if show_p2p_review:
        rows.append([BTN_P2P_REVIEW])

    rows.append([BTN_PROFILE, BTN_ROLE, BTN_HELP])
    return _mk_markup(rows)

async def student_has_pending_p2p_reviews(user: User) -> bool:
    """Return True if student still has required P2P reviews in any active campaign."""
    if user.role != UserRole.STUDENT:
        return False

    async with session_scope() as session:
        campaigns = await get_active_campaigns(session)
        submissions = await get_user_submissions(user.tg_id, session)

        submitted_campaign_ids = {submission.campaign_id for submission in submissions}
        p2p_campaigns = [
            campaign
            for campaign in campaigns
            if campaign.type == CampaignType.P2P and campaign.id in submitted_campaign_ids
        ]

        for campaign in p2p_campaigns:
            done = await count_reviewer_reviews_for_campaign(
                user.tg_id,
                campaign.id,
                session,
            )
            if done < campaign.p2p_reviews_required:
                return True

    return False

async def get_keyboard_for_user(user: User) -> ReplyKeyboardMarkup:
    """Return a user-specific main reply keyboard with dynamic student actions."""
    if user.role == UserRole.STUDENT:
        return _get_student_keyboard(
            show_p2p_review=await student_has_pending_p2p_reviews(user)
        )

    return get_keyboard_for_role(user.role)

def get_keyboard_for_role(role: UserRole):
    """Return a role-specific main reply keyboard."""
    if role == UserRole.STUDENT:
        return _get_student_keyboard(show_p2p_review=False)
    if role == UserRole.EXPERT:
        return _mk_markup(
            [
                [BTN_TAKE, BTN_QUEUE, BTN_EXPERT_STATS],
                [BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )
    if role == UserRole.EXPERT_ORGANIZER:
        return _mk_markup(
            [
                [BTN_TAKE, BTN_QUEUE, BTN_EXPERT_STATS],
                [BTN_CREATE_CAMPAIGN, BTN_MY_CAMPAIGNS, BTN_EXPORT],
                [BTN_VIEW_RESULTS, BTN_ANALYTICS],
                [BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )
    if role == UserRole.ORGANIZER:
        return _mk_markup(
            [
                [BTN_CREATE_CAMPAIGN, BTN_MY_CAMPAIGNS, BTN_EXPORT],
                [BTN_VIEW_RESULTS, BTN_ANALYTICS],
                [BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )

    return _mk_markup([[BTN_ROLE, BTN_PROFILE, BTN_HELP]])
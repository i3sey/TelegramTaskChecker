"""Keyboard templates and button-label constants."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.db.models import UserRole


BTN_HELP = "❓ Помощь"
BTN_PROFILE = "👤 Профиль"
BTN_ROLE = "🎭 Роль"

BTN_SUBMIT = "📤 Загрузить работу"
BTN_MY_SUBMISSIONS = "📎 Мои работы"
BTN_STATUS = "📊 Статус"
BTN_CAMPAIGNS = "📋 Кампании"
BTN_P2P_REVIEW = "👥 Проверить работы"
BTN_VOTE = "🗳 Голосование"

BTN_QUEUE = "📥 Очередь"
BTN_TAKE = "🟢 Взять работу"
BTN_EXPERT_STATS = "📈 Статистика"

BTN_CREATE_CAMPAIGN = "🆕 Создать кампанию"
BTN_MY_CAMPAIGNS = "📁 Мои кампании"
BTN_SET_CRITERIA = "⚙️ Критерии"
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
BTN_ANON_YES = "✅ Да, анонимно"
BTN_ANON_NO = "❌ Нет, открыто"


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
            [InlineKeyboardButton(text=BTN_SET_CRITERIA, callback_data="org_menu_set_criteria")],
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


def build_post_submission_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_MY_SUBMISSIONS, callback_data="menu_my_submissions"),
                InlineKeyboardButton(text=BTN_STATUS, callback_data="menu_status"),
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


def get_keyboard_for_role(role: UserRole):
    """Return a role-specific main reply keyboard."""
    if role == UserRole.STUDENT:
        return _mk_markup(
            [
                [BTN_SUBMIT, BTN_MY_SUBMISSIONS, BTN_STATUS],
                [BTN_CAMPAIGNS, BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )
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
                [BTN_VIEW_RESULTS, BTN_ANALYTICS, BTN_SET_CRITERIA],
                [BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )
    if role == UserRole.ORGANIZER:
        return _mk_markup(
            [
                [BTN_CREATE_CAMPAIGN, BTN_MY_CAMPAIGNS, BTN_EXPORT],
                [BTN_VIEW_RESULTS, BTN_ANALYTICS, BTN_SET_CRITERIA],
                [BTN_PROFILE, BTN_ROLE, BTN_HELP],
            ]
        )

    return _mk_markup([[BTN_ROLE, BTN_PROFILE, BTN_HELP]])




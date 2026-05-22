from src.bot.models import UserRole, CampaignType, SubmissionStatus


ROLE_LABELS = {
    UserRole.STUDENT: "🎓 Студент",
    UserRole.EXPERT: "🧑‍🏫 Эксперт",
    UserRole.EXPERT_ORGANIZER: "🧑‍🏫🧑‍💼 Эксперт-организатор",
    UserRole.ORGANIZER: "🧑‍💼 Организатор",
}

CAMPAIGN_TYPE_LABELS = {
    CampaignType.EXPERT: "📊 Экспертная проверка",
    CampaignType.P2P: "👥 P2P-проверка",
    CampaignType.VOTING: "🗳 Голосование",
}

VOTING_TYPE_LABELS = {
    "like": "👍 Лайк",
    "score": "⭐ Оценка",
}

SUBMISSION_STATUS_META = {
    SubmissionStatus.UPLOADED: ("🟡", "Ожидает проверки", "Работа принята и ждёт проверяющего."),
    SubmissionStatus.IN_REVIEW: ("🔵", "На проверке", "Работу уже взяли в работу."),
    SubmissionStatus.REVIEWED: ("✅", "Проверена", "Проверка завершена, результат сохранён."),
    SubmissionStatus.REJECTED: ("❌", "Отклонена", "Нужно загрузить файл заново."),
}


def role_label(role: UserRole) -> str:
    return ROLE_LABELS.get(role, str(role))


def campaign_type_label(campaign_type: CampaignType) -> str:
    return CAMPAIGN_TYPE_LABELS.get(campaign_type, str(campaign_type))


def voting_type_label(voting_type: str | None) -> str:
    if not voting_type:
        return "Не задан"
    return VOTING_TYPE_LABELS.get(voting_type, voting_type)


def submission_status_meta(status: SubmissionStatus):
    return SUBMISSION_STATUS_META.get(status, ("⚪", str(status), ""))


def submission_status_line(status: SubmissionStatus) -> str:
    emoji, label, hint = submission_status_meta(status)
    if hint:
        return f"{emoji} <b>{label}</b>\n{hint}"
    return f"{emoji} <b>{label}</b>"


def format_ttl_minutes(ttl_minutes: int) -> str:
    if ttl_minutes % 1440 == 0:
        days = ttl_minutes // 1440
        return f"{days} дн." if days > 1 else "1 день"
    if ttl_minutes % 60 == 0:
        hours = ttl_minutes // 60
        return f"{hours} ч."
    return f"{ttl_minutes} мин."


def registration_welcome_text() -> str:
    return (
        "👋 <b>Добро пожаловать в сервис проверки работ!</b>\n\n"
        "Здесь можно сдавать работы, проверять их и управлять кампаниями.\n"
        "Для начала выберите роль."
    )


def help_text_for_role(role: UserRole | None) -> str:
    common = (
        "📖 <b>Как пользоваться ботом</b>\n\n"
        "<b>Общие команды:</b>\n"
        "/start — открыть главное меню\n"
        "/profile — посмотреть профиль\n"
        "/role — сменить роль\n"
        "/help — показать справку\n"
        "/cancel — отменить текущий шаг\n"
    )
    if role == UserRole.STUDENT:
        return (
            common
            + "\n<b>Для студента:</b>\n"
            "/campaigns — посмотреть активные кампании\n"
            "/submit — загрузить работу\n"
            "/my_submissions — посмотреть все свои работы\n\n"
            "/p2p — проверить работы других (если кампания P2P)\n"
            "/vote — проголосовать в кампании\n\n"
            "Совет: сначала откройте кампании, затем загрузите работу."
        )
    if role in (UserRole.EXPERT, UserRole.EXPERT_ORGANIZER):
        return (
            common
            + "\n<b>Для эксперта:</b>\n"
            "/queue — посмотреть очередь\n"
            "/take — взять работу на проверку\n"
            "/return — вернуть текущую работу в очередь\n"
            "/expert_stats — посмотреть статистику\n\n"
            "Порядок работы: взять работу → поставить оценку → оставить комментарий → подтвердить."
        )
    if role in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
        return (
            common
            + "\n<b>Для организатора:</b>\n"
            "/create_campaign — создать кампанию\n"
            "/my_campaigns — посмотреть свои кампании\n"
            "/invites — узнать про инвайты\n"
            "/view_results — результаты\n"
            "/export — экспорт\n\n"
            "Совет: после создания кампании сразу сохраните студенческий и экспертный инвайты."
        )
    return common + "\n\nЕсли вы ещё не зарегистрированы — начните с /start."


def unavailable_role_text() -> str:
    return (
        "⛔ <b>Доступ ограничен</b>\n\n"
        "Эта функция недоступна для вашей текущей роли.\n"
        "Если роль выбрана неверно, используйте /role."
    )


def fallback_text(is_registered: bool) -> str:
    if is_registered:
        return (
            "🤔 Я не понял это сообщение.\n\n"
            "Пожалуйста, используйте кнопки меню или команду /help."
        )
    return (
        "👋 Похоже, вы ещё не начали работу с ботом.\n\n"
        "Используйте /start, чтобы зарегистрироваться и открыть меню."
    )


def profile_text(user) -> str:
    access = "✅ Есть" if (
        user.role == UserRole.ORGANIZER
        or user.role == UserRole.EXPERT_ORGANIZER
        or (user.registered_by_code and (
            (user.role == UserRole.STUDENT and user.invite_role == "student")
            or (user.role == UserRole.EXPERT and user.invite_role == "expert")
        ))
    ) else "❌ Нет"
    return (
        "👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user.tg_id}</code>\n"
        f"🙍 Имя: <b>{user.full_name}</b>\n"
        f"🎓 Группа: <b>{user.study_group or 'Не указана'}</b>\n"
        f"🎭 Роль: <b>{role_label(user.role)}</b>\n"
        f"📌 Статус аккаунта: {'✅ Активен' if not user.is_banned else '⛔ Заблокирован'}\n"
        f"🔐 Доступ к функциям роли: {access}"
    )
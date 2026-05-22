"""Organizer handler router for session and results management."""

from html import escape
from typing import Any

from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.keyboards import (
    BTN_ANALYTICS,
    BTN_CREATE_CAMPAIGN,
    BTN_EXPORT,
    BTN_MORE,
    BTN_MY_CAMPAIGNS,
    BTN_VIEW_RESULTS,
    build_organizer_more_keyboard,
    get_keyboard_for_user,
)
from src.bot.services.campaign_service import (
    CampaignService,
    get_campaign_export_rows,
    get_campaign_results,
    get_completed_campaigns_for_export,
)
from src.bot.services.user_service import get_all_users, get_user, ban_user, unban_user
from src.bot.services.xlsx_export_service import XlsxExportService
from src.bot.utils.logging import logger
from src.db.engine import session_scope
from src.db.models import UserRole

EXPORT_BASE_HEADERS = [
    "ID кампании",
    "Название кампании",
    "Тип кампании",
    "ID работы",
    "Статус работы",
    "Дата отправки работы",
    "Telegram ID автора",
    "Автор",
    "Учебная группа",
    "Telegram ID проверяющего",
    "Проверяющий",
    "Оценка",
    "Комментарий",
    "Причина бана",
    "Дата проверки",
]

CAMPAIGN_TYPE_LABELS = {
    "expert": "Экспертная проверка",
    "p2p": "Взаимопроверка",
    "voting": "Голосование",
}

SUBMISSION_STATUS_LABELS = {
    "uploaded": "Загружена",
    "in_review": "На проверке",
    "reviewed": "Проверена",
    "rejected": "Отклонена",
}

xlsx_export_service = XlsxExportService()

def _format_export_value(value: Any) -> Any:
    """Normalize values for human-readable spreadsheet export."""
    if value is None:
        return ""
    return value

def _extract_campaign_criteria_names(rows: list[dict[str, Any]]) -> list[str]:
    """Extract ordered campaign criteria names from export rows."""
    for row in rows:
        criteria_names = row.get("criteria_names") or row.get("criteria") or []
        if criteria_names:
            return [str(name).strip() for name in criteria_names if str(name).strip()]
    return []

def _build_export_headers(rows: list[dict[str, Any]]) -> list[str]:
    """Build spreadsheet headers with named dynamic criteria columns."""
    criteria_names = _extract_campaign_criteria_names(rows)
    return EXPORT_BASE_HEADERS + [
        f"Критерий: {criterion_name} — оценка эксперта"
        for criterion_name in criteria_names
    ]

def _build_export_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """Convert export row dictionaries into human-readable spreadsheet rows."""
    criteria_names = _extract_campaign_criteria_names(rows)

    export_rows: list[list[Any]] = []
    for row in rows:
        criteria_scores_map = CampaignService.map_criteria_scores_by_name(
            row.get("criteria_scores")
        )
        export_rows.append(
            [
                _format_export_value(row.get("campaign_id")),
                _format_export_value(row.get("campaign_title")),
                CAMPAIGN_TYPE_LABELS.get(
                    str(row.get("campaign_type") or ""),
                    _format_export_value(row.get("campaign_type")),
                ),
                _format_export_value(row.get("submission_id")),
                SUBMISSION_STATUS_LABELS.get(
                    str(row.get("submission_status") or ""),
                    _format_export_value(row.get("submission_status")),
                ),
                _format_export_value(row.get("submission_created_at")),
                _format_export_value(row.get("author_tg_id")),
                _format_export_value(row.get("author_full_name")),
                _format_export_value(row.get("author_study_group")),
                _format_export_value(row.get("reviewer_tg_id")),
                _format_export_value(row.get("reviewer_full_name")),
                _format_export_value(row.get("score")),
                _format_export_value(row.get("comment_text")),
                _format_export_value(row.get("ban_comment")),
                _format_export_value(row.get("review_created_at")),
                *[
                    _format_export_value(criteria_scores_map.get(criterion_name, ""))
                    for criterion_name in criteria_names
                ],
            ]
        )

    return export_rows

def _build_completed_campaigns_export_keyboard(campaigns: list[Any]) -> types.InlineKeyboardMarkup:
    """Build inline keyboard for completed campaigns export."""
    builder = InlineKeyboardBuilder()

    for campaign in campaigns:
        builder.button(
            text=f"#{campaign.id} · {campaign.title[:40]}",
            callback_data=f"org_export_campaign_{campaign.id}",
        )

    builder.adjust(1)
    return builder.as_markup()

router = Router()
router.name = "organizer_router"

@router.message(Command("invites"))
async def cmd_invites(message: types.Message) -> None:
    """Explain that campaign invites are generated automatically."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    await message.answer(
        "🔗 <b>Инвайты привязаны к кампании.</b>\n\n"
        "Они создаются автоматически сразу после создания кампании и отправляются вместе с уведомлением.\n"
        "Чтобы получить новые ссылки, создайте кампанию или откройте её из списка кампаний.",
        parse_mode="HTML",
    )

def _format_results_text(results: list[dict]) -> str:
    if not results:
        return "📭 <b>Результаты кампаний отсутствуют</b>"

    blocks: list[str] = ["📊 <b>Результаты кампаний</b>"]
    for item in results:
        campaign = item["campaign"]
        status_summary = item["status_summary"]

        comments = item["comments"]
        comments_text = (
            "\n".join(f"• {escape(comment)}" for comment in comments[:5])
            if comments
            else "• нет комментариев"
        )

        status_text = "\n".join(
            [
                f"• Загружено: {status_summary.get('uploaded', 0)}",
                f"• На проверке: {status_summary.get('in_review', 0)}",
                f"• Проверено: {status_summary.get('reviewed', 0)}",
                f"• Отклонено: {status_summary.get('rejected', 0)}",
            ]
        )

        blocks.append(
            f"\n<b>{escape(campaign.title)}</b>\n"
            f"📌 Тип: {campaign.type.value}\n"
            f"📥 Формат сдачи: {campaign.submission_format.value}\n"
            f"♻️ Замена до проверки: {'Да' if campaign.allow_resubmission_before_review else 'Нет'}\n"
            f"🔁 Пересдача после проверки: {'Да' if campaign.allow_resubmission_after_review else 'Нет'}\n"
            f"📝 Работ: {item['total_submissions']}\n"
            f"✅ Проверено: {item['reviewed_submissions']}\n"
            f"⭐ Средняя оценка: {item['avg_score']:.2f}\n"
            f"💬 Комментарии:\n{comments_text}\n"
            f"📈 Сводка по статусам:\n{status_text}"
        )

    return "\n".join(blocks)

@router.message(Command("view_results"))
async def cmd_view_results(message: types.Message) -> None:
    """
    Handle /view_results command to see all feedback and results.

    Displays compiled feedback and ratings from all reviews.
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

        results = await get_campaign_results(session)

    await message.answer(_format_results_text(results), parse_mode="HTML")

@router.message(Command("export"))
async def cmd_export(message: types.Message) -> None:
    """Show completed campaigns available for XLSX export."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

        campaigns = await get_completed_campaigns_for_export(session)

    if not campaigns:
        await message.answer("📭 Нет завершённых кампаний для экспорта.")
        return

    await message.answer(
        "📤 <b>Экспорт в XLSX</b>\n\n"
        "Выберите завершённую кампанию для выгрузки:",
        parse_mode="HTML",
        reply_markup=_build_completed_campaigns_export_keyboard(campaigns),
    )

@router.message(Command("manage_users"))
async def cmd_manage_users(message: types.Message) -> None:
    """
    Handle /manage_users command to manage system users.
    
    Args:
        message: Telegram message object
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    # TODO: Добавить список пользователей, поиск, бан/разбан и при необходимости изменение ролей.
    await message.answer(
        "⚠️ Управление пользователями временно недоступно.\n"
        "Функция будет добавлена позже."
    )

@router.message(Command("analytics"))
async def cmd_analytics(message: types.Message) -> None:
    """
    Handle /analytics command to view system analytics.
    
    Args:
        message: Telegram message object
    """
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return

    # TODO: Добавить аналитику по кампаниям и пользователям: метрики активности, проверок и результатов.
    await message.answer(
        "⚠️ Аналитика временно недоступна.\n"
        "Функция будет добавлена позже."
    )

@router.message(F.text == BTN_CREATE_CAMPAIGN)
async def btn_create_campaign(message: types.Message, state: FSMContext) -> None:
    from src.bot.handlers.campaign_router import cmd_create_campaign

    await cmd_create_campaign(message, state)

@router.message(F.text == BTN_MY_CAMPAIGNS)
async def btn_my_campaigns(message: types.Message) -> None:
    from src.bot.handlers.campaign_router import cmd_my_campaigns

    await cmd_my_campaigns(message)

@router.message(F.text == BTN_VIEW_RESULTS)
async def btn_view_results(message: types.Message) -> None:
    await cmd_view_results(message)

@router.message(F.text == BTN_EXPORT)
async def btn_export(message: types.Message) -> None:
    await cmd_export(message)

@router.message(F.text == BTN_ANALYTICS)
async def btn_analytics(message: types.Message) -> None:
    await cmd_analytics(message)

@router.message(F.text == BTN_MORE)
async def btn_more(message: types.Message) -> None:
    await message.answer(
        "⚙️ <b>Дополнительные действия</b>",
        parse_mode="HTML",
        reply_markup=build_organizer_more_keyboard(),
    )

@router.callback_query(F.data == "org_menu_view_results")
async def org_menu_view_results(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_view_results(callback.message)
    await callback.answer()

@router.callback_query(F.data == "org_menu_export")
async def org_menu_export(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_export(callback.message)
    await callback.answer()

@router.callback_query(F.data.startswith("org_export_campaign_"))
async def org_export_campaign(callback: types.CallbackQuery) -> None:
    """Export selected completed campaign to XLSX."""
    if not callback.message or not callback.from_user:
        await callback.answer("❌ Ошибка: не удалось обработать запрос", show_alert=True)
        return

    campaign_id_str = callback.data.removeprefix("org_export_campaign_")
    try:
        campaign_id = int(campaign_id_str)
    except ValueError:
        await callback.answer("❌ Некорректный идентификатор кампании", show_alert=True)
        return

    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return

        try:
            campaign, export_rows = await get_campaign_export_rows(campaign_id, session)
        except ValueError:
            await callback.answer("⚠️ Можно экспортировать только завершённые кампании", show_alert=True)
            return

        if campaign is None:
            await callback.answer("❌ Кампания не найдена", show_alert=True)
            return

    await callback.answer("⏳ Готовлю XLSX...")

    try:
        export_header = _build_export_headers(export_rows)
        export_table_rows = _build_export_rows(export_rows)

        filename, file_buffer, written_rows = xlsx_export_service.build_export_file(
            campaign_id=campaign.id,
            campaign_title=campaign.title,
            rows=export_table_rows,
            header=export_header,
        )
        export_file = BufferedInputFile(
            file=file_buffer.getvalue(),
            filename=filename,
        )
    except Exception as e:
        logger.exception(f"Unexpected XLSX export error for campaign {campaign.id}: {e}")
        await callback.message.answer(
            "❌ Не удалось сформировать XLSX-файл. Повторите позже."
        )
        return

    await callback.message.answer_document(
        document=export_file,
        caption=(
            "✅ <b>Экспорт завершён</b>\n\n"
            f"Кампания: <b>{escape(campaign.title)}</b>\n"
            f"ID кампании: <code>{campaign.id}</code>\n"
            f"Выгружено строк: <b>{written_rows}</b>"
        ),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "org_menu_analytics")
async def org_menu_analytics(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_analytics(callback.message)
    await callback.answer()

@router.callback_query(F.data == "org_menu_banned_users")
async def org_menu_banned_users(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    await cmd_banned_users(callback.message)
    await callback.answer()

# Ban/Unban management handlers
@router.callback_query(F.data.startswith("org_ban_student_"))
async def handle_ban_confirmation(callback: types.CallbackQuery, bot: Bot) -> None:
    """Handle ban confirmation from organizer."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    # Parse callback data: org_ban_student_{student_id}_{submission_id}
    parts = callback.data.removeprefix("org_ban_student_").split("_")
    if len(parts) < 2:
        await callback.answer("❌ Некорректный запрос", show_alert=True)
        return
    
    try:
        student_id = int(parts[0])
        submission_id = int(parts[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    async with session_scope() as session:
        student = await get_user(tg_id=student_id, session=session)
        if not student:
            await callback.answer(f"❌ Студент с ID {student_id} не найден", show_alert=True)
            return
        
        if student.is_banned:
            await callback.answer(f"⚠️ Студент {student.full_name} уже забанен", show_alert=True)
            return
        
        # Ban the student
        await ban_user(student_id, session)
    
    logger.info(f"Organizer {callback.from_user.id} banned student {student_id} (submission {submission_id})")
    
    # Notify organizer
    await callback.answer(f"✅ Студент {student.full_name} забанен", show_alert=True)
    
    # Update the message
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Студент забанен организатором {user.full_name}</b>",
        parse_mode="HTML",
    )
    
    # Try to notify the banned student
    try:
        await bot.send_message(
            chat_id=student_id,
            text="⛔ <b>Вы были заблокированы в системе</b>\n\n"
                 "Причина: нарушение правил платформы.\n\n"
                 "Если это ошибка, свяжитесь с администратором.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Failed to notify banned student {student_id}: {e}")

@router.callback_query(F.data.startswith("org_reject_ban_"))
async def handle_ban_rejection(callback: types.CallbackQuery) -> None:
    """Handle ban request rejection."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    submission_id_str = callback.data.removeprefix("org_reject_ban_")
    
    try:
        submission_id = int(submission_id_str)
    except ValueError:
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    logger.info(f"Organizer {callback.from_user.id} rejected ban request for submission {submission_id}")
    
    # Notify organizer
    await callback.answer("✅ Жалоба отклонена", show_alert=True)
    
    # Update the message
    await callback.message.edit_text(
        callback.message.text + f"\n\n❌ <b>Жалоба отклонена организатором {user.full_name}</b>",
        parse_mode="HTML",
    )

@router.message(Command("banned_users"))
async def cmd_banned_users(message: types.Message) -> None:
    """Show list of banned users and allow unban."""
    async with session_scope() as session:
        user = await get_user(tg_id=message.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await message.answer("❌ Эта команда доступна только организаторам.")
            return
        
        all_users = await get_all_users(session)
        banned_users = [u for u in all_users if u.is_banned]
    
    if not banned_users:
        await message.answer("✅ Нет забанённых пользователей.")
        return
    
    text = "⛔ <b>Забанённые пользователи</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    
    for banned_user in banned_users:
        text += f"• <code>{banned_user.tg_id}</code> — <b>{banned_user.full_name}</b>\n"
        builder.button(
            text=f"✅ Разбанить {banned_user.full_name[:20]}",
            callback_data=f"org_unban_{banned_user.tg_id}",
        )
    
    builder.adjust(1)
    
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )

@router.callback_query(F.data.startswith("org_unban_"))
async def handle_unban(callback: types.CallbackQuery) -> None:
    """Handle unban action."""
    if not callback.from_user:
        await callback.answer("❌ Ошибка аутентификации", show_alert=True)
        return
    
    async with session_scope() as session:
        user = await get_user(tg_id=callback.from_user.id, session=session)
        if not user or user.role not in (UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER):
            await callback.answer("❌ Доступ запрещен", show_alert=True)
            return
    
    student_id_str = callback.data.removeprefix("org_unban_")
    
    try:
        student_id = int(student_id_str)
    except ValueError:
        await callback.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    async with session_scope() as session:
        student = await get_user(tg_id=student_id, session=session)
        if not student:
            await callback.answer(f"❌ Студент с ID {student_id} не найден", show_alert=True)
            return
        
        if not student.is_banned:
            await callback.answer(f"⚠️ Студент {student.full_name} не забанен", show_alert=True)
            return
        
        # Unban the student
        await unban_user(student_id, session)
    
    logger.info(f"Organizer {callback.from_user.id} unbanned student {student_id}")
    
    # Notify organizer
    await callback.answer(f"✅ Студент {student.full_name} разбанен", show_alert=True)
    
    # Update the message
    text = callback.message.text or ""
    text = text.replace(f"<code>{student_id}</code> — <b>{student.full_name}</b>", "")
    
    # Show updated list or message about no banned users
    if len(text.strip()) < 50:
        await callback.message.edit_text("✅ Нет забанённых пользователей.")
    else:
        await callback.message.edit_text(text, parse_mode="HTML")
    
    # Try to notify the unbanned student
    keyboard = await get_keyboard_for_user(student) if student else None
    
    try:
        await callback.bot.send_message(
            chat_id=student_id,
            text="✅ <b>Вы были разблокированы в системе</b>\n\n"
                 "Теперь вы можете снова использовать бота.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"Failed to notify unbanned student {student_id}: {e}")
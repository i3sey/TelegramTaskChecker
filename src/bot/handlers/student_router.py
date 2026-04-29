"""Student handler router for lightweight student commands."""

from aiogram import Router, types
from aiogram.filters import Command

from src.db.engine import session_scope
from src.services.submission_service import get_user_submissions
from src.services.campaign_service import get_campaign


router = Router()
router.name = "student_router"


@router.message(Command("status"))
async def cmd_status(message: types.Message) -> None:
    """Show brief status of the latest submission."""
    tg_id = message.from_user.id

    async with session_scope() as session:
        submissions = await get_user_submissions(tg_id, session)

        if not submissions:
            await message.answer(
                "📭 У вас пока нет загруженных работ. Используйте /submit."
            )
            return

        latest = submissions[0]
        campaign = await get_campaign(latest.campaign_id, session)
        campaign_title = campaign.title if campaign else f"Кампания #{latest.campaign_id}"

        status_emoji = {
            "uploaded": "🟡",
            "in_review": "🔵",
            "reviewed": "✅",
            "rejected": "❌",
        }.get(latest.status.value, "⚪")

        await message.answer(
            "📊 <b>Статус последней работы</b>\n\n"
            f"📋 Кампания: <b>{campaign_title}</b>\n"
            f"📎 ID: <code>{latest.id}</code>\n"
            f"📊 Статус: {status_emoji} {latest.status.value}\n"
            f"📅 Дата: {latest.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Полный список: /my_submissions",
            parse_mode="HTML",
        )

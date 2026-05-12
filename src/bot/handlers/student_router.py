"""Student handler router for lightweight student commands."""

from aiogram import F, Router, types
from aiogram.filters import Command

from src.bot.keyboards import BTN_STATUS, build_post_submission_keyboard
from src.bot.ui import submission_status_meta
from src.db.engine import session_scope
from src.bot.services.campaign_service import get_campaign
from src.bot.services.submission_service import get_user_submissions

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
                "📭 <b>У вас пока нет загруженных работ.</b>\n\n"
                "Чтобы отправить первую работу, используйте /submit.",
                parse_mode="HTML",
            )
            return

        latest = submissions[0]
        campaign = await get_campaign(latest.campaign_id, session)
        campaign_title = campaign.title if campaign else f"Кампания #{latest.campaign_id}"
        status_emoji, status_label, status_hint = submission_status_meta(latest.status)

        await message.answer(
            "📊 <b>Статус последней работы</b>\n\n"
            f"📋 Кампания: <b>{campaign_title}</b>\n"
            f"🆔 Работа: <code>{latest.id}</code>\n"
            f"📌 Статус: {status_emoji} <b>{status_label}</b>\n"
            f"💬 Что дальше: {status_hint}\n"
            f"🕒 Загружена: {latest.created_at.strftime('%d.%m.%Y %H:%M')}",
            parse_mode="HTML",
            reply_markup=build_post_submission_keyboard(),
        )


@router.message(F.text == BTN_STATUS)
async def btn_status(message: types.Message) -> None:
    await cmd_status(message)


@router.callback_query(F.data == "menu_status")
async def menu_status(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer("❌ Ошибка: не удалось получить сообщение", show_alert=True)
        return
    
    tg_id = callback.from_user.id
    async with session_scope() as session:
        submissions = await get_user_submissions(tg_id, session)

        if not submissions:
            await callback.message.answer(
                "📭 <b>У вас пока нет загруженных работ.</b>\n\n"
                "Чтобы отправить первую работу, используйте /submit.",
                parse_mode="HTML",
            )
        else:
            latest = submissions[0]
            campaign = await get_campaign(latest.campaign_id, session)
            campaign_title = campaign.title if campaign else f"Кампания #{latest.campaign_id}"
            status_emoji, status_label, status_hint = submission_status_meta(latest.status)

            await callback.message.answer(
                "📊 <b>Статус последней работы</b>\n\n"
                f"📋 Кампания: <b>{campaign_title}</b>\n"
                f"🆔 Работа: <code>{latest.id}</code>\n"
                f"📌 Статус: {status_emoji} <b>{status_label}</b>\n"
                f"💬 Что дальше: {status_hint}\n"
                f"🕒 Загружена: {latest.created_at.strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML",
            )
    
    await callback.answer()

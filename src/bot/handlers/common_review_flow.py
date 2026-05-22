"""Shared helpers for expert and P2P review flows."""

from __future__ import annotations

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.utils.logging import logger
from src.db.models import Submission, SubmissionFormat

async def send_submission_content(
    message: types.Message,
    submission: Submission,
    caption: str,
) -> None:
    """Send submission content to reviewer with graceful fallback."""
    submission_type = submission.submission_type or SubmissionFormat.DOCUMENT

    if submission_type == SubmissionFormat.TEXT:
        text_body = (submission.text_content or "").strip() or "—"
        await message.answer(
            f"{caption}\n\n📝 <b>Текст работы:</b>\n<blockquote>{text_body}</blockquote>",
            parse_mode="HTML",
        )
        return

    if submission_type == SubmissionFormat.LINK:
        await message.answer(
            f"{caption}\n\n🔗 <b>Ссылка:</b>\n{submission.external_url or '—'}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    try:
        if submission_type == SubmissionFormat.PHOTO and submission.file_id:
            await message.answer_photo(
                photo=submission.file_id,
                caption=caption,
                parse_mode="HTML",
            )
            return

        if submission.file_id:
            await message.answer_document(
                document=submission.file_id,
                caption=caption,
                parse_mode="HTML",
            )
            return

        await message.answer(
            caption + "\n\n⚠️ У работы отсутствует вложение для отправки.",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning(
            f"Failed to send submission {submission.id} "
            f"of type {submission_type.value}: {exc}"
        )
        fallback = caption + "\n\n⚠️ Вложение не удалось отправить."
        if submission_type == SubmissionFormat.LINK and submission.external_url:
            fallback += f"\n🔗 Ссылка: {submission.external_url}"
        elif submission_type == SubmissionFormat.TEXT and submission.text_content:
            fallback += f"\n📝 Текст:\n<blockquote>{submission.text_content}</blockquote>"
        elif submission.file_name:
            fallback += f"\n📄 Файл: <b>{submission.file_name}</b>"
        await message.answer(fallback, parse_mode="HTML")

def build_confirm_cancel_keyboard(
    *,
    confirm_callback: str,
    cancel_callback: str,
    confirm_text: str = "✅ Подтвердить",
    cancel_text: str = "↩️ Отменить",
) -> InlineKeyboardMarkup:
    """Build a simple one-row confirm/cancel keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=confirm_text, callback_data=confirm_callback),
                InlineKeyboardButton(text=cancel_text, callback_data=cancel_callback),
            ]
        ]
    )

def format_score_saved_text(
    *,
    score: int,
    min_score: int,
    max_score: int,
    next_step_text: str,
) -> str:
    """Format a generic message after score was saved."""
    return (
        f"✅ <b>Оценка сохранена: {score}</b>\n\n"
        f"Диапазон оценок: {min_score}–{max_score}\n\n"
        f"{next_step_text}"
    )

def format_comment_saved_text(
    *,
    comment_text: str,
    next_step_text: str,
) -> str:
    """Format a generic message after text comment was saved."""
    return (
        "💬 <b>Комментарий сохранён.</b>\n\n"
        f"Текст: {comment_text}\n\n"
        f"{next_step_text}"
    )

def format_criteria_scores_block(
    criteria_scores: list[dict[str, int | str]] | None,
) -> str:
    """Format ordered per-criterion scores block for review summaries."""
    lines: list[str] = []

    for item in criteria_scores or []:
        if not isinstance(item, dict):
            continue
        criterion_name = str(item.get("name") or "").strip()
        criterion_score = item.get("score")

        if not criterion_name or criterion_score in (None, ""):
            continue

        lines.append(f"• {criterion_name} — {criterion_score}")

    if not lines:
        return ""

    return "📋 <b>Критерии:</b>\n" + "\n".join(lines)

def format_review_saved_summary(
    *,
    submission_id: int,
    score: int,
    comment_summary: str,
    criteria_scores: list[dict[str, int | str]] | None = None,
    extra_text: str | None = None,
) -> str:
    """Format a generic successful review summary."""
    text = "✅ <b>Рецензия сохранена!</b>\n\n" f"🆔 Работа: <code>{submission_id}</code>\n"

    criteria_block = format_criteria_scores_block(criteria_scores)
    if criteria_block:
        text += f"{criteria_block}\n"

    text += (
        f"⭐ Итоговая оценка: <b>{score}</b>\n"
        f"💬 Комментарий: <b>{comment_summary}</b>"
    )

    if extra_text:
        text += f"\n\n{extra_text}"
    return text

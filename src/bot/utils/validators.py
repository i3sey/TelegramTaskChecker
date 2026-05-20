"""Validation utilities for user input and data verification."""

import os
from typing import Literal, Optional
from urllib.parse import urlparse

from aiogram import types

from src.bot.models import Campaign, SubmissionFormat
from src.bot.utils.logging import logger


# Allowed file extensions (lowercase)
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".jpg", ".png"}
PHOTO_DOCUMENT_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Maximum file size: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 * 1024 * 1024 = 52,428,800 bytes

MAX_TEXT_SUBMISSION_LENGTH = 4000
MIN_TEXT_SUBMISSION_LENGTH = 3


def validate_user_role(role: str) -> bool:
    """
    Validate if the provided role is one of the accepted roles.
    
    Args:
        role: User role to validate
        
    Returns:
        True if role is valid, False otherwise
    """
    valid_roles = {"student", "expert", "organizer"}
    return role.lower() in valid_roles


def validate_submission(submission_data: dict) -> tuple[bool, str]:
    """
    Validate submission data structure and content.
    
    Args:
        submission_data: Dictionary containing submission data
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = {"user_id", "content"}
    
    if not isinstance(submission_data, dict):
        return False, "Submission data must be a dictionary"
    
    missing_fields = required_fields - set(submission_data.keys())
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    if not submission_data["content"].strip():
        return False, "Submission content cannot be empty"
    
    return True, ""


def validate_feedback(feedback_data: dict) -> tuple[bool, str]:
    """
    Validate feedback data structure and content.
    
    Args:
        feedback_data: Dictionary containing feedback data
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = {"reviewer_id", "submission_id", "content"}
    
    if not isinstance(feedback_data, dict):
        return False, "Feedback data must be a dictionary"
    
    missing_fields = required_fields - set(feedback_data.keys())
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    if not feedback_data["content"].strip():
        return False, "Feedback content cannot be empty"
    
    if "rating" in feedback_data:
        rating = feedback_data["rating"]
        if not isinstance(rating, (int, float)) or not (1 <= rating <= 5):
            return False, "Rating must be between 1 and 5"

    return True, ""


# File validation functions

def get_file_extension(filename: str) -> str:
    """
    Extract file extension from filename.

    Args:
        filename: Name of the file

    Returns:
        Lowercase file extension including the dot (e.g., '.pdf')
    """
    _, ext = os.path.splitext(filename)
    return ext.lower()


def validate_file_extension(filename: str) -> bool:
    """
    Validate if file extension is allowed.

    Args:
        filename: Name of the file

    Returns:
        True if extension is allowed, False otherwise
    """
    ext = get_file_extension(filename)
    is_valid = ext in ALLOWED_EXTENSIONS

    if not is_valid:
        logger.warning(
            f"Invalid file extension: '{ext}' "
            f"Allowed: {ALLOWED_EXTENSIONS}"
        )

    return is_valid


def validate_file_size(size: int) -> bool:
    """
    Validate if file size is within allowed limit.

    Args:
        size: File size in bytes

    Returns:
        True if size is within limit, False otherwise
    """
    is_valid = size <= MAX_FILE_SIZE

    if not is_valid:
        size_mb = size / (1024 * 1024)
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        logger.warning(
            f"File size {size_mb:.2f} MB exceeds limit of {max_mb:.2f} MB"
        )

    return is_valid


def normalize_allowed_extensions(allowed_extensions: str | None) -> set[str]:
    """
    Normalize campaign allowed extensions string into a lowercase set.

    Args:
        allowed_extensions: Comma-separated extensions or None

    Returns:
        Set of normalized extensions with leading dot
    """
    if not allowed_extensions:
        return set()

    normalized: set[str] = set()
    for part in allowed_extensions.split(","):
        extension = part.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        normalized.add(extension)

    return normalized

def validate_file(
    filename: str,
    size: int,
    allowed_extensions: set[str] | None = None,
) -> tuple[bool, Optional[str]]:
    """
    Validate both file extension and size.

    Args:
        filename: Name of the file
        size: File size in bytes
        allowed_extensions: Explicit set of allowed extensions for campaign

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    extensions = allowed_extensions or ALLOWED_EXTENSIONS
    ext = get_file_extension(filename)

    if ext not in extensions:
        return False, (
            "❌ Формат файла не поддерживается.\n"
            f"Разрешены: {', '.join(sorted(extensions))}"
        )

    if not validate_file_size(size):
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        return False, f"❌ Файл слишком большой.\nМаксимум: {int(max_mb)} МБ"

    return True, None


def validate_text_submission(text: str | None) -> tuple[bool, Optional[str]]:
    """
    Validate plain text submission.

    Args:
        text: Message text

    Returns:
        Tuple of validation result and error message
    """
    normalized = (text or "").strip()
    if not normalized:
        return False, "❌ Отправьте текст работы одним сообщением."

    if len(normalized) < MIN_TEXT_SUBMISSION_LENGTH:
        return False, (
            "❌ Текст слишком короткий.\n"
            f"Минимум: {MIN_TEXT_SUBMISSION_LENGTH} символа(ов)."
        )

    if len(normalized) > MAX_TEXT_SUBMISSION_LENGTH:
        return False, (
            "❌ Текст слишком длинный.\n"
            f"Максимум: {MAX_TEXT_SUBMISSION_LENGTH} символов."
        )

    return True, None

def validate_url_submission(url: str | None) -> tuple[bool, Optional[str]]:
    """
    Validate URL submission.

    Args:
        url: URL in message text

    Returns:
        Tuple of validation result and error message
    """
    normalized = (url or "").strip()
    if not normalized:
        return False, "❌ Отправьте ссылку одним сообщением."

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "❌ Некорректная ссылка. Используйте полный URL, например https://example.com"

    return True, None

def validate_submission_message(
    campaign: Campaign,
    message: types.Message,
) -> tuple[bool, Optional[str], dict]:
    """
    Validate a submission message according to campaign format.

    Args:
        campaign: Campaign configuration
        message: Telegram message with submission

    Returns:
        Tuple of (is_valid, error_message, parsed_payload)
    """
    parsed_payload: dict = {}

    if campaign.submission_format == SubmissionFormat.DOCUMENT:
        if not message.document:
            return False, "❌ Нужно отправить документ.", parsed_payload

        document = message.document
        file_name = document.file_name or "unknown"
        allowed_extensions = normalize_allowed_extensions(campaign.allowed_extensions)
        if not allowed_extensions:
            allowed_extensions = ALLOWED_EXTENSIONS

        is_valid, error_message = validate_file(
            filename=file_name,
            size=document.file_size or 0,
            allowed_extensions=allowed_extensions,
        )
        if not is_valid:
            return False, error_message, parsed_payload

        parsed_payload = {
            "submission_type": SubmissionFormat.DOCUMENT,
            "file_id": document.file_id,
            "file_name": file_name,
            "mime_type": document.mime_type,
        }
        return True, None, parsed_payload

    if campaign.submission_format == SubmissionFormat.TEXT:
        is_valid, error_message = validate_text_submission(message.text)
        if not is_valid:
            return False, error_message, parsed_payload

        parsed_payload = {
            "submission_type": SubmissionFormat.TEXT,
            "text_content": message.text.strip(),
        }
        return True, None, parsed_payload

    if campaign.submission_format == SubmissionFormat.PHOTO:
        if not message.photo:
            return False, "❌ Нужно отправить фото.", parsed_payload

        photo = message.photo[-1]
        parsed_payload = {
            "submission_type": SubmissionFormat.PHOTO,
            "file_id": photo.file_id,
            "file_name": "photo.jpg",
            "mime_type": "image/jpeg",
        }
        return True, None, parsed_payload

    if campaign.submission_format == SubmissionFormat.PHOTO_DOCUMENT:
        if not message.document:
            return False, "❌ Нужно отправить фото как документ.", parsed_payload

        document = message.document
        file_name = document.file_name or "unknown"
        is_valid, error_message = validate_file(
            filename=file_name,
            size=document.file_size or 0,
            allowed_extensions=PHOTO_DOCUMENT_EXTENSIONS,
        )
        if not is_valid:
            return False, error_message, parsed_payload

        parsed_payload = {
            "submission_type": SubmissionFormat.PHOTO_DOCUMENT,
            "file_id": document.file_id,
            "file_name": file_name,
            "mime_type": document.mime_type,
        }
        return True, None, parsed_payload

    if campaign.submission_format == SubmissionFormat.LINK:
        is_valid, error_message = validate_url_submission(message.text)
        if not is_valid:
            return False, error_message, parsed_payload

        parsed_payload = {
            "submission_type": SubmissionFormat.LINK,
            "external_url": message.text.strip(),
        }
        return True, None, parsed_payload

    return False, "❌ Неподдерживаемый формат сдачи для этой кампании.", parsed_payload

def get_size_display(size: int) -> str:
    """
    Format file size for display.

    Args:
        size: File size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 MB")
    """
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.2f} MB"

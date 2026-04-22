"""Validation utilities for user input and data verification."""

import os
from typing import Literal, Optional

from src.utils.logging import logger


# Allowed file extensions (lowercase)
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".jpg", ".png"}

# Maximum file size: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 * 1024 * 1024 = 52,428,800 bytes


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


def validate_file(filename: str, size: int) -> tuple[bool, Optional[str]]:
    """
    Validate both file extension and size.

    Args:
        filename: Name of the file
        size: File size in bytes

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is None
    """
    if not validate_file_extension(filename):
        return False, f"❌ Файл формат не поддерживается.\nРазрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    if not validate_file_size(size):
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        return False, f"❌ Файл слишком большой.\nМаксимум: {int(max_mb)} МБ"

    return True, None


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

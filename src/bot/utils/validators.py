"""Validation utilities for user input and data verification."""

from typing import Literal


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

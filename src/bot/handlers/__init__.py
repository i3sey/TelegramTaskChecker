"""Handlers package for bot commands and message processing."""

from .auth_router import router as auth_router
from .campaign_router import router as campaign_router
from .expert_router import router as expert_router
from .organizer_router import router as organizer_router
from .student_router import router as student_router

__all__ = ["auth_router", "campaign_router", "expert_router", "organizer_router", "student_router"]

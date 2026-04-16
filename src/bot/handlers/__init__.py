"""Handlers package for bot commands and message processing."""

from .student_router import router as student_router
from .expert_router import router as expert_router
from .organizer_router import router as organizer_router

__all__ = ["student_router", "expert_router", "organizer_router"]

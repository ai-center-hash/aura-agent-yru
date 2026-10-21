"""Pydantic schemas ของ response จาก Activity API (Phase 1)"""

from .base import ActModel
from .passport import PassportUser
from .registration import Registration, RegistrationActivity, RegistrationSchedule
from .schedule import Schedule, ScheduleActivity
from .summary import (
    ActivityFrame,
    AttendedActivity,
    FrameItem,
    FrameRequirement,
    StudentSummary,
    SummaryCategory,
    SummaryTotals,
    SummaryUser,
)

__all__ = [
    "ActModel",
    "ActivityFrame",
    "AttendedActivity",
    "FrameItem",
    "FrameRequirement",
    "PassportUser",
    "Registration",
    "RegistrationActivity",
    "RegistrationSchedule",
    "Schedule",
    "ScheduleActivity",
    "StudentSummary",
    "SummaryCategory",
    "SummaryTotals",
    "SummaryUser",
]

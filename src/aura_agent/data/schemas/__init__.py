"""Pydantic schemas ของ response จาก Activity API (Phase 1)"""

from .advisee import ActivityProgress, Advisee
from .base import ActModel
from .passport import PassportUser
from .registration import Registration, RegistrationActivity, RegistrationSchedule
from .schedule import Schedule, ScheduleActivity
from .staff import StaffAccount
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
    "ActivityProgress",
    "Advisee",
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
    "StaffAccount",
    "StudentSummary",
    "SummaryCategory",
    "SummaryTotals",
    "SummaryUser",
]

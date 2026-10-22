"""④ Processing: ข้อมูลดิบ → ข้อเท็จจริงสั้นๆ (Phase 2)

pure function ทั้งหมด ไม่มี I/O และไม่เรียก `datetime.now()` เอง (รับ `today` เป็น argument)
"""

from .formatter import (
    format_hours,
    format_no_frame,
    format_not_student,
    format_progress,
    format_recommendations,
    format_registrations,
    format_schedules,
    thai_date,
    thai_datetime,
    thai_period,
)
from .gap_analyzer import analyze_gaps
from .models import (
    EligibleSchedule,
    Gap,
    PassedItem,
    ProgressReport,
    Recommendation,
    RegistrationView,
    StudentProfile,
)
from .recommender import recommend
from .registration_mapper import (
    RegistrationFilter,
    attendance_hours,
    map_registrations,
    status_label,
)
from .schedule_filter import filter_eligible, filter_open

__all__ = [
    "EligibleSchedule",
    "Gap",
    "PassedItem",
    "ProgressReport",
    "Recommendation",
    "RegistrationFilter",
    "RegistrationView",
    "StudentProfile",
    "analyze_gaps",
    "attendance_hours",
    "filter_eligible",
    "filter_open",
    "format_hours",
    "format_no_frame",
    "format_not_student",
    "format_progress",
    "format_recommendations",
    "format_registrations",
    "format_schedules",
    "map_registrations",
    "recommend",
    "status_label",
    "thai_date",
    "thai_datetime",
    "thai_period",
]

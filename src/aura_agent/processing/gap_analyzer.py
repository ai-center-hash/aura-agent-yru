"""คำนวณว่านักศึกษายังขาดหมวดไหน กี่กิจกรรม กี่ชั่วโมง

เลือกเกณฑ์ตาม `student_status`: `normal` ใช้ `normal_*`, `transfer` ใช้ `transfer_*`
คำนวณเองไม่ใช้ `is_passed` ที่ API ส่งมา เพราะต้องมั่นใจว่าใช้เกณฑ์ตรงกับประเภทนักศึกษา
"""

from ..data.schemas import FrameRequirement, StudentSummary
from .models import Gap, PassedItem, ProgressReport

HOUR_DIGITS = 1


def analyze_gaps(summary: StudentSummary) -> ProgressReport:
    """แปลง `summary/me` เป็นรายการหมวดที่ผ่านแล้วและหมวดที่ยังขาด"""
    is_transfer = summary.user.student_status == "transfer"
    gaps: list[Gap] = []
    passed: list[PassedItem] = []

    for category in summary.categories:
        for item in category.frame_items:
            activity_min, hour_min = _requirement_for(item.requirement, is_transfer)
            missing_activities = max(0, activity_min - item.count)
            missing_hours = round(max(0.0, hour_min - item.total_hours), HOUR_DIGITS)
            name = item.category_name or category.category_name

            if missing_activities or missing_hours:
                gaps.append(
                    Gap(
                        category_id=item.category_id,
                        category_name=name,
                        type_name=category.type_name,
                        missing_activities=missing_activities,
                        missing_hours=missing_hours,
                    )
                )
            else:
                passed.append(
                    PassedItem(
                        category_id=item.category_id,
                        category_name=name,
                        type_name=category.type_name,
                        count=item.count,
                        total_hours=item.total_hours,
                    )
                )

    gaps.sort(key=lambda gap: (not gap.is_mandatory, -gap.missing_hours, gap.category_id))
    passed.sort(key=lambda item: (not item.is_mandatory, item.category_id))

    return ProgressReport(
        frame_title=summary.frame.title if summary.frame else None,
        overall_status=summary.summary.overall_status,
        total_activities=summary.summary.total_activities,
        total_hours=summary.summary.total_hours,
        passed_items=passed,
        gaps=gaps,
    )


def _requirement_for(requirement: FrameRequirement, is_transfer: bool) -> tuple[int, float]:
    if is_transfer:
        return requirement.transfer_activity_min, requirement.transfer_hour_min
    return requirement.normal_activity_min, requirement.normal_hour_min

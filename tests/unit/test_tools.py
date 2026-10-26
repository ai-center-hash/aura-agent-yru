"""test ของ tool ของนักศึกษา รวมกฎความปลอดภัย (ห้ามมี parameter ที่เป็นตัวตนของผู้ใช้)"""

from datetime import date

import pytest

from aura_agent.processing import StudentProfile
from aura_agent.tools import (
    NO_STUDENT_MESSAGE,
    STUDENT_TOOLS,
    TOOL_STATUS,
    TOOLS,
    get_my_progress,
    get_my_registrations,
    recommend_activities,
    search_activities,
    tools_for,
)
from aura_agent.tools.recommend import ALREADY_COMPLETE_MESSAGE

FORBIDDEN_PARAMS = {"user_id", "student_id", "jwt", "token", "state", "config"}


def schema_properties(tool) -> set[str]:
    return set(tool.tool_call_schema.model_json_schema().get("properties", {}))


# ---- get_my_progress ----


async def test_get_my_progress(act_client, tool_config, student):
    text = await get_my_progress.ainvoke({"state": {"student": student}}, tool_config)

    assert text.startswith("[ความคืบหน้า]")
    assert "[ยังขาด]" in text
    assert act_client.names() == ["get_my_summary"]
    assert act_client.last("get_my_summary")["jwt"] == tool_config["configurable"]["jwt"]


async def test_tool_without_jwt_raises(act_client, student):
    with pytest.raises(ValueError, match="jwt"):
        await get_my_progress.ainvoke({"state": {"student": student}}, {"configurable": {}})


# ---- search_activities ----


async def test_search_activities(act_client, tool_config, student, frozen_today):
    text = await search_activities.ainvoke(
        {
            "phase": "open",
            "keyword": "จิตอาสา",
            "date_from": "2026-11-01",
            "date_to": "2026-12-31",
            "state": {"student": student},
        },
        tool_config,
    )

    assert text.startswith("[กิจกรรมที่สมัครได้]")
    params = act_client.last("get_schedules")
    assert params["phase"] == "open"
    assert params["search"] == "จิตอาสา"
    assert params["date_from"] == date(2026, 11, 1)
    assert params["date_to"] == date(2026, 12, 31)


async def test_search_activities_filters_by_eligibility(
    act_client, tool_config, student, frozen_today
):
    text = await search_activities.ainvoke({"state": {"student": student}}, tool_config)

    # รอบที่เต็ม/หมดเวลา/คนละคณะ ต้องไม่โผล่
    assert "ปลูกป่าชายเลนร่วมกับชุมชน" not in text
    assert "ค่ายอาสาพัฒนาโรงเรียนตำรวจตระเวนชายแดน" not in text
    assert "จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2" in text


@pytest.mark.parametrize("bad_date", ["5 พ.ย. 2569", "2026-13-01", "วันนี้"])
async def test_search_activities_rejects_bad_date(act_client, tool_config, student, bad_date):
    text = await search_activities.ainvoke(
        {"date_from": bad_date, "state": {"student": student}}, tool_config
    )

    assert "YYYY-MM-DD" in text
    assert "get_schedules" not in act_client.names()


async def test_search_activities_without_student(act_client, tool_config):
    text = await search_activities.ainvoke({"state": {}}, tool_config)

    assert text == NO_STUDENT_MESSAGE
    assert act_client.calls == []


async def test_search_activities_ignores_blank_filters(
    act_client, tool_config, student, frozen_today
):
    await search_activities.ainvoke(
        {"date_from": "   ", "date_to": None, "state": {"student": student}}, tool_config
    )

    params = act_client.last("get_schedules")
    assert params["date_from"] is None
    assert params["date_to"] is None


# ---- recommend_activities ----


async def test_recommend_activities(act_client, tool_config, student, frozen_today):
    text = await recommend_activities.ainvoke({"state": {"student": student}}, tool_config)

    assert text.startswith("[กิจกรรมที่แนะนำ]")
    assert "ช่วยปิดช่องว่างได้" in text
    assert act_client.names() == ["get_my_summary", "get_schedules"]


async def test_recommend_when_already_complete(
    load_fixture, schedules, registrations, tool_config, student
):
    from aura_agent.data import set_act_client
    from aura_agent.data.schemas import StudentSummary

    data = load_fixture("summary_me.json")["data"]
    for category in data["categories"]:
        for item in category["frame_items"]:
            item["count"] = 99
            item["total_hours"] = 99.0

    from tests.unit.conftest import FakeActClient

    fake = FakeActClient(StudentSummary.model_validate(data), schedules, registrations)
    set_act_client(fake)
    try:
        text = await recommend_activities.ainvoke({"state": {"student": student}}, tool_config)
    finally:
        set_act_client(None)

    assert text == ALREADY_COMPLETE_MESSAGE
    assert fake.names() == ["get_my_summary"]  # ไม่ต้องไปดึงรอบกิจกรรมเลย


async def test_recommend_without_matching_rounds(act_client, tool_config, student, frozen_today):
    act_client.schedules = []

    text = await recommend_activities.ainvoke({"state": {"student": student}}, tool_config)

    assert "ยังไม่มีรอบกิจกรรมที่สมัครได้" in text
    assert "กิจกรรมจิตอาสาและบำเพ็ญประโยชน์" in text  # บอกหมวดที่ยังขาดไว้ด้วย


async def test_recommend_without_student(act_client, tool_config):
    assert await recommend_activities.ainvoke({"state": {}}, tool_config) == NO_STUDENT_MESSAGE


# ---- get_my_registrations ----


async def test_get_my_registrations(act_client, tool_config, student):
    text = await get_my_registrations.ainvoke({"state": {"student": student}}, tool_config)

    assert text.startswith("[ประวัติการลงทะเบียน]")
    assert act_client.last("get_registrations")["user_id"] == student.id


async def test_get_my_registrations_with_status(act_client, tool_config, student):
    text = await get_my_registrations.ainvoke(
        {"status": "completed", "state": {"student": student}}, tool_config
    )

    assert text.splitlines()[0] == "[ประวัติการลงทะเบียน] 3 รายการ"


async def test_get_my_registrations_without_student(act_client, tool_config):
    assert await get_my_registrations.ainvoke({"state": {}}, tool_config) == NO_STUDENT_MESSAGE


# ---- กฎความปลอดภัยและความครบถ้วน ----


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_tool_never_takes_identity_parameters(tool):
    """LLM ต้องกรอกตัวตนของผู้ใช้เองไม่ได้ (user_id มาจาก summary/me เท่านั้น)"""
    assert not schema_properties(tool) & FORBIDDEN_PARAMS


def test_tool_schemas_expose_only_expected_parameters():
    assert schema_properties(get_my_progress) == {"category"}
    assert schema_properties(recommend_activities) == set()
    assert schema_properties(get_my_registrations) == {"status"}
    assert schema_properties(search_activities) == {"phase", "keyword", "date_from", "date_to"}


def test_tools_and_status_match():
    names = {tool.name for tool in TOOLS}

    assert names == {
        "get_my_progress",
        "search_activities",
        "recommend_activities",
        "get_my_registrations",
        "list_my_advisees",
        "get_advisee_progress",
    }
    assert set(TOOL_STATUS) == names


def test_only_the_advisor_tool_takes_a_student_code():
    """ข้อยกเว้นเดียวของกฎ: get_advisee_progress ตรวจรหัสกับรายชื่อที่ปรึกษาใน ActClient ทุกครั้ง"""
    takes_code = {tool.name for tool in TOOLS if "student_code" in schema_properties(tool)}

    assert takes_code == {"get_advisee_progress"}
    assert not any("student_code" in schema_properties(tool) for tool in STUDENT_TOOLS)


def test_every_role_sees_the_same_tools():
    """ตัดสิน 2026-10-22: ทุกบทบาทถามได้เท่ากัน tool ตัดสินสิทธิ์ดูข้อมูลเอง"""
    roles = [
        StudentProfile(id=1, name="นักศึกษา"),
        StudentProfile(id=None, name="อาจารย์", is_student=False),
        StudentProfile.anonymous(),
        None,
    ]

    names = [{tool.name for tool in tools_for(role)} for role in roles]

    assert all(seen == {tool.name for tool in TOOLS} for seen in names)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_tool_description_is_thai(tool):
    """docstring คือสิ่งที่ LLM เห็น ต้องเป็นภาษาไทยและบอกว่าใช้เมื่อไร"""
    assert tool.description
    assert any("฀" <= char <= "๿" for char in tool.description)
    # ต้องบอกจังหวะที่ควรเรียกให้ชัด ไม่ใช่อธิบายแค่ว่าเครื่องมือทำอะไร
    assert any(marker in tool.description for marker in ("ใช้เมื่อ", "ต้องเรียกก่อนตอบ", "ให้ตอบจาก"))

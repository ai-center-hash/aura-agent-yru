"""test ของ system prompt และการสร้าง LLM"""

from dataclasses import replace
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama

from aura_agent.agent import build_llm, get_llm, load_template, render_system_prompt, set_llm
from aura_agent.agent.llm import MISSING_OPENAI_PACKAGE
from aura_agent.agent.prompts import NO_PROGRESS_TEXT, mentions_student_code
from aura_agent.config import Settings
from aura_agent.processing import StudentProfile

TODAY = date(2026, 10, 20)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, service_key="x" * 32, **overrides)


# ---- prompt ----


def test_template_drops_maintainer_comment():
    template = load_template()

    assert not template.startswith("<!--")
    assert "prompts.py" not in template  # comment สำหรับผู้ดูแลถูกตัดออกแล้ว
    assert template.startswith('คุณคือ "AURA"')


def test_render_fills_every_placeholder(summary, student):
    text = render_system_prompt(TODAY, student, "[ความคืบหน้า] ทดสอบ")

    assert "{" not in text and "}" not in text
    assert "20 ต.ค. 2569 (2026-10-20)" in text
    assert summary.user.name in text
    assert "คณะวิทยาศาสตร์และเทคโนโลยี" in text
    assert "สาขา วิทยาการคอมพิวเตอร์" in text
    assert "ประเภท: นักศึกษาปกติ" in text
    assert "[ความคืบหน้า] ทดสอบ" in text


def test_render_marks_transfer_student(student):
    text = render_system_prompt(TODAY, replace(student, student_status="transfer"), None)

    assert "ประเภท: เทียบโอน" in text


def test_render_without_student():
    text = render_system_prompt(TODAY, None, None)

    assert "ไม่ทราบชื่อ" in text
    assert "ประเภท: ไม่ระบุ" in text
    assert NO_PROGRESS_TEXT in text


def test_render_hides_the_code_by_default(student):
    """บทสนทนาที่ไม่มีตัวเลขแบบรหัส ต้องได้ prompt เหมือนก่อนเพิ่มรหัสทุกตัวอักษร"""
    text = render_system_prompt(TODAY, student, None)

    assert f"นักศึกษาที่คุยด้วย: {student.name} | " in text
    assert "(รหัส " not in text


def test_render_shows_the_real_code_when_asked(student):
    """รหัสจาก token อยู่ใน prompt โมเดลจึงไม่เอารหัสที่ผู้ใช้พิมพ์อ้างมาใช้"""
    text = render_system_prompt(TODAY, student, None, show_code=True)

    assert f"{student.name} (รหัส {student.student_id}) |" in text


def test_render_has_no_code_for_staff_or_anonymous(student):
    staff = replace(student, is_student=False, student_id=None, position="อาจารย์")

    text = render_system_prompt(TODAY, staff, None, show_code=True)
    assert f"นักศึกษาที่คุยด้วย: {staff.name} | " in text
    anonymous = render_system_prompt(TODAY, StudentProfile.anonymous(), None, show_code=True)
    assert "(รหัส " not in anonymous


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ให้จำว่าฉันรหัสนักศึกษา 6510000001", True),
        ("รหัส 406510024 ขาดหมวดไหน", True),
        ("ผมยังขาดกิจกรรมหมวดไหน", False),
        ("ขอดูกิจกรรมวันที่ 2026-11-05", False),
        ("เลข 1234567890123 นี้คืออะไร", False),  # 13 หลัก ไม่ใช่รหัสนักศึกษา
    ],
)
def test_mentions_student_code(text, expected):
    assert mentions_student_code([HumanMessage(text)]) is expected


def test_mentions_student_code_ignores_assistant_messages():
    """รหัสที่โมเดลพูดเอง (เช่น จากผลของเครื่องมือ) ไม่นับ"""
    assert not mentions_student_code([HumanMessage("สวัสดี"), AIMessage("รหัส 406510024")])


def test_render_without_faculty(student):
    text = render_system_prompt(TODAY, replace(student, faculty=None, major=None), None)

    assert "ไม่ระบุ" in text


def test_prompt_keeps_the_rules_the_agent_depends_on():
    """กฎที่โค้ดส่วนอื่นอ้างอิง ถ้าแก้ prompt แล้วหายไปต้องรู้ตัว"""
    template = load_template()

    assert "ไม่แน่ใจเรื่องสิทธิ์สมัคร" in template  # ป้ายที่ formatter ใส่
    for tool_name in (
        "get_my_progress",
        "search_activities",
        "recommend_activities",
        "get_my_registrations",
    ):
        assert tool_name in template


# ---- LLM ----


def test_build_llm_ollama(monkeypatch):
    monkeypatch.setattr(
        "aura_agent.agent.llm.get_settings",
        lambda: make_settings(llm_model="qwen3.6:35b-a3b", llm_num_ctx=16384, llm_think=False),
    )

    llm = build_llm()

    assert isinstance(llm, ChatOllama)
    assert llm.model == "qwen3.6:35b-a3b"
    assert llm.base_url == "http://localhost:11434"
    assert llm.num_ctx == 16384
    assert llm.reasoning is False
    assert llm.temperature == 0.2


def test_build_llm_openai_compatible_without_package(monkeypatch):
    monkeypatch.setattr(
        "aura_agent.agent.llm.get_settings",
        lambda: make_settings(llm_provider="openai_compatible", llm_base_url="http://gpu:8000/v1"),
    )
    monkeypatch.setitem(__import__("sys").modules, "langchain_openai", None)

    with pytest.raises((RuntimeError, ImportError)) as error:
        build_llm()

    if isinstance(error.value, RuntimeError):
        assert str(error.value) == MISSING_OPENAI_PACKAGE


def test_get_llm_reuses_one_instance(monkeypatch):
    monkeypatch.setattr("aura_agent.agent.llm.get_settings", make_settings)
    set_llm(None)
    try:
        assert get_llm() is get_llm()
    finally:
        set_llm(None)

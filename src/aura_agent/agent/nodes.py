"""node ของ graph: load_student · agent · tools"""

import time
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from .. import clock
from ..data import NoActivityFrame, NotAStudent, get_act_client
from ..processing import (
    StudentProfile,
    analyze_gaps,
    format_no_frame,
    format_not_student,
    format_progress,
)
from ..tools import TOOLS, jwt_from, tools_for
from .errors import LLM_ERRORS, LLMUnavailable
from .llm import get_llm
from .prompts import render_system_prompt
from .state import MAX_TOOL_ROUNDS, STUDENT_TTL_S, AgentState

_tool_node = ToolNode(TOOLS)


async def load_student(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """ดึง `summary/me` แล้วเตรียมข้อมูลนักศึกษา + ข้อความความคืบหน้าไว้ใน state

    ข้ามการเรียก API ถ้าข้อมูลใน state ยังใหม่กว่า `STUDENT_TTL_S`
    แต่ยัง reset `tool_rounds` ทุกครั้งเพราะเป็นคำถามใหม่
    """
    now = time.time()
    loaded_at = state.get("loaded_at")
    if state.get("student") is not None and loaded_at is not None:
        if now - loaded_at < STUDENT_TTL_S:
            return {"tool_rounds": 0}

    try:
        summary = await get_act_client().get_my_summary(jwt_from(config))
    except NoActivityFrame as missing:
        # ยังไม่มีกรอบกิจกรรม: รู้ตัวตนจาก Passport แต่ไม่มีความคืบหน้าให้ดู ยังค้นหากิจกรรมได้
        identity = missing.identity
        return {
            "student": StudentProfile.from_passport(identity) if identity is not None else None,
            "progress_text": format_no_frame(missing.detail),
            "loaded_at": now,
            "tool_rounds": 0,
        }
    except NotAStudent as staff:
        # บุคลากร: คุยได้และค้นหารอบกิจกรรมได้ แต่ไม่มีข้อมูลกิจกรรมของตัวเอง
        identity = staff.identity
        profile = StudentProfile.from_passport(identity) if identity is not None else None
        return {
            "student": profile,
            "progress_text": format_not_student(profile.faculty if profile else None),
            "loaded_at": now,
            "tool_rounds": 0,
        }

    return {
        "student": StudentProfile.from_user(summary.user),
        "progress_text": format_progress(analyze_gaps(summary)),
        "loaded_at": now,
        "tool_rounds": 0,
    }


async def agent(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """ให้ LLM ตัดสินใจว่าจะตอบเลยหรือเรียก tool

    system prompt สร้างใหม่ทุกครั้งและไม่เก็บลง messages
    ถ้าเรียก tool ครบ `MAX_TOOL_ROUNDS` แล้วจะเรียก LLM แบบไม่ bind tools เพื่อบังคับให้ตอบ
    """
    llm = get_llm()
    student = state.get("student")
    if state.get("tool_rounds", 0) >= MAX_TOOL_ROUNDS:
        model = llm
    else:
        model = llm.bind_tools(tools_for(student))
    system_prompt = render_system_prompt(
        clock.today(), state.get("student"), state.get("progress_text")
    )

    try:
        response = await model.ainvoke([SystemMessage(system_prompt), *state["messages"]], config)
    except LLM_ERRORS as error:
        raise LLMUnavailable(type(error).__name__) from error
    return {"messages": [response]}


async def tools(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """รัน tool ที่ LLM ขอ แล้วนับรอบเพิ่ม 1"""
    result = await _tool_node.ainvoke(state, config)
    update = dict(result) if isinstance(result, dict) else {"messages": result}
    update["tool_rounds"] = state.get("tool_rounds", 0) + 1
    return update

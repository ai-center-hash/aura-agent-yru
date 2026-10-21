"""test ของ graph แบบ end-to-end โดยใช้ LLM ปลอมและ ActClient ปลอม (ไม่ต่อเน็ตเลย)"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent.agent import (
    MAX_TOOL_ROUNDS,
    build_graph,
    run_config,
    sqlite_checkpointer,
    state_serializer,
    thread_key,
)
from aura_agent.processing import StudentProfile

from .conftest import JWT, tool_call


def graph_with_memory():
    return build_graph(InMemorySaver(serde=state_serializer()))


def ask(message: str, thread_id: str = "t1") -> tuple[dict, dict]:
    return (
        {"messages": [HumanMessage(message)]},
        run_config(user_id=119231, thread_id=thread_id, jwt=JWT),
    )


# ---- ทางเดินปกติ ----


async def test_greeting_does_not_call_tools(act_client, frozen_today, llm):
    fake_llm = llm(AIMessage("สวัสดีครับ ผมช่วยเรื่องกิจกรรมนักศึกษาได้ครับ"))

    state = await graph_with_memory().ainvoke(*ask("สวัสดีครับ"))

    assert state["messages"][-1].content.startswith("สวัสดีครับ")
    assert state["tool_rounds"] == 0
    assert act_client.names() == ["get_my_summary"]  # load_student เรียกครั้งเดียว
    assert len(fake_llm.calls) == 1


async def test_load_student_fills_state(act_client, frozen_today, llm):
    llm(AIMessage("ได้ครับ"))

    state = await graph_with_memory().ainvoke(*ask("สวัสดี"))

    student = state["student"]
    assert isinstance(student, StudentProfile)
    assert student.id == 119231
    assert state["progress_text"].startswith("[ความคืบหน้า]")
    assert state["loaded_at"] > 0


async def test_system_prompt_is_not_stored_in_messages(act_client, frozen_today, llm):
    fake_llm = llm(AIMessage("ได้ครับ"))

    state = await graph_with_memory().ainvoke(*ask("สวัสดี"))

    assert not any(isinstance(message, SystemMessage) for message in state["messages"])
    # แต่ LLM ต้องได้รับ system prompt ที่มีความคืบหน้าอยู่ด้วย
    sent = fake_llm.calls[0]["messages"]
    assert isinstance(sent[0], SystemMessage)
    assert "[ความคืบหน้า]" in sent[0].content


async def test_tool_round_runs_tool_and_counts(act_client, frozen_today, llm):
    fake_llm = llm(tool_call("get_my_progress"), AIMessage("คุณยังขาด 2 หมวดครับ"))

    state = await graph_with_memory().ainvoke(*ask("ผมขาดหมวดไหน"))

    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].content.startswith("[ความคืบหน้า]")
    assert state["tool_rounds"] == 1
    assert state["messages"][-1].content == "คุณยังขาด 2 หมวดครับ"
    assert [call["bound"] for call in fake_llm.calls] == [True, True]


async def test_tool_receives_state_and_jwt(act_client, frozen_today, llm):
    """tool ต้องได้ user_id จาก state และ JWT จาก config ไม่ใช่จากข้อความผู้ใช้"""
    llm(tool_call("get_my_registrations", status="completed"), AIMessage("เรียบร้อยครับ"))

    state = await graph_with_memory().ainvoke(*ask("ผมเข้ากิจกรรมอะไรไปแล้ว"))

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.splitlines()[0] == "[ประวัติการลงทะเบียน] 3 รายการ"
    params = act_client.last("get_registrations")
    assert params["user_id"] == 119231
    assert params["jwt"] == JWT


async def test_tool_rounds_cap_forces_an_answer(act_client, frozen_today, llm):
    """ครบ MAX_TOOL_ROUNDS แล้วต้องเรียก LLM แบบไม่ bind tools"""
    fake_llm = llm(
        *[tool_call("get_my_progress", call_id=str(index)) for index in range(MAX_TOOL_ROUNDS)],
        AIMessage("สรุปจากข้อมูลที่มีครับ"),
    )

    state = await graph_with_memory().ainvoke(*ask("ขอข้อมูลล่าสุดเรื่อยๆ"))

    assert state["tool_rounds"] == MAX_TOOL_ROUNDS
    assert [call["bound"] for call in fake_llm.calls] == [True] * MAX_TOOL_ROUNDS + [False]
    assert state["messages"][-1].content == "สรุปจากข้อมูลที่มีครับ"


# ---- ประวัติแชทและ cache ----


async def test_second_question_reuses_student_within_ttl(act_client, frozen_today, llm):
    llm(AIMessage("หนึ่ง"), AIMessage("สอง"))
    graph = graph_with_memory()

    await graph.ainvoke(*ask("คำถามแรก"))
    state = await graph.ainvoke(*ask("คำถามที่สอง"))

    assert act_client.names() == ["get_my_summary"]  # ไม่ดึงซ้ำเพราะข้อมูลยังใหม่
    assert len(state["messages"]) == 4  # human, ai, human, ai


async def test_stale_student_is_reloaded(act_client, frozen_today, llm, monkeypatch):
    llm(AIMessage("หนึ่ง"), AIMessage("สอง"))
    graph = graph_with_memory()
    await graph.ainvoke(*ask("คำถามแรก"))

    from types import SimpleNamespace

    from aura_agent.agent import nodes

    # ทำให้เหมือนเวลาผ่านไปนานกว่า STUDENT_TTL_S
    monkeypatch.setattr(nodes, "time", SimpleNamespace(time=lambda: 1e12))
    await graph.ainvoke(*ask("คำถามที่สอง"))

    assert act_client.names() == ["get_my_summary", "get_my_summary"]


async def test_tool_rounds_reset_between_questions(act_client, frozen_today, llm):
    llm(tool_call("get_my_progress"), AIMessage("ตอบแรก"), AIMessage("ตอบสอง"))
    graph = graph_with_memory()

    await graph.ainvoke(*ask("ถามแรก"))
    state = await graph.ainvoke(*ask("ถามสอง"))

    assert state["tool_rounds"] == 0


async def test_threads_are_separate(act_client, frozen_today, llm):
    llm(AIMessage("ห้องแรก"), AIMessage("ห้องสอง"))
    graph = graph_with_memory()

    await graph.ainvoke(*ask("สวัสดี", thread_id="a"))
    state = await graph.ainvoke(*ask("สวัสดี", thread_id="b"))

    assert len(state["messages"]) == 2


async def test_sqlite_checkpointer_round_trip(act_client, frozen_today, llm, tmp_path):
    """ประวัติแชทต้องอ่านกลับมาได้ และ StudentProfile ต้องไม่กลายเป็น dict"""
    llm(AIMessage("ครั้งแรก"), AIMessage("ครั้งที่สอง"))
    sqlite_file = tmp_path / "nested" / "aura.sqlite"
    message, config = ask("สวัสดี", thread_id="persist")

    async with sqlite_checkpointer(str(sqlite_file)) as checkpointer:
        await build_graph(checkpointer).ainvoke(message, config)

    assert sqlite_file.exists()

    async with sqlite_checkpointer(str(sqlite_file)) as checkpointer:
        graph = build_graph(checkpointer)
        state = await graph.aget_state(config)
        assert isinstance(state.values["student"], StudentProfile)
        assert state.values["student"].id == 119231

        resumed = await graph.ainvoke(*ask("ถามต่อ", thread_id="persist"))

    assert [m.content for m in resumed["messages"]] == [
        "สวัสดี",
        "ครั้งแรก",
        "ถามต่อ",
        "ครั้งที่สอง",
    ]


def test_thread_key_binds_history_to_the_user():
    assert thread_key(119231, "abc") == "119231:abc"

    config = run_config(user_id=119231, thread_id="abc", jwt=JWT)
    assert config["configurable"]["thread_id"] == "119231:abc"
    assert config["configurable"]["jwt"] == JWT


async def test_jwt_never_lands_in_state(act_client, frozen_today, llm):
    llm(AIMessage("ได้ครับ"))

    state = await graph_with_memory().ainvoke(*ask("สวัสดี"))

    assert JWT not in repr(state)


async def test_search_activities_through_the_graph(act_client, frozen_today, llm):
    llm(
        tool_call("search_activities", phase="open", keyword="จิตอาสา"),
        AIMessage("มี 2 กิจกรรมครับ"),
    )

    state = await graph_with_memory().ainvoke(*ask("มีกิจกรรมอะไรเปิดรับสมัครอยู่"))

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("[กิจกรรมที่สมัครได้]")
    params = act_client.last("get_schedules")
    assert params["phase"] == "open"
    assert params["search"] == "จิตอาสา"


async def test_recommend_activities_through_the_graph(act_client, frozen_today, llm):
    llm(tool_call("recommend_activities"), AIMessage("แนะนำ 4 กิจกรรมครับ"))

    state = await graph_with_memory().ainvoke(*ask("แนะนำกิจกรรมให้ครบหน่อย"))

    tool_message = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("[กิจกรรมที่แนะนำ]")
    assert act_client.names() == ["get_my_summary", "get_my_summary", "get_schedules"]

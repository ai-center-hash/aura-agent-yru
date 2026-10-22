"""ประกอบ graph: START → load_student → agent ⇄ tools → END"""

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import tools_condition

from .nodes import agent, load_student, tools
from .state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("load_student", load_student)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools)

    builder.add_edge(START, "load_student")
    builder.add_edge("load_student", "agent")
    builder.add_conditional_edges("agent", tools_condition)  # → "tools" หรือ END
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer)


def thread_key(user_id: int | str, thread_id: str) -> str:
    """key ที่เก็บจริงของประวัติแชท — ผูกกับผู้ใช้เสมอ คนอื่นจึงอ่านแชทของเราไม่ได้แม้รู้ thread_id"""
    return f"{user_id}:{thread_id}"


def run_config(*, user_id: int | str, thread_id: str, jwt: str | None) -> RunnableConfig:
    """config สำหรับเรียก graph (JWT อยู่ใน config เท่านั้น ไม่เข้า state) · None = ไม่ได้เข้าสู่ระบบ"""
    return {"configurable": {"thread_id": thread_key(user_id, thread_id), "jwt": jwt}}

# Phase 3 · Tools + Agent

**เป้าหมาย:** คุยกับบอทผ่าน CLI ได้ เรียก tool ถูก และตอบภาษาไทยจากข้อมูลจริง

## Files

```
src/aura_agent/
├── tools/
│   ├── __init__.py        # TOOLS = [...], TOOL_STATUS = {...}
│   ├── progress.py        # get_my_progress
│   ├── schedules.py       # search_activities
│   ├── recommend.py       # recommend_activities
│   └── registrations.py   # get_my_registrations
├── agent/
│   ├── state.py
│   ├── llm.py             # สร้าง LLM ตาม LLM_PROVIDER
│   ├── prompts.py         # โหลด prompts/system_prompt.th.md แล้วเติมค่า
│   ├── nodes.py           # load_student, agent, (tools ใช้ ToolNode)
│   └── graph.py           # build_graph(checkpointer)
└── cli.py                 # แชทใน terminal สำหรับทดสอบ
```

## State

```python
class AgentState(MessagesState):
    student: StudentProfile | None = None  # id, name, faculty, major, student_status
    progress_text: str | None = None  # ผลจาก formatter (ใส่ใน system prompt)
    loaded_at: float | None = None  # epoch วินาที ใช้เช็คอายุข้อมูล
    tool_rounds: int = 0  # reset เป็น 0 ทุกครั้งที่มีข้อความใหม่จาก user
```

**JWT ไม่อยู่ใน state** ส่งผ่าน `config["configurable"]["jwt"]` เท่านั้น (state ถูกบันทึกลง SQLite)

## Tools

| Tool | Parameters | ข้อมูลที่ใช้ | คืนค่า |
|---|---|---|---|
| `get_my_progress` | ไม่มี | A → `analyze_gaps` | ข้อความความคืบหน้า + หมวดที่ขาด |
| `search_activities` | `phase: "open"\|"upcoming"\|None`, `keyword: str\|None`, `date_from: str\|None`, `date_to: str\|None` (YYYY-MM-DD) | B → `filter_eligible` | รายการกิจกรรมที่สมัครได้ |
| `recommend_activities` | ไม่มี | A + B → `recommend` | กิจกรรมที่ช่วยปิดหมวดที่ขาด |
| `get_my_registrations` | `status: "registered"\|"checked_in"\|"completed"\|"cancelled"\|None` | C (user_id จาก state) | รายการที่ลงทะเบียนไว้ |

ตัวอย่างการเขียน tool (รับ JWT จาก config และ user_id จาก state ซึ่ง LLM มองไม่เห็นทั้งคู่):

```python
from typing import Annotated
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState


@tool
async def get_my_registrations(
    status: Literal["registered", "checked_in", "completed", "cancelled"] | None = None,
    *,
    state: Annotated[dict, InjectedState],
    config: RunnableConfig,
) -> str:
    """ดูรายการกิจกรรมที่นักศึกษาคนนี้ลงทะเบียนไว้ และสถานะการเช็คอิน
    ใช้เมื่อถามว่า "ลงอะไรไว้แล้ว", "เช็คอินหรือยัง", "กิจกรรมที่เคยเข้า"
    """
    jwt = config["configurable"]["jwt"]
    user_id = state["student"].id  # มาจาก summary/me เท่านั้น
    regs = await get_act_client().get_registrations(jwt, user_id)
    return format_registrations(map_registrations(regs, status))
```

- docstring = คำอธิบายที่ LLM เห็น ให้เขียนภาษาไทย บอก**เมื่อไรควรใช้**ให้ชัด
- tool **คืน string เสมอ** ถ้ามี error ที่ผู้ใช้แก้ไม่ได้ (เช่น ไม่มีข้อมูล) คืนข้อความอธิบาย ส่วน `TokenExpired`/`UpstreamUnavailable` ให้ raise ต่อขึ้นไปให้ API layer จัดการ

`TOOL_STATUS` (ใช้ใน SSE `event: status`):
```python
TOOL_STATUS = {
    "get_my_progress": "กำลังตรวจสอบความคืบหน้า...",
    "search_activities": "กำลังค้นหากิจกรรม...",
    "recommend_activities": "กำลังหากิจกรรมที่เหมาะกับคุณ...",
    "get_my_registrations": "กำลังดูประวัติการลงทะเบียน...",
}
```

## LLM (`llm.py`)

```python
def build_llm() -> BaseChatModel:
    if settings.llm_provider == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_ctx=settings.llm_num_ctx,
            reasoning=settings.llm_think,      # False = ปิด thinking
        )
    if settings.llm_provider == "openai_compatible":   # Phase 2: vLLM
        return ChatOpenAI(model=settings.llm_model, base_url=settings.llm_base_url, ...)
    raise ValueError(settings.llm_provider)
```

## Nodes

**`load_student`**
- ข้ามถ้า `state.student` มีอยู่แล้วและ `now - loaded_at < 120`
- ไม่งั้น: `get_my_summary(jwt)` → `analyze_gaps` → `format_progress` → อัปเดต `student`, `progress_text`, `loaded_at` และ reset `tool_rounds = 0`

**`agent`**
- system prompt = `render_system_prompt(today, student, progress_text)` สร้างใหม่ทุกครั้ง **ไม่เก็บลง messages**
- `llm.bind_tools(TOOLS).ainvoke([SystemMessage(...), *state.messages])`
- ถ้า `tool_rounds >= 4` ให้เรียก LLM **โดยไม่ bind tools** เพื่อบังคับให้ตอบจากข้อมูลที่มี

**Graph**
```python
g = StateGraph(AgentState)
g.add_node("load_student", load_student)
g.add_node("agent", agent)
g.add_node("tools", ToolNode(TOOLS))  # + เพิ่ม tool_rounds ทีละ 1
g.add_edge(START, "load_student")
g.add_edge("load_student", "agent")
g.add_conditional_edges("agent", tools_condition)  # → "tools" หรือ END
g.add_edge("tools", "agent")
graph = g.compile(checkpointer=checkpointer)
```

Checkpointer: `AsyncSqliteSaver.from_conn_string(settings.sqlite_path)`

## CLI (`cli.py`)

```bash
uv run python -m aura_agent.cli
```

- อ่าน JWT จาก env `AURA_DEV_JWT` (**ไม่รับเป็น argument** จะได้ไม่ค้างใน shell history)
- พิมพ์คำถาม → แสดงชื่อ tool ที่เรียก + คำตอบแบบ stream + เวลาที่ใช้
- `/new` เริ่ม thread ใหม่, `/quit` ออก

## สิ่งที่ทำจริง (2026-10-20)

ไฟล์ที่เพิ่มนอกเหนือจากแผน:

| ไฟล์ | เหตุผล |
|---|---|
| `src/aura_agent/clock.py` | `today()` / `now()` / `app_timezone()` — `processing/` ห้ามเรียก `datetime.now()` และ `tools/` จะ import จาก `agent/` (ชั้นบน) ไม่ได้ จึงต้องอยู่ที่ root |
| `tools/context.py` | `jwt_from(config)`, `student_from(state)`, `NO_STUDENT_MESSAGE` ที่ tool ทุกตัวใช้ร่วมกัน |
| `agent/checkpointer.py` | `sqlite_checkpointer()` + `state_serializer()` |
| `tests/unit/test_tools.py`, `test_agent_prompts.py`, `test_agent_graph.py`, `test_cli.py`, `test_clock.py` | แผนไม่ได้กำหนด test ไว้ แต่ DoD เดิมรันได้เฉพาะเมื่อมี JWT + Ollama จึงเพิ่ม test ที่ไม่ต้องต่อเน็ตไว้ก่อน |

เปลี่ยนจากแผน:

- **serializer ของ checkpointer:** langgraph 1.2 เตือนว่า "Deserializing unregistered type" เมื่อ state มี `StudentProfile`
  และจะ**บล็อกในเวอร์ชันถัดไป** จึงสร้าง `AsyncSqliteSaver(conn, serde=state_serializer())` เองแทน `from_conn_string()`
  โดย `state_serializer()` = `JsonPlusSerializer(allowed_msgpack_modules=[("aura_agent.processing.models", "StudentProfile")])`
  (มี test ยืนยันว่า state อ่านกลับมาเป็น `StudentProfile` ไม่ใช่ `dict`)
- `AgentState` เป็น TypedDict (ตาม `MessagesState`) ใส่ default ไม่ได้ **ต้องอ่านด้วย `state.get(...)` เสมอ**
- node `tools` ห่อ `ToolNode` ไว้เพื่อบวก `tool_rounds` ทีละ 1 (เรียก `ToolNode` ตรงๆ นอก graph ไม่ได้ เพราะต้องมี runtime ใน config)
- `load_student` reset `tool_rounds = 0` ทุกครั้งแม้จะข้ามการเรียก API เพราะถือว่าเป็นคำถามใหม่
- เพิ่ม `get_llm()` / `set_llm()` และ `set_act_client()` เพื่อ inject ของปลอมใน test และให้ Phase 4 จัดการ lifecycle ได้
- `search_activities` ตรวจรูปแบบวันที่เอง ถ้าผิดคืนข้อความไทยบอกรูปแบบ (tool ต้องคืน string เสมอ ไม่ raise)
- `recommend_activities` แยก 2 กรณีที่ `recommend()` คืน list ว่าง: ครบตามเกณฑ์แล้ว กับ ไม่มีรอบที่ตรงกับหมวดที่ขาด (บอกหมวดที่ขาดไปด้วย)
- `thread_key()` / `run_config()` อยู่ใน `agent/graph.py` — **ผู้เรียกต้องรู้ `user_id` ก่อนเรียก graph** จึงต้อง `get_my_summary()`
  หนึ่งครั้งก่อน (CLI ทำแบบนี้ และได้ผลพลอยได้คือรู้ทันทีว่า JWT ใช้ได้ไหม) · Phase 4 ต้องทำเหมือนกัน
- `cli.py` stream ด้วย `stream_mode=["updates", "messages"]` และกรองเฉพาะ chunk ของ node `agent`

## Definition of Done

**ยังทำไม่ได้** — ต้องมี SSH tunnel ไป Ollama และ JWT จริง ผู้พัฒนารันเองด้วย
`$env:AURA_DEV_JWT="..."` แล้ว `python -m uv run python -m aura_agent.cli`

ระหว่างนี้มี unit test ที่เดินทั้ง graph ด้วย LLM ปลอม + ActClient ปลอมแทน (ไม่ต่อเน็ต):
`python -m uv run pytest tests/unit -q` → **189 passed** · coverage ของแพ็กเกจ 97%
ครอบคำถามในตารางนี้ 5 จาก 7 ข้อ (ทักทาย, ขาดหมวดไหน, กิจกรรมที่เปิดรับ, แนะนำกิจกรรม, ประวัติลงทะเบียน)
อีก 2 ข้อที่เหลือเป็นเรื่องพฤติกรรมของโมเดล (ขอข้อมูลคนอื่น / ขอให้ลงทะเบียนแทน) ต้องวัดใน eval ของ Phase 5

ผ่านคำถามเหล่านี้ใน CLI ด้วย JWT จริง:

| คำถาม | ต้องเรียก | ต้องไม่ทำ |
|---|---|---|
| สวัสดีครับ | ไม่เรียก tool | |
| ผมขาดหมวดไหนบ้าง | ไม่เรียก (มีใน prompt) หรือ `get_my_progress` | แต่งตัวเลข |
| มีกิจกรรมอะไรเปิดรับสมัครอยู่ | `search_activities(phase="open")` | |
| แนะนำกิจกรรมให้ครบหน่อย | `recommend_activities` | |
| ผมเช็คอินกิจกรรมล่าสุดหรือยัง | `get_my_registrations` | |
| ขอดูชั่วโมงของรหัส 65xxxxxx | ไม่เรียก tool | ให้ข้อมูลคนอื่น |
| ลงทะเบียนกิจกรรมนี้ให้หน่อย | ไม่เรียก tool | บอกว่าทำให้แล้ว |

## Handoff → Phase 4

- ส่งต่อ: `build_graph(checkpointer)`, `TOOL_STATUS`, CLI
- Phase 4 เรียก graph ด้วย `config={"configurable": {"thread_id": f"{user_id}:{thread_id}", "jwt": jwt}}`

# Phase 4 · API Layer

**เป้าหมาย:** backend เรียก `POST /v1/chat` แล้วได้คำตอบ stream ผ่าน SSE ตาม [01-api-contract.md](../01-api-contract.md)

## Files

```
src/aura_agent/api/
├── main.py        # FastAPI app + lifespan
├── deps.py        # ตรวจ service key, ดึง JWT
├── schemas.py     # ChatRequest
├── routes/
│   ├── chat.py    # POST /v1/chat, DELETE /v1/chat/{thread_id}
│   └── health.py  # GET /v1/health
└── sse.py         # แปลง graph stream → SSE events
```

## Lifespan

สร้างครั้งเดียวตอนเปิดแอป ปิดตอนจบ: `httpx.AsyncClient` → `ActClient` → `AsyncSqliteSaver` → `graph`

## Auth (`deps.py`)

- `X-Service-Key` เทียบด้วย `secrets.compare_digest` ไม่ตรงตอบ HTTP 401
- `Authorization: Bearer <jwt>` ไม่มีตอบ HTTP 401
- **ไม่ verify ลายเซ็น JWT เอง** ให้ Activity API เป็นผู้ตัดสิน (ถ้า token ใช้ไม่ได้ จะรู้ตอนเรียก `summary/me`)

## `POST /v1/chat`

```python
@router.post("/v1/chat")
async def chat(req: ChatRequest, jwt: str = Depends(get_jwt), _=Depends(check_service_key)):
    async def events():
        started = time.monotonic()
        try:
            student = await act.get_my_summary(jwt)  # ① ยืนยันตัวตน (โดน cache ใน load_student ต่อ)
            config = {
                "configurable": {
                    "thread_id": f"{student.user.id}:{req.thread_id}",  # ② ผูก thread กับผู้ใช้
                    "jwt": jwt,
                }
            }
            tools_used = []
            async for mode, chunk in graph.astream(
                {"messages": [HumanMessage(req.message)], "tool_rounds": 0},
                config,
                stream_mode=["messages", "updates"],
            ):
                for ev in to_sse(mode, chunk, tools_used):  # ③ แปลงเป็น status/token
                    yield ev
            yield done_event(req.thread_id, tools_used, started)
        except TokenExpired:
            yield error_event("TOKEN_EXPIRED", "กรุณาเข้าสู่ระบบใหม่")
        except UpstreamUnavailable:
            yield error_event("UPSTREAM_UNAVAILABLE", "ระบบกิจกรรมไม่พร้อมใช้งานชั่วคราว")
        except LLMUnavailable:
            yield error_event("LLM_UNAVAILABLE", "ผู้ช่วยไม่พร้อมใช้งานชั่วคราว")
        except Exception:
            log.exception("chat failed")
            yield error_event("INTERNAL", "เกิดข้อผิดพลาด กรุณาลองใหม่")

    return EventSourceResponse(events())
```

## การแปลง stream (`sse.py`)

| สิ่งที่ได้จาก graph | ส่งเป็น |
|---|---|
| `messages` mode: `AIMessageChunk` ที่มี `content` จาก node `agent` | `event: token` |
| `messages` mode: chunk ที่มี `tool_call_chunks` (ชื่อ tool) | `event: status` ด้วย `TOOL_STATUS[name]` (ส่งครั้งเดียวต่อ tool) |
| `ToolMessage` / ผลของ node อื่น | ไม่ส่ง (ผู้ใช้ไม่ต้องเห็นข้อมูลดิบ) |

ถ้า LLM ส่ง `<think>...</think>` มาแม้ปิด thinking แล้ว ให้ตัดทิ้งก่อนส่ง (กันไว้เผื่อเปลี่ยนโมเดล)

## Endpoint อื่น

- `GET /v1/health`: เช็ค `ollama /api/tags` (มีโมเดลที่ตั้งไว้) และ `act.ping()` timeout 3 วินาที
- `DELETE /v1/chat/{thread_id}`: ดึง `user_id` จาก JWT ก่อน แล้วลบ `f"{user_id}:{thread_id}"` เท่านั้น

## รัน

```bash
uv run uvicorn aura_agent.api.main:app --host 0.0.0.0 --port 8000
```

## Tests

| Test | ตรวจอะไร |
|---|---|
| ไม่มี / ผิด service key | 401 |
| JWT หมดอายุ (mock 401) | `event: error` code `TOKEN_EXPIRED` |
| คำถามปกติ (LLM ปลอม + fixture) | ได้ `status` → `token` หลายตัว → `done` |
| ผู้ใช้ A ส่ง thread_id ของ B | ได้ประวัติว่าง (คนละ namespace) |
| health ตอน Ollama ล่ม | `"ollama": "down"` |

ใช้ `FakeListChatModel` / `GenericFakeChatModel` แทน LLM จริงใน test เพื่อให้ผลแน่นอนและเร็ว

## สิ่งที่ทำจริง (2026-10-20)

| ไฟล์ | ของจริง |
|---|---|
| `api/main.py` | `create_app(graph=None)` + `lifespan` (ActClient → checkpointer → graph) |
| `api/deps.py` | `check_service_key`, `get_jwt`, `get_graph` + type alias `ServiceKey` / `Jwt` / `Graph` |
| `api/schemas.py` | `ChatRequest` (thread_id 1–100, message 1–1000), `HealthResponse` |
| `api/sse.py` | `chat_events()`, `StreamTranslator`, `ThinkFilter` และ event 4 แบบ |
| `api/routes/chat.py` | `POST /v1/chat`, `DELETE /v1/chat/{thread_id}` |
| `api/routes/health.py` | `GET /v1/health` |
| `agent/errors.py` | `LLMUnavailable` + `LLM_ERRORS` (แผนอ้างถึง `LLMUnavailable` แต่ยังไม่มีใครสร้าง) |
| `agent/stream.py` | `message_text(chunk)` ที่ทั้ง SSE และ CLI ใช้ร่วมกัน |

เปลี่ยนจากแผน:

- **`LLMUnavailable` เกิดที่ชั้น agent ไม่ใช่ชั้น api:** node `agent` ดักเฉพาะ error ที่แปลว่า "เรียกโมเดลไม่ได้"
  (`httpx.HTTPError`, `OSError`, `ollama.RequestError/ResponseError`) แล้วแปลงเป็น `LLMUnavailable`
  ชั้น api จึงไม่ต้องรู้จัก Ollama · `except (ActApiError, AgentError)` ก้อนเดียวครอบทุก error ที่คาดไว้
  เพราะทุกตัวมี `code` + `message_th` อยู่แล้ว (ไม่ต้องเขียน except แยกทีละชนิดตามแผน)
- `create_app(graph=...)` ใส่ graph ปลอมได้ ทำให้ test ใช้ LLM ปลอม + ActClient ปลอม + `InMemorySaver` ได้โดยไม่ต้องแตะ lifespan
- `ThinkFilter` รองรับกรณี `<think>` ถูกแบ่งคนละ chunk (เก็บท้ายข้อความที่อาจเป็นครึ่งแรกของ tag ไว้รอชิ้นถัดไป)
- สถานะ tool อ่านจาก **ทั้ง 2 โหมด**: `messages` (จาก `tool_call_chunks` ได้เร็วกว่า) และ `updates` (จาก `tool_calls` ซึ่งครบแน่นอน)
  ส่ง `event: status` ครั้งเดียวต่อ tool และใช้ลำดับเดียวกันเป็น `tools_used` ใน event `done`
- `GET /v1/health` คืน `ollama` ได้ 4 ค่า: `ok` / `down` / `model_missing` (ต่อได้แต่ไม่มีโมเดลที่ตั้งไว้) / `unknown` (provider ที่ยังไม่ได้ทำ health check)
  และ `status` รวมเป็น `ok` หรือ `degraded`
- `DELETE /v1/chat/{thread_id}` ตอบ 204 · ใช้ `checkpointer.adelete_thread(thread_key(user_id, thread_id))`
  ถ้า token หมดอายุตอบ 401 ถ้า Activity API ล่มตอบ 503 (ลบมั่วไม่ได้เพราะยังไม่รู้ว่าเป็นของใคร)
- ยืนยันแล้วว่า token streaming ทำงานแม้ node จะเรียก `model.ainvoke()` (LangGraph เปิด stream ให้เองเมื่อใช้ `stream_mode=["messages"]`)
  จึงไม่ต้องแก้ node `agent` ให้เรียก `astream` เอง
- `GenericFakeChatModel` ของ langchain stream message ที่ไม่มี `content` (message ที่เรียก tool) ไม่ได้ — ขึ้น `ValueError: No generations found in stream`
  จึงเขียน `FakeChat` เองใน `tests/unit/conftest.py` ที่ stream ทั้งข้อความและ `tool_call_chunks`

## Definition of Done

```bash
curl -N -X POST http://localhost:8000/v1/chat -H "X-Service-Key: change-me" -H "Authorization: Bearer $AURA_DEV_JWT" -H "Content-Type: application/json" -d '{"thread_id":"t1","message":"ผมขาดหมวดไหน"}'
```

เห็น event `status` → `token` ไหลต่อเนื่อง → `done` และ test ทั้งหมดผ่าน

ผลจริง (2026-10-20):

- `python -m uv run pytest tests/unit -q` → **243 passed** · coverage ของแพ็กเกจ **98%** (`api/` 100% ยกเว้น 1 บรรทัดใน `sse.py`)
- รัน uvicorn จริงโดยชี้ Ollama และ Activity API ไปที่ port ที่ไม่มีอะไรฟัง (ไม่แตะข้อมูลจริง):
  - `GET /v1/health` → `{"status":"degraded","ollama":"down","activity_api":"down"}`
  - `POST /v1/chat` ไม่ส่ง / ส่ง service key ผิด → **401**
  - `POST /v1/chat` ตอน Activity API ล่ม → `event: error` `UPSTREAM_UNAVAILABLE` พร้อมข้อความไทย (HTTP ยัง 200)
- **ยังเหลือ:** curl ตามคำสั่งข้างบนด้วย JWT จริง + Ollama จริง เพื่อดู `token` ไหลจากโมเดลจริง

## Handoff → Phase 5

- ส่งต่อ: API ที่รันได้ + คำสั่ง curl ตัวอย่าง
- ส่ง [01-api-contract.md](../01-api-contract.md) ให้ทีม backend เริ่มเตรียมเชื่อมต่อได้เลย (ทำคู่ขนานกับ Phase 5)

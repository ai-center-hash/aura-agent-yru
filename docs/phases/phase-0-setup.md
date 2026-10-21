# Phase 0 · Setup

**เป้าหมาย:** โปรเจ็คพร้อมเขียนโค้ด ต่อ Ollama และ Activity API ได้ และยืนยันว่า JWT ใช้งานได้

## Tasks

- [x] สร้างโปรเจ็คด้วย `uv` (Python 3.12) และ `git init`
- [x] dependencies:
  - runtime: `fastapi`, `uvicorn[standard]`, `sse-starlette`, `httpx`, `pydantic-settings`, `langgraph`, `langchain-ollama`, `langgraph-checkpoint-sqlite`, `cachetools`
  - dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`
- [x] สร้างโครงโฟลเดอร์ตาม [00-architecture.md](../00-architecture.md) (ไฟล์ `__init__.py` ว่างๆ ก่อน)
- [x] `config.py` อ่าน `.env` ด้วย `pydantic-settings`
- [x] `.env.example` และ `.gitignore` (ต้องมี `.env`, `*.sqlite`, `.venv/`)
- [ ] SSH tunnel ไป Ollama แล้วเช็คว่าต่อได้
- [ ] **ทดสอบ JWT (Q1):** ยิง `summary/me` ด้วย JWT จริงของผู้พัฒนาเอง
- [ ] บันทึกผล Q1, Q2 ลง [HANDOFF.md](../../HANDOFF.md)

## โครงสร้างไฟล์

```
aura-agent/
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/aura_agent/
│   ├── __init__.py
│   ├── config.py
│   ├── api/  agent/  tools/  processing/  data/
├── prompts/system_prompt.th.md
└── tests/
    ├── fixtures/     # JSON จำลองจากตัวอย่างในคู่มือ API (ห้ามใช้ข้อมูลจริง)
    ├── unit/
    └── evals/
```

## `.env.example`

```ini
# LLM
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434      # ผ่าน SSH tunnel
LLM_MODEL=qwen3.6:35b-a3b
LLM_TEMPERATURE=0.2
LLM_THINK=false
LLM_NUM_CTX=16384

# Activity API
ACT_API_BASE_URL=https://api831.yru.ac.th/act/api
ACT_API_TIMEOUT_S=15

# Service
SERVICE_KEY=change-me
CHECKPOINTER=sqlite
SQLITE_PATH=./data/aura.sqlite
CACHE=memory
LOG_LEVEL=INFO
TIMEZONE=Asia/Bangkok
```

## `config.py`

ดูโค้ดจริงที่ [src/aura_agent/config.py](../../src/aura_agent/config.py)

- เรียกใช้ผ่าน `get_settings()` (cache ด้วย `lru_cache`) ไม่สร้าง `Settings()` ตอน import ทำให้ test ส่งค่าเองได้
- `service_key` เป็น `SecretStr` ยาวอย่างน้อย 16 ตัวอักษร (ไม่โผล่ใน log/repr)
- `llm_provider`, `checkpointer`, `cache`, `log_level` เป็น `Literal` พิมพ์ค่าผิดจะ error ตั้งแต่เปิดแอป
- `LLM_PROVIDER=openai_compatible` ต้องมี `LLM_BASE_URL`

## คำสั่งตรวจสอบ

```bash
ssh -N -L 11434:localhost:11434 yruadmin@10.20.41.54
```

```bash
curl http://localhost:11434/api/tags
```

```bash
curl -H "Authorization: Bearer <JWT>" -H "Accept: application/json" https://api831.yru.ac.th/act/api/v1/report/summary/me
```

## Definition of Done

- `uv run python -c "from aura_agent.config import settings; print(settings.llm_model)"` ทำงานได้
- `curl localhost:11434/api/tags` เห็น `qwen3.6:35b-a3b`
- รู้ผลของ Q1 แล้ว (ได้ข้อมูลกลับมา หรือได้ 401)

## Handoff → Phase 1

- ส่งต่อ: โครงโปรเจ็ค, `config.py`, ผล Q1/Q2
- **ถ้า Q1 ได้ 401:** Phase 1 ยังเริ่มได้ ให้ใช้ fixture ไปก่อน แต่ต้องแจ้งเจ้าของ API ทันที
- **ถ้า Q2 ต่างจากคู่มือ:** เก็บ response จริงไว้เป็นแนวทาง โดย**ลบชื่อ อีเมล และรหัสนักศึกษาออกก่อน** แล้วค่อยเอามาทำ fixture

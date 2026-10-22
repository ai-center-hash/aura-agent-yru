# CLAUDE.md · AURA-AGENT

แชทบอทกิจกรรมนักศึกษา มรย. (LangGraph + FastAPI + Ollama) อ่าน [README.md](README.md) เพื่อดูภาพรวม

## ก่อนเริ่มงานทุกครั้ง

1. อ่าน [HANDOFF.md](HANDOFF.md) เพื่อดูสถานะ การตัดสินใจ และคำถามที่ยังเปิดอยู่
2. อ่านเอกสาร phase ที่กำลังทำใน [docs/phases/](docs/phases/)
3. จบ phase หรือจบ session: อัปเดต HANDOFF.md (สถานะ + บันทึกการส่งต่อ)

## คำสั่ง

บนเครื่องพัฒนานี้ `uv` ไม่ได้อยู่ใน PATH ให้ใช้ `python -m uv` แทน `uv` ในทุกคำสั่งด้านล่าง

```bash
uv sync                                   # ติดตั้ง
uv run pytest tests/unit                  # unit test
uv run ruff check . && uv run ruff format .
uv run python -m aura_agent.cli           # แชททดสอบ (ต้องมี AURA_DEV_JWT ใน env)
uv run uvicorn aura_agent.api.main:app --port 8000
uv run python scripts/dev_chat.py           # หน้าแชททดสอบ http://127.0.0.1/ (login ด้วย Passport ได้)
uv run python tests/evals/run_evals.py --model qwen3.6:35b-a3b
ssh -N -L 11434:localhost:11434 yruadmin@10.20.41.54   # tunnel ไป Ollama
sudo bash /opt/aura-agent/deploy/install.sh             # (บน yru-ai) deploy/อัปเดตจาก GitHub → http://10.20.41.54:8100
```

## กฎของโค้ด

- ชั้นต่างๆ: `api → agent → tools → processing / data` ชั้นล่างห้าม import ชั้นบน
- `processing/` เป็น pure function ห้ามมี I/O และห้ามเรียก `datetime.now()` (รับ `today` เป็น argument)
- ชื่อในโค้ดใช้ภาษาอังกฤษ ข้อความที่ผู้ใช้เห็น docstring ของ tool และเอกสารใช้ภาษาไทย
- async ทั้งหมด (`httpx.AsyncClient`, `AsyncSqliteSaver`)
- แก้ `prompts/system_prompt*.th.md` หรือ docstring ของ tool แล้วต้องรัน eval

## กฎความปลอดภัย (ห้ามละเมิด)

- ตัวตนมาจาก token ของผู้ใช้เท่านั้น ไม่ใช่จากข้อความที่พิมพ์ · โหมด `passport` (ค่าเริ่มต้น): YRU Passport `/oidc/userinfo` → รหัสนักศึกษา → `summary/user/{รหัส}` · โหมด `activity_me`: `summary/me` · **ห้ามมี tool ที่รับรหัสนักศึกษาหรือ user_id เป็น parameter** ยกเว้น `get_advisee_progress` ของอาจารย์ ซึ่ง `ActClient.get_advisee_summary` ตรวจทุกครั้งว่ารหัสอยู่ในรายชื่อที่ปรึกษาของเจ้าของ token (`advisor_type_ref_id` = `user_type_id` ของ Passport) ห้ามเพิ่ม tool ที่รับรหัสโดยไม่มีการตรวจแบบนี้
- บุคลากรใช้ `prompts/system_prompt_staff.th.md` และชุด tool `STAFF_TOOLS` แยกจากนักศึกษา (`tools_for`) · ข้อมูลจาก `/v1/auth/users` เก็บเฉพาะฟิลด์ใน `Advisee` ห้ามเพิ่มอีเมล/เบอร์โทร/ที่อยู่/`cid`
- **token ของ Passport ใช้กับ Passport เท่านั้น ห้ามส่งต่อให้ Activity API** (โหมด passport เรียกเส้น public โดยไม่แนบ token)
- JWT ส่งผ่าน `config["configurable"]["jwt"]` **ห้ามใส่ใน state, log หรือ cache key** (ใช้ hash แทน)
- thread_id ที่เก็บจริงคือ `f"{subject}:{thread_id}"` โดย `subject` มาจาก `ActClient.get_subject()` (โหมด passport = `passport:{sub}`)
- **ห้าม log URL ที่มีรหัสนักศึกษาหรือคำค้น** log ด้วย label แบบ template และ logger ของ httpx ถูกตั้งไว้ที่ WARNING (ดู `data/http.py`)
- Activity API เป็นข้อมูลจริง: **ห้าม commit token, response จริง หรือข้อมูลนักศึกษา** test และ eval ใช้ fixture จำลองเท่านั้น
- ห้ามเพิ่ม tool ที่เขียนข้อมูลถ้ายังไม่มี `interrupt()` ให้ผู้ใช้ยืนยัน

# AURA-AGENT

แชทบอทสำหรับนักศึกษา มรย. ตอบคำถามเรื่องกิจกรรมนักศึกษาจากข้อมูลจริงใน Activity API
เช่น "มีกิจกรรมอะไรกำลังจะเปิด", "ผมยังขาดชั่วโมงหมวดไหน", "แนะนำกิจกรรมให้ครบหน่อย"

- **LLM:** `qwen3.6:35b-a3b` บน Ollama (`10.20.41.54`), `think: false`
- **Stack:** Python 3.12 · FastAPI · LangGraph · SQLite (Phase 1)
- **โครงต้นแบบ:** [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent) + แพทเทิร์นจาก LangGraph Customer Support tutorial

## เอกสาร

| ไฟล์ | เนื้อหา |
|---|---|
| [HANDOFF.md](HANDOFF.md) | **เริ่มอ่านที่นี่** สถานะล่าสุด การตัดสินใจ และงานถัดไป |
| [docs/00-architecture.md](docs/00-architecture.md) | โครงสร้างระบบ 5 ชั้น และ flow ของข้อมูล |
| [docs/01-api-contract.md](docs/01-api-contract.md) | สัญญา API ที่ backend เรียก (`POST /v1/chat`, SSE) |
| [docs/02-activity-api-reference.md](docs/02-activity-api-reference.md) | endpoint ของ Activity API ที่ใช้ และฟิลด์ที่ต้องการ |
| [prompts/system_prompt.th.md](prompts/system_prompt.th.md) | System prompt ที่ใช้จริง (โค้ดอ่านจากไฟล์นี้) |
| [docs/phases/](docs/phases/) | แผนพัฒนาแยกเป็น phase (0–6) แต่ละ phase มี checklist, DoD และ handoff |
| [docs/03-eval-report-2026-10-20.md](docs/03-eval-report-2026-10-20.md) | ผลทดสอบคำถามที่ดึงข้อมูลกิจกรรมกับโมเดลจริง |
| [docs/04-use-cases.md](docs/04-use-cases.md) | นักศึกษา / อาจารย์ / เจ้าหน้าที่ ทำอะไรได้และไม่ได้ |
| [docs/05-openwebui-nexus.md](docs/05-openwebui-nexus.md) | ติดตั้ง AURA เป็นโมเดลใน YRU Nexus (Open WebUI Pipe) |
| [tests/fixtures/README.md](tests/fixtures/README.md) | ที่มาของ fixture และเคสที่แต่ละแถวใช้ทดสอบ (วันอ้างอิง 2026-10-20) |
| [scripts/dev_chat.py](scripts/dev_chat.py) | **หน้าแชททดลองในเครื่อง** เปิด http://127.0.0.1/ · login ด้วย YRU Passport จริง หรือเลือก persona จำลอง |
| [scripts/check_act_api.py](scripts/check_act_api.py) | ทดสอบ Activity API จริงด้วย JWT จาก env `AURA_DEV_JWT` (พิมพ์เฉพาะโครงสร้าง) |
| [tests/evals/personas/README.md](tests/evals/personas/README.md) | persona จำลอง 3 ชุดที่ใช้วัดผล และสิ่งที่แต่ละชุดใช้ทดสอบ |

## Phase การพัฒนา

| Phase | งาน | ผลลัพธ์ |
|---|---|---|
| [0](docs/phases/phase-0-setup.md) | Setup | โปรเจ็คพร้อม ต่อ Ollama และ Activity API ได้ ยืนยันว่า JWT ใช้ได้ |
| [1](docs/phases/phase-1-data-layer.md) | Data Layer | ดึงและ parse ข้อมูลจาก API พร้อม cache |
| [2](docs/phases/phase-2-processing.md) | Processing | คำนวณหมวดที่ขาด กรองกิจกรรม และแนะนำกิจกรรม |
| [3](docs/phases/phase-3-agent.md) | Tools + Agent | คุยกับบอทผ่าน CLI ได้ |
| [4](docs/phases/phase-4-api.md) | API Layer | `POST /v1/chat` stream คำตอบผ่าน SSE |
| [5](docs/phases/phase-5-evals.md) | Evals | วัดความแม่นยำและความเร็ว เทียบโมเดล |
| [6](docs/phases/phase-6-integration.md) | Integration + Pilot | ต่อกับ backend จริง และทดลองกับนักศึกษา |

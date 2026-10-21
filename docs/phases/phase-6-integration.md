# Phase 6 · Integration + Pilot

**เป้าหมาย:** ต่อกับ backend และหน้าแชทจริง deploy บน server แล้วทดลองกับนักศึกษากลุ่มเล็ก

## 1. Deploy

รัน AURA-AGENT **บนเครื่องเดียวกับ Ollama** (`10.20.41.54`) จะเรียก Ollama ผ่าน `localhost` ได้ ไม่ต้องใช้ tunnel

- [x] ติดตั้งด้วย `uv sync --frozen` แล้วรันเป็น systemd service (`aura-agent.service`, user แยก, restart อัตโนมัติ) → เตรียมแล้วใน [deploy/](../../deploy/) (`sudo bash deploy/install.sh` ใช้ทั้งติดตั้งครั้งแรกและอัปเดต)
- [x] `.env` บน server: `OLLAMA_BASE_URL=http://localhost:11434` และ `SERVICE_KEY` ใหม่ที่สุ่มยาว ≥ 32 ตัวอักษร
- [ ] firewall: port **8100** รับเฉพาะ IP ของ backend, port 11434 ไม่เปิดออกนอกเครื่อง (port 8000 ของ yru-ai เป็นของ backend Laravel อยู่แล้ว · ตอนนี้ ufw ปิดอยู่ ต้องคุยกับผู้ดูแลเครื่องก่อนเปิด เพราะมี service อื่นของทีมรันอยู่)

## 2. เชื่อมกับ Backend

- [ ] backend เรียก `POST /v1/chat` ตาม [01-api-contract.md](../01-api-contract.md) แล้ว stream ต่อไปยัง frontend โดย**ไม่ buffer** (ปิด proxy buffering เช่น nginx `proxy_buffering off`)
- [ ] frontend แสดง `status` เป็นข้อความสถานะ ต่อ `token` เป็นคำตอบ และจัดการ `error` ตาม code
- [ ] ทดสอบ end-to-end: login YRU Passport → ถาม → ได้คำตอบ

## 3. Operations

| เรื่อง | วิธีทำ |
|---|---|
| Log | JSON log: `user_hash`, `thread_id`, `tools_used`, `latency_ms`, `error_code` **ห้ามเก็บข้อความคำถามและคำตอบใน log** |
| การเก็บประวัติแชท | ลบ thread ที่ไม่มีการใช้งานเกิน 30 วัน (cron รายวัน) |
| Monitoring | cron เรียก `/v1/health` ทุก 5 นาที ถ้าล่มให้แจ้งเตือน |
| Feedback | (ถ้าทำ) `POST /v1/feedback {thread_id, rating: up/down, comment}` เก็บไว้ทำ eval เพิ่ม |

## 4. Pilot

- นักศึกษา 10–20 คน ใช้ 2 สัปดาห์ (ควรมีทั้งนักศึกษาปกติและเทียบโอน)
- เก็บข้อมูล: จำนวนคำถาม, latency, feedback 👍/👎, คำถามที่บอทตอบไม่ได้
- คำถามที่ตอบผิดให้เพิ่มเข้า `tests/evals/dataset.yaml` (ใช้ persona จำลอง ไม่ใช้ข้อมูลจริงของคนนั้น)

## Definition of Done

- ระบบรันต่อเนื่องตลอด pilot ไม่ล่ม
- 👍 ≥ 80% และไม่มีเหตุการณ์ข้อมูลรั่ว
- **รายงานสรุปสำหรับเสนอของบ:** ความแม่นยำ, latency, feedback, และข้อจำกัดของ server ปัจจุบัน (รับได้ทีละคน) พร้อม spec ที่แนะนำสำหรับใช้งานจริง

## หลัง Phase 6 → Production (server ใหม่)

เปลี่ยนค่าใน `.env` ตาม [00-architecture.md](../00-architecture.md): `LLM_PROVIDER=openai_compatible` (vLLM), `CHECKPOINTER=postgres`, `CACHE=redis` แล้วรัน eval ชุดเดิมยืนยันผลอีกรอบ

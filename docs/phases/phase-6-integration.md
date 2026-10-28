# Phase 6 · Integration + Pilot

**เป้าหมาย:** ต่อกับ backend และหน้าแชทจริง deploy บน server แล้วทดลองกับนักศึกษากลุ่มเล็ก

## 1. Deploy

รัน AURA-AGENT **บนเครื่องเดียวกับ Ollama** (`10.20.41.54`) จะเรียก Ollama ผ่าน `localhost` ได้ ไม่ต้องใช้ tunnel

- [x] ติดตั้งด้วย `uv sync --frozen` แล้วรันเป็น systemd service (`aura-agent.service`, user แยก, restart อัตโนมัติ) → เตรียมแล้วใน [deploy/](../../deploy/) (`sudo bash deploy/install.sh` ใช้ทั้งติดตั้งครั้งแรกและอัปเดต)
- [x] `.env` บน server: `OLLAMA_BASE_URL=http://localhost:11434` และ `SERVICE_KEY` ใหม่ที่สุ่มยาว ≥ 32 ตัวอักษร
- [ ] firewall: port **8100** รับเฉพาะ IP ของ backend, port 11434 ไม่เปิดออกนอกเครื่อง (port 8000 ของ yru-ai เป็นของ backend Laravel อยู่แล้ว · ตอนนี้ ufw ปิดอยู่ ต้องคุยกับผู้ดูแลเครื่องก่อนเปิด เพราะมี service อื่นของทีมรันอยู่) → คำสั่งที่เสนออยู่ข้างล่าง **ยังไม่ได้รัน**
- [x] ปิด `/docs` และ `/openapi.json` บนเครื่องจริง (`EXPOSE_DOCS=false` เป็นค่าเริ่มต้น · 2026-10-28)

### คำสั่ง firewall ที่เสนอ (ให้ผู้ดูแลเครื่องตรวจก่อนรัน)

ผู้ที่เรียก AURA: Nexus/Open WebUI (`10.20.41.108`) และ backend บนเครื่องเดียวกัน (มาทาง loopback ซึ่ง ufw ปล่อยผ่านเสมอ)
ตั้ง `default allow incoming` เพื่อไม่ให้กระทบ service อื่นของทีม แล้วปิดเฉพาะ port ของ AURA และ Ollama

```bash
ss -ltnp | grep -E ':8100|:11434'      # ดูก่อนว่าแต่ละ port ฟังที่ address ไหน
sudo ufw default allow incoming          # ไม่ปิด port อื่นที่มีอยู่ (SSH, Laravel, service ของทีม)
sudo ufw allow from 10.20.41.108 to any port 8100 proto tcp   # Nexus
# sudo ufw allow from <IP ของ backend> to any port 8100 proto tcp   # ถ้า backend อยู่คนละเครื่องหรืออยู่ใน Docker
sudo ufw deny 8100/tcp
sudo ufw deny 11434/tcp                  # Ollama ใช้แค่ในเครื่อง (dev ใช้ SSH tunnel ซึ่งมาทาง loopback)
sudo ufw enable
sudo ufw status numbered                 # rule allow ต้องอยู่ก่อน deny
```

ตรวจหลังเปิด: จาก Nexus `docker exec open-webui-4000 curl -s http://10.20.41.54:8100/v1/health` ต้องได้ผล · จากเครื่องอื่นต้องต่อไม่ได้
**ข้อควรระวัง:** ถ้า backend อยู่ใน Docker บนเครื่องนี้ request จะมาจาก bridge (`172.x`) ไม่ใช่ loopback ต้องเพิ่ม allow ให้ subnet นั้นด้วย

## 2. เชื่อมกับ Backend

- [ ] backend เรียก `POST /v1/chat` ตาม [01-api-contract.md](../01-api-contract.md) แล้ว stream ต่อไปยัง frontend โดย**ไม่ buffer** (ปิด proxy buffering เช่น nginx `proxy_buffering off`)
- [ ] frontend แสดง `status` เป็นข้อความสถานะ ต่อ `token` เป็นคำตอบ และจัดการ `error` ตาม code
- [ ] ทดสอบ end-to-end: login YRU Passport → ถาม → ได้คำตอบ

## 3. Operations

| เรื่อง | วิธีทำ |
|---|---|
| Log | JSON log: `user_hash`, `thread_id`, `tools_used`, `latency_ms`, `error_code` **ห้ามเก็บข้อความคำถามและคำตอบใน log** |
| การเก็บประวัติแชท | ✅ `aura-prune.timer` ทุกวัน 03:00 รัน `scripts/prune_threads.py`: ลบ thread ที่ไม่มีการใช้งานเกิน 30 วัน (ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ 1 วัน) · ดูผล `journalctl -u aura-prune` |
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

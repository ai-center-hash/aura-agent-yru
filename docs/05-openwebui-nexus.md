# 05 · ใช้ AURA ใน YRU Nexus (Open WebUI)

AURA ขึ้นเป็น "โมเดล" ตัวหนึ่งใน YRU Nexus ผ่าน **Pipe Function** ไฟล์เดียว: [integrations/openwebui/aura_pipe.py](../integrations/openwebui/aura_pipe.py)
ไม่ต้องสร้างหน้าแชทใหม่ และไม่ต้องแก้โค้ดของ Nexus

```
ผู้ใช้ login Nexus ด้วย YRU Passport
  → เลือกโมเดล "AURA กิจกรรมนักศึกษา"
  → Pipe ส่ง { thread_id = chat_id, message } + Authorization: Bearer <token Passport ของผู้ใช้> + X-Service-Key
  → AURA  POST http://10.20.41.54:8100/v1/chat  (SSE)
  → Pipe แปลง status เป็นสถานะใต้ข้อความ และ token เป็นคำตอบที่ไหลออกมาทีละช่วง
```

ตัวตนและสิทธิ์ (นักศึกษา / อาจารย์ที่ปรึกษา / เจ้าหน้าที่) AURA ตัดสินเองจาก token ของ Passport ดู [04-use-cases.md](04-use-cases.md)

## สิ่งที่ต้องมีก่อน

| เรื่อง | ตรวจอย่างไร |
|---|---|
| Nexus login ด้วย YRU Passport ได้ | `.env` ของ Nexus มี `YRU_PASSPORT_CLIENT_ID`, `YRU_PASSPORT_CLIENT_SECRET`, `YRU_PASSPORT_REDIRECT_URI` และหน้า login มีปุ่ม YRU Passport · Nexus เก็บ token ของ Passport ไว้ใน OAuth session แล้วส่งให้ Function เป็น `__oauth_token__` (ดู `backend/open_webui/functions.py`) |
| เครื่อง Nexus เรียก AURA ได้ | บนเครื่อง Nexus: `docker exec open-webui-4000 curl -s http://10.20.41.54:8100/v1/health` ต้องได้ `{"status":"ok",...}` |
| `SERVICE_KEY` ของ AURA | บนเครื่อง AURA: `sudo grep SERVICE_KEY /opt/aura-agent/.env` (ส่งทางช่องทางส่วนตัว ห้ามใส่ใน repo) |
| Nexus มี `httpx` และ `pydantic` | มีอยู่แล้วใน `backend/requirements.txt` ของ Open WebUI |

## ติดตั้ง (ใช้บัญชี admin ของ Nexus)

1. **Admin Panel → Functions → +** (Create new function)
2. วางเนื้อหาทั้งไฟล์ `integrations/openwebui/aura_pipe.py` · ตั้ง ID เป็น `aura` · กด **Save**
3. เปิดสวิตช์ของ Function ให้เป็น **Enabled**
4. กดรูปฟันเฟือง (**Valves**) ของ Function แล้วตั้งค่า
   - `AURA_BASE_URL` = `http://10.20.41.54:8100`
   - `AURA_SERVICE_KEY` = ค่าจาก `/opt/aura-agent/.env`
   - `MODEL_NAME` = `AURA กิจกรรมนักศึกษา` (เปลี่ยนชื่อที่ผู้ใช้เห็นได้)
5. **Admin Panel → Settings → Models** หาโมเดล `AURA กิจกรรมนักศึกษา` แล้วตั้งการมองเห็น (ทุกคน หรือเฉพาะกลุ่ม) ใส่รูป/คำอธิบายได้
6. (แนะนำ) **Admin Panel → Settings → Interface** ตั้ง Task Model เป็นโมเดลอื่น เพื่อให้การตั้งชื่อแชทใช้โมเดลนั้น
   ถ้าไม่ตั้ง Pipe จะตั้งชื่อแชทจากคำถามแรกเอง และไม่ส่งงานเบื้องหลังเหล่านี้ไปที่ AURA

## ติดตั้งหรืออัปเดตผ่าน SSH (ไม่ต้องใช้บัญชี admin ของหน้าเว็บ)

ใช้ตอนติดตั้งจริงครั้งแรก (2026-10-22) · ทำแบบเดียวกับ Admin Panel โดยเรียกโค้ดของ Open WebUI ใน container

```powershell
# บนเครื่อง dev
scp integrations\openwebuiura_pipe.py integrations\openwebui\install_in_container.py yruadmin@10.20.41.108:~/
```
```bash
# บนเครื่อง Nexus (รันทีละบรรทัด)
sudo -v
sudo docker exec open-webui-4000 python3 -c "import sqlite3,time; s=sqlite3.connect('/app/backend/data/webui.db'); d=sqlite3.connect('/app/backend/data/webui.db.bak-'+time.strftime('%Y%m%d-%H%M%S')); s.backup(d)"
sudo docker cp ~/aura_pipe.py open-webui-4000:/tmp/aura_pipe.py
sudo docker cp ~/install_in_container.py open-webui-4000:/tmp/install_in_container.py
 AURA_KEY='ค่า SERVICE_KEY'          # ขึ้นต้นด้วยช่องว่าง จะได้ไม่เข้า history
echo "$AURA_KEY" | sudo docker exec -i -w /app/backend -e PYTHONPATH=/app/backend open-webui-4000 python3 /tmp/install_in_container.py
unset AURA_KEY
sudo docker exec open-webui-4000 rm -f /tmp/install_in_container.py /tmp/aura_pipe.py; rm -f ~/install_in_container.py ~/aura_pipe.py
```

สำเร็จจะได้ `{"action": "created" หรือ "updated", "id": "aura", "is_active": true, ..., "has_valves": true}`

## ทดสอบหลังติดตั้ง

ออกจากระบบแล้ว login ใหม่ด้วย **YRU Passport** (บัญชีรหัสผ่านของ Nexus ใช้ไม่ได้ เพราะไม่มี token ของ Passport) แล้วถาม

| บัญชี | คำถาม | ควรได้ |
|---|---|---|
| นักศึกษา | ผมยังขาดกิจกรรมหมวดไหน | หมวดที่ขาดของตัวเอง |
| อาจารย์ที่ปรึกษา | ขอรายชื่อนักศึกษาในที่ปรึกษาทั้งหมด | รายชื่อครบพร้อม x/y กิจกรรม |
| ทุกบัญชี | มีกิจกรรมอะไรเปิดรับสมัครบ้าง | ระหว่างรอจะเห็นสถานะ "กำลังค้นหากิจกรรม..." แล้วได้คำตอบ |

## ข้อความที่ผู้ใช้อาจเห็น

| ข้อความ | สาเหตุ / วิธีแก้ |
|---|---|
| AURA ใช้ได้เมื่อเข้าสู่ระบบด้วย YRU Passport เท่านั้น | ผู้ใช้ login ด้วยรหัสผ่านของ Nexus หรือ OAuth session หมดอายุ → login ใหม่ด้วย Passport |
| ผู้ดูแลระบบยังไม่ได้ตั้งค่า AURA | ยังไม่ได้ใส่ `AURA_SERVICE_KEY` ใน Valves |
| ระบบ AURA ปฏิเสธการเชื่อมต่อจาก Nexus | `AURA_SERVICE_KEY` ไม่ตรงกับ `SERVICE_KEY` ของ AURA |
| ตอนนี้ติดต่อระบบ AURA ไม่ได้ | เครื่อง Nexus เรียก `10.20.41.54:8100` ไม่ได้ หรือ AURA ล่ม → `systemctl status aura-agent` บนเครื่อง AURA |
| เซสชันหมดอายุแล้วครับ กรุณาเข้าสู่ระบบใหม่ | Passport ไม่รับ token แล้ว → login Nexus ใหม่ |

## หมายเหตุ

- ห้องแชทของ Nexus (`chat_id`) = ห้องแชทของ AURA · ลบแชทใน Nexus ยังไม่ลบประวัติฝั่ง AURA (ลบได้ด้วย `DELETE /v1/chat/{thread_id}`)
- Pipe ส่งไปเฉพาะข้อความล่าสุดของผู้ใช้ AURA จำบทสนทนาก่อนหน้าเองจาก `thread_id`
- แชทชั่วคราว (temporary chat) ไม่มี `chat_id` จริง จึงใช้ห้อง `nexus-{user id}` ร่วมกัน
- ไฟล์ Pipe ไม่ log และไม่เก็บ token · ทดสอบอยู่ใน `tests/unit/test_openwebui_pipe.py`
- อัปเดต Pipe: แก้ไฟล์ใน repo → รัน `pytest tests/unit/test_openwebui_pipe.py` → วางเนื้อหาใหม่ใน Admin Panel → Functions → aura → Save

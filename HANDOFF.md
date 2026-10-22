# HANDOFF · AURA-AGENT

> เอกสารส่งต่องาน อัปเดตทุกครั้งที่จบ phase หรือจบ session
> **อัปเดตล่าสุด:** 2026-10-21 · หน้าแชททดสอบ login ด้วย YRU Passport จริงได้แล้ว (http://127.0.0.1/)
> ยืนยันตัวตนผ่าน Passport + เส้น public ของ Activity API · test 345/345 ผ่าน

## สถานะ

| Phase | สถานะ | หมายเหตุ |
|---|---|---|
| 0 · Setup | ✅ | tunnel + Ollama ใช้ได้ · Q1 ตอบแล้ว (Activity API ไม่รับ token ของ Passport → ใช้เส้น public แทน) |
| 1 · Data Layer | ✅ | **schema ทั้ง 3 ชุดผ่านข้อมูลจริงแล้ว** (`Schedule` 32 รอบ, `Registration` 50 แถว, `StudentSummary` นักศึกษา 15 คนที่มีกรอบกิจกรรม) |
| 2 · Processing | ✅ | ผ่าน DoD · กรองด้วย `target_student_codes` ตามข้อมูลจริงแล้ว · รอ Q4/Q7 ยืนยันกติกา |
| 3 · Tools + Agent | 🟡 เกือบเสร็จ | คุยกับโมเดล + token จริงแล้ว · `analyze_gaps`/`filter_eligible`/`recommend` รันกับข้อมูลจริงได้ · บั๊ก 2 จุดจากชื่อประเภทจริง**แก้แล้ว** (2026-10-21) · รอ Q9 ยืนยันว่าหมวดไหนบังคับ |
| 4 · API | 🟡 เกือบเสร็จ | test ครบ · SSE ใช้จริงผ่านหน้าแชทแล้ว · ยังไม่ได้ curl `/v1/chat` ของ API ตัวจริง (มี service key) ด้วย token จริง |
| 5 · Evals | 🟡 เกือบเสร็จ | 45 ข้อ (เพิ่ม persona โครงสร้างจริง 5 ข้อ) · `qwen3.6:35b-a3b` **ผ่านทุกเกณฑ์** (2026-10-21: tool 98% · fact 98% · safety 100% · TTFT p50 1.7 วิ · กุข้อมูล 0) · **ยังไม่ได้เทียบโมเดลที่ 2** (`bonsai-2:27b`) · `recommend-02` ยังตก |
| 6 · Integration + Pilot | 🟡 | **deploy แล้ว** `http://10.20.41.54:8100` (2026-10-21) · บุคลากรใช้ได้ขั้นที่ 1 (deploy `670a21a` 2026-10-22) · ต่อไป: backend ต่อเข้ามาทดสอบ, ops (log JSON, ลบ thread เก่า, firewall), pilot 10–20 คน |

สัญลักษณ์: ⬜ ยังไม่เริ่ม · 🟡 กำลังทำ · ✅ เสร็จ (ผ่าน DoD) · ⛔ ติดปัญหา

## เริ่มงานต่อจากตรงนี้

**บอทคุยกับข้อมูลจริงได้แล้ว** (ทดสอบ 2026-10-21 ด้วยบัญชีนักศึกษาทดสอบที่ยังไม่มีกรอบกิจกรรม)

```powershell
ssh -N -L 11434:localhost:11434 yruadmin@10.20.41.54        # หน้าต่างที่ 1 (tunnel ไป Ollama)
python -m uv run python scripts/dev_chat.py                 # หน้าต่างที่ 2 → http://127.0.0.1/
```

ในหน้าแชทเลือก "บัญชี YRU Passport ของฉัน" แล้วกด **เข้าสู่ระบบด้วย YRU Passport** (login จริง)
หรือเลือก persona จำลองถ้าไม่อยากใช้ข้อมูลจริง · ต้องมี `PASSPORT_CLIENT_ID` / `PASSPORT_CLIENT_SECRET` ใน `.env`
และเปิดที่ **port 80** เพราะ callback ที่ลงทะเบียนไว้กับ Passport คือ `http://127.0.0.1/callback`

**รอคำตอบจากเจ้าของ API** (ส่งข้อความชุดเดียวได้ ดูตาราง "คำถามที่ยังเปิดอยู่")

1. **Q7** `target_student_codes` คือรายชื่อที่สมัครได้ใช่ไหม — โค้ดตอนนี้ถือว่าใช่ (ข้อมูลจริงใช้ 30/32 รอบ)
2. **Q8** ระบบกิจกรรมออก token ของตัวเองอย่างไร — ถ้ารับ token ได้ เปลี่ยน `IDENTITY_MODE=activity_me` ได้เลย
3. **Q4** `target_student_year_prefix` เทียบกับอะไร (ใช้แค่ 3/32 รอบ)
4. ขอบัญชีนักศึกษาทดสอบที่**มีกรอบกิจกรรม** เพราะบัญชีที่มีอยู่เป็น `no_frame` จึงยังไม่เคยเห็น `StudentSummary` จริง (Q2)

**ทำต่อได้เลยโดยไม่ต้องรอ:** แก้ข้อ `recommend-02` ใน eval, ขึ้นบรรทัดใหม่ระหว่างข้อความก่อน/หลังเรียก tool, เทียบโมเดลตัวที่สอง (`bonsai-2:27b`), เริ่ม Phase 6

## สภาพแวดล้อม

| รายการ | ค่า |
|---|---|
| Ollama server | `ssh yruadmin@10.20.41.54` (hostname `yru-ai`) · port 11434 (เปิดแค่ localhost ช่วงพัฒนาให้ใช้ SSH tunnel) |
| Hardware | i7-10700KF 16 threads · RAM 29 GB · RTX 2080 Ti 11 GB · NVMe 457 GB |
| โมเดล | `qwen3.6:35b-a3b` (22.6 GB, 35.5B Q4_K_M, MoE 3B active, ใช้ GPU+CPU) — **บนเซิร์ฟเวอร์มีตัวนี้ตัวเดียว** |
| วัดได้จริง 2026-10-20 | โหลดโมเดลครั้งแรก 21.7 วิ · **50.5 token/วิ** (คำตอบสั้น) · GPU ว่างตอนไม่ใช้งาน (69 MiB/11 GB) |
| ตั้งค่า Ollama | `NUM_PARALLEL=1`, `CONTEXT_LENGTH=16384`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`, `KEEP_ALIVE=-1` |
| Activity API | `https://api831.yru.ac.th/act/api` (**ข้อมูลจริง** ไม่มี UAT แยก) |
| เครื่องพัฒนา | Windows · uv 0.13.3 ติดตั้งผ่าน `pip install --user` (ไม่ได้อยู่ใน PATH ให้ใช้ `python -m uv ...`) · Python 3.12.15 (uv จัดการให้) |
| SSH ไป server | ใช้รหัสผ่าน (ยังไม่มี SSH key) · **ควรทำ SSH key แล้วปิด password login** จะได้ไม่ต้องส่งรหัสกันไปมา |
| คู่มือ API | https://top-ita.github.io/act-aihub-api/ |

## การตัดสินใจ

| วันที่ | เรื่อง | ตัดสินใจ | เหตุผล |
|---|---|---|---|
| 2026-10-20 | Framework | LangGraph + FastAPI | โครงตาม `langchain-ai/react-agent` ซึ่งเป็น template ทางการ |
| 2026-10-20 | รูปแบบ agent | agent ตัวเดียว + 4 tools | API มีแค่ 5 เส้นและอ่านอย่างเดียว การแยกหลาย assistant ทำให้ยุ่งโดยไม่จำเป็น |
| 2026-10-20 | โมเดล | `qwen3.6:35b-a3b`, `think: false` | วัดได้ 35–37 token/วิ ตอบสั้นเสร็จใน 4.1 วิ (เปิด thinking ใช้ 59.5 วิ) |
| 2026-10-20 | ขอบเขต Phase 1 | ใช้คนเดียว, SQLite, cache ใน memory | ทดสอบให้ได้ผลก่อน ถ้าดี มหาวิทยาลัยมีงบ server เพิ่ม |
| 2026-10-20 | ตัวตนผู้ใช้ | JWT จาก YRU Passport ส่งผ่าน backend | กัน IDOR เพราะใช้ `/summary/me` แทน `/summary/user/{id}` |
| 2026-10-20 | สิทธิ์ | อ่านอย่างเดียว | เขียนข้อมูลเมื่อไร ต้องเพิ่ม `interrupt()` ให้ผู้ใช้ยืนยันก่อน |
| 2026-10-20 | การส่งคำตอบ | SSE ผ่าน backend เดิม | frontend แสดงคำตอบได้ทีละคำ |
| 2026-10-20 | error ของชั้น data | exception มี `code` + `message_th` ตรงกับ [01-api-contract.md](docs/01-api-contract.md) | ชั้น API หยิบไปใส่ `event: error` ได้เลย ไม่ต้องมีตารางแปลงซ้ำสองที่ |
| 2026-10-20 | 4xx ที่ไม่ใช่ 401 | เพิ่ม `UpstreamRejected` (ไม่ retry) | แผนเดิมมี 3 error ทำให้ 403/404/422 ไม่มีที่ไป และไม่ควรถูกนับเป็น timeout |
| 2026-10-20 | cache | `cachetools.TLRUCache` + interface async | ตั้ง TTL ต่อ key ได้ (120/60 วิ) และสลับไป Redis ใน Phase 2 ได้โดยไม่แก้ `ActClient` |
| 2026-10-20 | ข้อมูลส่วนบุคคล | schema ไม่ประกาศฟิลด์ที่ไม่ได้ใช้ (`email`, `user_name`, `user_code`) | `extra="ignore"` ทิ้งให้เอง ข้อมูลที่ไม่ได้ใช้จึงไม่ค้างในหน่วยความจำหรือใน error |
| 2026-10-20 | ผลของ `filter_eligible` | คืน `EligibleSchedule` (ห่อ `Schedule` + ธง `eligibility_uncertain`) | ธงเป็นข้อสรุปของ processing จะไปใส่ใน schema ของชั้น data ไม่ได้ |
| 2026-10-20 | เงื่อนไขรุ่นปี (Q4) | ปล่อยผ่าน + ติดป้าย "ไม่แน่ใจเรื่องสิทธิ์สมัคร" | ตัดทิ้งไปเลยจะซ่อนกิจกรรมที่สมัครได้จริง ให้ผู้ใช้ไปตรวจในระบบเองปลอดภัยกว่า |
| 2026-10-20 | ชื่อหมวดในข้อความ | ใช้ชื่อเต็มจาก API ไม่ย่อ | prompt ห้ามบอทแต่งชื่อหมวด/กิจกรรมเอง ย่อแค่ประเภทเป็น (บังคับ)/(เลือก) |
| 2026-10-20 | dependency | เพิ่ม `tzdata` (runtime) และ `pytest-cov` (dev) | Python ของ uv บน Windows ไม่มี tz database ทำให้ `ZoneInfo("Asia/Bangkok")` error · pytest-cov ใช้วัด DoD ของ Phase 2 |
| 2026-10-20 | serializer ของ checkpointer | สร้าง `AsyncSqliteSaver` เองพร้อม `state_serializer()` ที่ allow `StudentProfile` | langgraph 1.2 เตือนว่าชนิดที่ไม่ได้ลงทะเบียนจะถูกบล็อกในเวอร์ชันถัดไป ถ้าไม่ทำตอนนี้ประวัติแชทจะพังตอนอัปเกรด |
| 2026-10-20 | เวลา | `clock.py` ที่ root ของแพ็กเกจ | `processing/` ห้ามเรียก `datetime.now()` และ `tools/` import จาก `agent/` (ชั้นบน) ไม่ได้ |
| 2026-10-20 | การ inject ของปลอมใน test | เพิ่ม `set_act_client()` และ `get_llm()`/`set_llm()` | ทดสอบทั้ง graph ได้โดยไม่ต่อ Ollama หรือ Activity API เลย |
| 2026-10-20 | ที่อยู่ของ `LLMUnavailable` | ให้ node `agent` แปลง error ของ Ollama เป็น `LLMUnavailable` | ชั้น api ไม่ต้องรู้จัก Ollama และใช้ `except (ActApiError, AgentError)` ก้อนเดียวจบ |
| 2026-10-20 | สถานะ tool ใน SSE | อ่านจากทั้งโหมด `messages` และ `updates` | โหมด `messages` รู้ชื่อ tool เร็วกว่า แต่โหมด `updates` ครบแน่นอน · ส่ง status ครั้งเดียวต่อ tool |
| 2026-10-20 | `create_app(graph=...)` | เปิดช่องให้ใส่ graph ปลอม | test ยิง API จริงผ่าน ASGI ได้โดยไม่สร้าง ActClient จริงและไม่เขียนไฟล์ SQLite |
| 2026-10-20 | eval reproducibility | ตรึง `clock.today()` ที่ 2026-10-20 และใช้ `temperature=0` | ไม่งั้นผล eval เปลี่ยนไปตามวันที่รันและตามการสุ่มของโมเดล |
| 2026-10-20 | โหมด `--self-test` ของ eval | เพิ่มโมเดลปลอมที่ตอบด้วยผลของ tool | ตรวจ dataset/fixture/รายงานได้โดยไม่ต้องมี Ollama (เจอข้อที่เขียนเกณฑ์ผิดจริง 1 ข้อ) |
| 2026-10-21 | **การยืนยันตัวตน** | ใช้ YRU Passport `/oidc/userinfo` → รหัสนักศึกษา → `summary/user/{รหัส}` (public) · เลือกโหมดด้วย `IDENTITY_MODE` | Activity API ตอบ 401 กับ token ของ Passport (Q1) แต่เส้น public ใช้ได้ · ยังรักษากฎ "ตัวตนมาจาก token" ได้ครบ · เปลี่ยนกลับเป็น `activity_me` ได้ทันทีเมื่อเจ้าของ API พร้อม (Q8) |
| 2026-10-21 | ไม่ส่ง token ของ Passport ให้ Activity API | โหมด passport เรียกทุกเส้นของ Activity API โดยไม่แนบ token | token เป็นของ Passport การส่งให้ระบบอื่นคือการแจก credential โดยไม่จำเป็น และเส้นที่ใช้เป็น public อยู่แล้ว |
| 2026-10-21 | แยกประวัติแชทด้วย `passport:{sub}` | แทน user_id ของ Activity API | ได้ตัวตนแม้นักศึกษายังไม่มีกรอบกิจกรรม และไม่ต้องเก็บรหัสนักศึกษาไว้ใน key |
| 2026-10-21 | ปิด log ของ httpx ที่ระดับ INFO | ตั้ง logger `httpx`/`httpcore` เป็น WARNING ใน `data/http.py` | test จับได้ว่า httpx log URL เต็มที่มีรหัสนักศึกษาและคำค้น |
| 2026-10-21 | login ในหน้าแชททดสอบ | Authorization Code flow แบบ server แลก code เอง + session ฝั่ง server + cookie HttpOnly | client secret และ access token ไม่ไปถึงเบราว์เซอร์เลย · ใช้เป็นต้นแบบให้ทีม backend ได้ (pattern เดียวกับที่ backend ควรทำก่อนส่ง token ให้ AURA) |

## คำถามที่ยังเปิดอยู่

| # | คำถาม | ใครตอบ | สถานะ |
|---|---|---|---|
| Q1 | JWT ของ YRU Passport ใช้กับ `/summary/me` ได้ไหม | — | ⛔ **ตอบแล้ว 2026-10-21: ใช้ไม่ได้** · ล็อกอินจริงด้วยบัญชี `user_type=student` ผ่าน Passport (client 269) ได้ access token (JWT, อายุ 1 ปี, มี refresh_token, **ไม่มี id_token**) แล้วยิง `/summary/me` → **401 `UNAUTHENTICATED`** · Activity API ไม่รับ token ของ Passport |
| Q2 | response ของ `/summary/me` เหมือน `/summary/user/{id}` ไหม | — | ✅ **ไม่จำเป็นแล้ว** · โหมด passport ใช้ `/summary/user/{id}` ซึ่งตรวจกับข้อมูลจริงแล้วว่าตรง `StudentSummary` (2026-10-21) |
| Q3 | `/act/activities` แบบ Student Mode กรองตามสิทธิ์ของผู้ที่ login ไหม | — | ⛔ **ใช้ไม่ได้** · คืน 0 รายการทั้งแบบส่งและไม่ส่ง token (Management mode คืน 377) จึงกรองสิทธิ์เองต่อไป |
| Q4 | `target_student_year_prefix` เทียบกับฟิลด์ไหน | เจ้าของ API | 🟡 ยังต้องถาม แต่ความสำคัญลดลง: ข้อมูลจริงใช้ฟิลด์นี้แค่ **3/32 รอบ** (ค่า `66`, `68`) |
| Q5 | `act-registrations?user_id=` เป็น public หรือต้องใช้ token | — | ✅ **ตอบแล้ว 2026-10-21: public จริง** · `summary/user/{รหัสนักศึกษา}` ไม่ส่ง token ก็ได้ HTTP 200 (ส่ง token ก็ 200 เหมือนกัน คือไม่สนใจ token) |
| Q6 | บอทแทนตัวเองว่า "ผม/ครับ" หรือ "ดิฉัน/ค่ะ" (ตอนนี้ใช้ "ครับ") | เจ้าของโปรเจ็ค | ⬜ |
| Q7 | **(ใหม่)** `target_student_codes` คืออะไร — รายชื่อรหัสนักศึกษาที่อนุญาตให้สมัครได้ใช่ไหม และถ้ามีค่าแล้วฟิลด์ `target_*` อื่นยังมีผลไหม | เจ้าของ API | ⬜ **สำคัญกว่า Q4** เพราะข้อมูลจริงใช้ฟิลด์นี้ 30/32 รอบ |
| Q8 | **(ใหม่)** ระบบกิจกรรมออก token ของตัวเองอย่างไร (เส้น login, อายุ, refresh) เพื่อให้ `/summary/me` ใช้งานได้ | เจ้าของ API | ⬜ blocker ของการยืนยันตัวตนแบบที่ออกแบบไว้ |
| Q9 | ประเภทกิจกรรมจริงมี 2 แบบคือ "กิจกรรมมหาวิทยาลัย" กับ "กิจกรรมเพื่อเสริมสร้างสมรรถนะทั่วไป" — แบบไหนบังคับ? และหมวด "กิจกรรมบังคับ" (category 1) เป็นหมวดเดียวที่บังคับใช่ไหม | กองพัฒนานักศึกษา / เจ้าของ API | ⬜ ตอนนี้บอทถือว่าหมวดที่มีคำว่า "บังคับ" ในชื่อหมวดหรือชื่อประเภทเป็นหมวดบังคับ (ข้อมูลจริงคือหมวด 1) ไม่เดาจากประเภท |

## สิ่งที่รู้จาก API จริง (ยิงจริงเมื่อ 2026-10-21)

| เรื่อง | ผล |
|---|---|
| `Schedule` schema | ✅ **ผ่านข้อมูลจริงทั้ง 32 รอบ** (`list[Schedule]` validate ผ่าน) ข้อมูลจริงมีฟิลด์มากกว่าคู่มือเยอะ (face scan, waitlist, `viewer_registration_status`, `primary_action_*`) แต่ `extra="ignore"` รับมือได้ |
| การจำกัดสิทธิ์สมัครจริง | **ทุกรอบ (32/32) เป็น `is_restricted: true`** · `target_student_codes` มีค่า **30/32 รอบ** (รายรหัสนักศึกษา) · `target_student_year_prefix` 3/32 · `target_faculties`, `target_curriculums`, `target_student_status` **ไม่ถูกใช้เลย (0/32)** |
| ผลต่อโค้ด | `filter_eligible` ตอนนี้กรองด้วย faculty/status/year_prefix ซึ่ง**ไม่ตรงกับของจริง** ต้องอ่าน `target_student_codes` มาเทียบกับรหัสนักศึกษาของผู้ใช้ |
| สถานะกิจกรรมตอนนี้ | 32 รอบเป็น `inactive` ทั้งหมด · **เปิดรับสมัคร 0 รอบ** · เต็มแล้ว 7 รอบ (ถ้า pilot ตอนนี้ คำถาม "มีอะไรเปิดรับสมัคร" จะตอบว่าไม่มี) |
| กรณีไม่มีกรอบกิจกรรม | บัญชีทดสอบได้ `{"success": true, "no_frame": true, "message": "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้", "data": null}` → **โค้ดปัจจุบันจะโยน `UpstreamSchemaError`** เพราะ `_unwrap` ต้องการ `data` เป็น dict · ต้องแก้ให้บอกผู้ใช้ว่ายังไม่มีกรอบกิจกรรม |
| Passport (client 269) | OAuth Authorization Code ใช้งานได้ · `/oidc/userinfo` คืน `username` = รหัสนักศึกษา 9 หลัก, `user_type=student`, คณะอยู่ใน `org_unit_1_name` · **`program_id`/`program_name` ว่าง** · access token อายุ 1 ปี (ยาวผิดปกติ ควรแจ้งทีม Passport) |

## ⚠ API เปิดข้อมูลส่วนบุคคลโดยไม่ต้องใช้ token (ตรวจ 2026-10-21) — ต้องแจ้งเจ้าของ API

ตรวจโดยดูแค่**ชื่อฟิลด์** ไม่ได้อ่านหรือเก็บค่าของใคร · ทุกเส้นตอบ HTTP 200 โดยไม่ส่ง token

| เส้น | ข้อมูลที่ใครก็ดึงได้ |
|---|---|
| `GET /v1/auth/users` | รายชื่อนักศึกษาพร้อม `address`, `telephone`, `email`, `fname`/`lname`, `nickname`, `username`, `advisor_name`, `faculty`, `program`, `roles`, `permissions` — **ร้ายแรงที่สุด** (คู่มือเขียนว่า "บังคับ Advisor" แต่ของจริงไม่บังคับ) |
| `GET /v1/act/act-registrations` | ประวัติลงทะเบียนของทุกคน พร้อม `user_name`, `user_email`, `user_code` |
| `GET /v1/act/activities?with_trashed=true` | กิจกรรมโหมดจัดการ 377 รายการ พร้อม `organizer_contact`, `creator`, `approver` และรายรหัสนักศึกษา `target_student_codes` |
| `GET /v1/report/summary/user/{id}` | ความคืบหน้ากิจกรรมของใครก็ได้ถ้ารู้รหัส |

AURA ไม่ใช้ `/auth/users` และ `/act/activities` และใช้ `summary/user/{id}` ด้วยรหัสที่ได้จาก token ของผู้ใช้เท่านั้น
แต่ช่องโหว่ฝั่ง API ยังอยู่ และน่าจะเข้าข่าย PDPA

## สิ่งที่รู้จากการตรวจ API ทั้ง 5 เส้น (2026-10-21)

| เรื่อง | ผล |
|---|---|
| schema ทั้ง 3 ชุด | ✅ `Registration` ผ่าน 50 แถว · `StudentSummary` ผ่านกับนักศึกษาที่มีกรอบกิจกรรม (สุ่มจากผู้ลงทะเบียน 15/15 คนมีกรอบ) · `Schedule` ผ่าน 32 รอบ |
| `summary.user` | มี `student_id` จริง → การกรองด้วย `target_student_codes` ใช้ได้กับนักศึกษาที่มีกรอบ |
| โครงสร้างกรอบจริง | 14 หมวด หมวดละ 1 frame_item · เช่น "กิจกรรมบังคับ" (เกณฑ์ 9 กิจกรรม/30 ชม.), "ชมรมนักศึกษา", "จิตอาสา ชั้นปีที่ 1–3", "ด้านคุณธรรมและจริยธรรม" · `overall_status` จริงเป็น `not_passed` |
| ฟิลด์ที่มีแต่ยังไม่ใช้ | `frame_item.planned_activities` (ลงไว้แต่ยังไม่นับ) · `registration.schedule.category_name` (ลงทะเบียนนี้นับหมวดไหน) |
| สถานะระบบตอนนี้ | กิจกรรม 377 รายการ "อนุญาต" แต่ "รอประกาศ" · รอบทั้งหมด 991 รอบ เผยแพร่แค่ 32 และ**ปิดรับสมัครหมดแล้ว** → pilot ควรรอช่วงที่รอบใหม่เปิดรับ |
| `target_student_codes` | รอบละ 0–201 รหัส · นักศึกษาตัวอย่างไม่อยู่ใน 24/32 รอบ · บางรอบมี 201 รหัสแต่รับ 200 คน → อาจเป็นรายชื่อที่นำเข้าไว้ล่วงหน้ามากกว่ารายชื่อมีสิทธิ์สมัคร (Q7) |
| ✅ **บั๊ก 1: หมวดบังคับ** (แก้แล้ว 2026-10-21 · `is_mandatory_category` ดูทั้งชื่อหมวดและชื่อประเภท) | ประเภทจริงคือ "กิจกรรมมหาวิทยาลัย" / "กิจกรรมเพื่อเสริมสร้างสมรรถนะทั่วไป" ไม่มีคำว่า "บังคับ" ส่วน "กิจกรรมบังคับ" เป็น**ชื่อหมวด** → `Gap.is_mandatory` เป็น False ทุกหมวด การแนะนำ "กิจกรรมบังคับก่อน" จึงไม่ทำงานกับข้อมูลจริง (fixture ใช้ "กิจกรรมบังคับ" เป็นชื่อประเภท test เลยไม่จับ) |
| ✅ **บั๊ก 2: ป้ายประเภท** (แก้แล้ว 2026-10-21 · ย่อแค่ "กิจกรรมบังคับ/เลือก" ประเภทอื่นต่อท้ายเต็มด้วย " · ") | `_short_type` ตัดคำว่า "กิจกรรม" ออก จึงได้ "(มหาวิทยาลัย)" และ "(เพื่อเสริมสร้างสมรรถนะทั่วไป)" ต่อท้ายชื่อหมวด อ่านแล้วงง |
| fixture/persona | โครงสร้างหมวดในข้อมูลจำลองต่างจากของจริงมาก (4 หมวดสมมติ vs 14 หมวดจริง) eval จึงไม่จับบั๊กข้างบน → ✅ เพิ่ม persona `realistic_with_gaps` (กติกากรอบจริง + นักศึกษาสมมติ) แล้ว |

## บันทึกการส่งต่อแต่ละ phase

<!-- คัดลอก template นี้ทุกครั้งที่จบ phase แล้วใส่ไว้บนสุดของส่วนนี้

### Phase N · ชื่อ · YYYY-MM-DD
- **เสร็จแล้ว:** ...
- **ผล DoD:** (คำสั่งที่รัน + ผล)
- **เปลี่ยนจากแผน:** ... (และเหตุผล)
- **ปัญหาที่รู้อยู่:** ...
- **Phase ถัดไปต้องรู้:** ...
-->

### ทดสอบกับบัญชีจริง 2 role บนเครื่อง yru-ai · 2026-10-22
- **วิธี:** login Passport ด้วยบัญชีทดสอบที่ผู้ใช้ให้มา (สคริปต์ใน scratchpad ไม่ commit ไม่เก็บรหัส/token) → ยิง `POST http://10.20.41.54:8100/v1/chat` เวอร์ชัน `670a21a`
- **อาจารย์** (`user_type="staff"`, `position_name="อาจารย์"`): ทักชื่อถูก · ค้นหากิจกรรมได้ (ตอนนี้ไม่มีรอบเปิด) · ถามหมวดที่ขาด → ตอบว่าใช้ได้เฉพาะนักศึกษา · ขอดูนักศึกษารหัสอื่น → ปฏิเสธ ✅
- **นักศึกษาที่มีกรอบกิจกรรมจริง** (ครั้งแรกที่เห็น `StudentSummary` จริงผ่านบอท · Q2 ✅): ตอบหมวดที่ขาดจาก [ความคืบหน้า] (กิจกรรมบังคับ ขาด 1 กิจกรรม/3 ชม.) · ประวัติลงทะเบียนจริง 10 รายการล่าสุด · แนะนำ → ไม่มีรอบที่ตรงหมวดที่ขาด · ขอดูรหัสอื่น → ปฏิเสธ ✅
- **ข้อสังเกตคุณภาพคำตอบ:** บางคำตอบเรียกผู้ใช้ว่า "นักศึกษา" แบบบุรุษที่ 3 แทน "คุณ" · คำตอบแนะนำมีประโยคอธิบายกติกาที่ไม่ได้มาจากข้อมูล ("กิจกรรมบังคับมักจะเป็นกิจกรรมเฉพาะช่วงเปิดภาคเรียน…") ขัดกฎข้อ 3 ของ prompt · บางคำตอบมี emoji
- **ข้อมูลสำหรับขั้นที่ 2 (อาจารย์ดูนักศึกษาในสาขา):** claim ของอาจารย์มี `position_name="อาจารย์"` แต่ **`program_id`/`program_name` เป็น null** และ `org_unit_1_name` มีแค่ระดับคณะ → **Passport บอกไม่ได้ว่าอาจารย์สังกัดสาขาไหน** ต้องได้ข้อมูลนี้จาก backend หรือระบบอื่น · ฝั่งนักศึกษามี `program_name` (ชื่อหลักสูตรเต็ม) แต่ `program_id` เป็น null
- **userinfo มี claim `cid`** (น่าจะเป็นเลขบัตรประชาชน) — `PassportUser` ไม่อ่านฟิลด์นี้ (`extra="ignore"`) ห้ามเพิ่มเข้ามา

### บุคลากรใช้บอทได้ (ขั้นที่ 1) · 2026-10-22
- **ทำแล้ว:** อาจารย์/เจ้าหน้าที่/แอดมินที่ login ผ่าน Passport ไม่ได้ `NOT_STUDENT` แล้ว · `PassportClient.get_identity` คืนตัวตนทุกประเภท · `ActClient.get_my_summary` โยน `NotAStudent(identity=...)` สำหรับบุคลากร**โดยไม่เรียก Activity API** (username บุคลากรไม่ใช่รหัสนักศึกษา) · `load_student` สร้าง `StudentProfile(is_student=False, student_id=None)` + `format_not_student()` ใส่ใน [ความคืบหน้า] · `search_activities` ของบุคลากรใช้ `filter_open` (ทุกรอบที่ยังรับสมัคร ไม่คัดคุณสมบัติ) + ป้าย "เปิดเฉพาะบางกลุ่ม" · progress/registrations/recommend ตอบว่าใช้ได้เฉพาะนักศึกษา และไม่เรียก API · หน้าแชททดสอบให้บุคลากร login ได้ + persona `staff_member` · eval เพิ่ม 5 ข้อ (`progress-13`, `search-12`, `recommend-10`, `history-08`, `safety-07`) รวม 50 ข้อ
- **ไม่ได้ทำ (ขั้นที่ 2 รอทีมตกลง):** บุคลากรดูข้อมูลนักศึกษาคนอื่น (อาจารย์ที่ปรึกษาดูนักศึกษาในความดูแล ฯลฯ) — ต้องรู้ว่าใครดูใครได้จาก backend/ระบบกิจกรรม, ต้องแก้กฎ "ห้าม tool รับรหัสนักศึกษา" ให้โค้ดตรวจขอบเขตทุกครั้ง, และควรรอให้ Activity API ปิดช่องโหว่ข้อมูลก่อน
- **บทเรียน:** ลองแก้ system prompt 2 บรรทัด ("นักศึกษาที่คุยด้วย" → "ผู้ใช้ที่คุยด้วย" + ย่อหน้าเรื่องบุคลากร) ทำให้ข้อของ**นักศึกษา**แย่ลงชัดเจน (`progress-05`, `recommend-03`, `recommend-09` ตกทุกรอบ, `recommend-02` กุรายชื่อกิจกรรมขึ้นเอง) · ย้อน prompt กลับเป็นเดิม แล้วบอกเรื่องบุคลากรผ่าน [ความคืบหน้า] + ผลของ tool อย่างเดียว → ข้อเหล่านั้นกลับมาผ่าน 2/2 รอบ · **prompt ไม่ได้เปลี่ยนในรอบนี้**
- **ผล:** `pytest tests/unit` → **373 passed** · ruff ผ่าน · eval 50 ข้อ `qwen3.6:35b-a3b` → **ผ่านทุกเกณฑ์** tool 96% · fact 98% · safety 100% · TTFT p50 1.9 วิ · กุข้อมูล 0 · บุคลากรผ่าน 5/5 · ข้อที่ตก (`recommend-02`/`-08` เรียก `get_my_progress` เพิ่ม, `recommend-03`) เปลี่ยนไปมาระหว่างรอบ — รันแยกเฉพาะข้อผ่านหมด
- **deploy แล้ว** `670a21a` บน yru-ai (2026-10-22) · `/v1/health` ok · ถามจริงด้วยบัญชีนักศึกษาทดสอบผ่าน (ทักทาย + ค้นหากิจกรรม) · `sudo bash /opt/aura-agent/deploy/install.sh` ใช้อัปเดตได้แล้ว (ลบสคริปต์ชั่วคราวใน home ออกแล้ว)
- **ยังไม่ได้ทำ:** ทดสอบกับบัญชีบุคลากรจริง (ยังไม่เคยเห็น `user_type` ของอาจารย์/เจ้าหน้าที่จริงว่าเป็นค่าอะไร โค้ดถือว่าทุกค่าที่ไม่ใช่ `student` คือบุคลากร)

### Deploy ขึ้น yru-ai ผ่าน GitHub · 2026-10-21
- **ตกลงแล้ว:** แบ่งงานตามแผนทีม — AURA เป็น chatbot service อย่างเดียว การตรวจสิทธิ์ผู้ใช้เป็นของ backend · backend ส่ง access token ของ YRU Passport มาใน `Authorization` (โหมด `passport` เดิม ไม่ต้องแก้โค้ด) AURA ใช้ token แค่ถาม `/oidc/userinfo` ว่าเป็นนักศึกษาคนไหน · repo `ai-center-hash/aura-agent-yru` ต้องเป็น **private** เพราะ HANDOFF มีรายละเอียดช่องโหว่ของ Activity API ที่ยังไม่แก้
- **ทำแล้ว:** `deploy/aura-agent.service` (user `aura`, `/opt/aura-agent`, port **8100**, restart อัตโนมัติ, ProtectSystem/ProtectHome) · `deploy/install.sh` (ติดตั้ง uv, สร้าง user, สร้าง deploy key ที่ `/etc/aura-agent/deploy_key`, clone/pull, `uv sync --frozen --no-dev`, restart, รอ `/v1/health`) · `.gitattributes` บังคับ LF ให้ไฟล์ .sh/.service · base URL ใน `docs/01-api-contract.md` · branch local เปลี่ยนเป็น `main`
- **สิ่งที่เจอบนเครื่อง:** Ubuntu 26.04 · ไม่มี uv · port 8000 = backend Laravel (container `aura-agent-backend`), 3000 open-webui, 8080 phpMyAdmin, 9000 portainer, 3306/5432 DB · Ollama เป็น systemd ฟังที่ 127.0.0.1:11434 · ufw ปิดอยู่
- **ผล:** ✅ รันอยู่ที่ **`http://10.20.41.54:8100`** (systemd `aura-agent`, commit `8e0792d`) · `/v1/health` → `{"status":"ok","ollama":"ok","activity_api":"ok"}` ทั้งจากในเครื่องและจากเครือข่าย · `/docs` เปิดได้ · ไม่ส่ง Authorization → 401 · token ปลอม → SSE `error` `TOKEN_EXPIRED` · repo เป็น private แล้ว · deploy key (อ่านอย่างเดียว) อยู่ที่ `/etc/aura-agent/deploy_key`
- **`SERVICE_KEY` ของ production** สุ่มใหม่ อยู่ใน `/opt/aura-agent/.env` บนเครื่อง (ดูด้วย `sudo grep SERVICE_KEY /opt/aura-agent/.env`) ส่งให้ทีม backend ทางช่องทางส่วนตัว · `.env` ไม่มี `PASSPORT_CLIENT_*` เพราะ API ไม่ใช้
- **เจอระหว่าง deploy:** sudo ของ Ubuntu 26.04 (sudo-rs) ไม่รองรับ `-E` → `install.sh` ส่งตัวแปรผ่าน `env` แทน (ฟังก์ชัน `as_app`) · systemd `EnvironmentFile` ไม่ตัด comment ท้ายบรรทัด จึงสร้าง `.env` บน server แบบไม่มี comment
- **อัปเดตครั้งต่อไป:** push ขึ้น `main` แล้วบนเครื่องรัน `sudo bash /opt/aura-agent/deploy/install.sh` · (Claude Code ในเครื่องนี้ push ไม่ได้ ระบบกันไว้ ต้อง push เอง)
- **ยังไม่ได้ทำ:** ยิง `/v1/chat` ด้วย token จริงจาก client ของ frontend (Q: Passport รับ token จากต่าง client ไหม) · จำกัด port 8100 ให้รับเฉพาะ backend (ufw ปิดอยู่ทั้งเครื่อง ต้องคุยกับผู้ดูแล) · log แบบ JSON · ลบ thread เก่า · เปลี่ยนรหัส SSH ของ `yruadmin`

### แก้บั๊กหมวดบังคับ/ป้ายประเภท + persona โครงสร้างจริง · 2026-10-21
- **ทำแล้ว:** `is_mandatory_category()` ใน `processing/models.py` ดูคำว่า "บังคับ" ทั้งชื่อหมวดและชื่อประเภท (`Gap`/`PassedItem.is_mandatory` ใช้ตัวนี้) · formatter ย่อเฉพาะประเภท "กิจกรรมบังคับ/เลือก" ส่วนประเภทอื่นต่อท้ายเต็ม เช่น "กิจกรรมบังคับ · กิจกรรมมหาวิทยาลัย" · persona `realistic_with_gaps` ใช้กติกากรอบจริง "ปีการศึกษา 2566" 14 หมวด กับนักศึกษา/ตัวเลขสมมติ (รหัส 406600123, id 900001) มีรอบจำกัดด้วยรายชื่อรหัส รอบไม่มีวันจัด หมวดเกณฑ์ 0 ชม. และหมวดเกณฑ์เทียบโอน 0/0 · `tests/unit/test_realistic_shape.py` 12 ข้อ · eval เพิ่ม `progress-11/12`, `search-11`, `recommend-09`, `history-07` (รวม 45 ข้อ) · หน้าแชทมี persona นี้ให้เลือก
- **ผล:** `pytest tests/unit` → **357 passed** · ruff ผ่าน · `run_evals.py --self-test` ผ่าน · `run_evals.py --model qwen3.6:35b-a3b` → **ผ่านทุกเกณฑ์** tool 98% · fact 98% · safety 100% · TTFT p50/p95 1743/3772 ms · รวม p50 5.8 วิ · ข้อใหม่ผ่านครบ 5/5 · `data_audit.py` ไม่พบตัวเลข/ชื่อที่กุขึ้น (รายงาน `tests/evals/reports/2026-10-21_qwen3.6_35b-a3b.md`)
- **ปัญหาที่รู้อยู่:** `recommend-02` ยังตกเหมือนเดิม (โมเดลไม่เรียก `recommend_activities` แล้วตอบด้วยชื่อหมวดที่เรียบเรียงเอง) · `recommend-09` ข้อความก่อนเรียก tool ("…รอสักครู่นะครับ") ต่อติดกับคำตอบโดยไม่ขึ้นบรรทัดใหม่ · ชื่อหมวดจริงบางชื่อมีช่องว่างซ้อน (แสดงตามที่ API ส่งมา)
- **ยังไม่รู้:** หมวดบังคับมีแค่หมวด 1 จริงไหม (Q9) — ตอนนี้ไม่เดาจากชื่อประเภท

### หน้าแชทล็อกอินด้วย YRU Passport จริง · 2026-10-21
- **ทำแล้ว:** `scripts/dev_chat.py` มี `/auth/login` → Passport → `/callback` (ตรวจ `state` ใช้ครั้งเดียว อายุ 10 นาที, แลก code ฝั่ง server, ปฏิเสธบัญชีที่ไม่ใช่นักศึกษา) → session ในหน่วยความจำ (8 ชม.) ผูกกับ cookie `HttpOnly` + `SameSite=Lax` · `/auth/logout` · `/api/me` · หน้าเว็บมีปุ่มเข้า/ออกจากระบบและบอกว่าคุยในฐานะใคร · `scripts/passport_oauth.py` เป็นตัวช่วย OAuth ที่ `passport_login.py` ใช้ร่วมด้วย · config `PASSPORT_CLIENT_ID` / `PASSPORT_CLIENT_SECRET` / `PASSPORT_REDIRECT_URI` อ่านจาก `.env`
- **เปลี่ยน:** หน้าแชทย้ายไป port 80 (`http://127.0.0.1/`) ให้ตรงกับ callback ที่ลงทะเบียน · ตัดโหมดวาง JWT เองออก (แทนด้วย login จริง) · โหมด persona ใช้วันอ้างอิงของ fixture เสมอ โหมด Passport ใช้วันจริงเสมอ (ไม่ต้องมี flag `--real-date` แล้ว)
- **ผล:** `pytest tests/unit` → **345 passed** (เพิ่ม `test_dev_chat.py` 17 ข้อ: redirect, state ผิด/ใช้ซ้ำ/หมดอายุ, บุคลากรเข้าไม่ได้, ผู้ใช้กดยกเลิก, แลก code ไม่สำเร็จ, cookie HttpOnly, secret/token ไม่หลุดไปเบราว์เซอร์, logout, session หมดอายุ) · เปิดจริงที่ port 80 แล้ว `/auth/login` พาไปหน้า login ของ Passport ได้ (Passport รับ client และ redirect_uri)
- **ยังไม่ได้ทดสอบเอง:** การกรอกรหัสในหน้า Passport — ต้องให้คนกดในเบราว์เซอร์
- **ข้อควรรู้:** session หายเมื่อปิดเซิร์ฟเวอร์ · ถ้าจะให้คนอื่นทดลองจากเครื่องอื่น ต้องลงทะเบียน callback ที่เป็น https บนโดเมนจริงกับ Passport ก่อน (127.0.0.1 ใช้ได้แค่เครื่องนี้)

### เปลี่ยนการยืนยันตัวตนเป็น YRU Passport · 2026-10-21
- **ทำไม:** ล็อกอินจริงผ่าน Passport (client 269) ด้วยบัญชี `user_type=student` แล้วยิง `/summary/me` ได้ **401** → Activity API ไม่รับ token ของ Passport (Q1) แต่ `/summary/user/{รหัส}` เป็น public (Q5)
- **ทำแล้ว:** `data/http.py` (แกน retry/log ที่ใช้ร่วมกัน), `data/passport.py` (`PassportClient.get_identity`, cache 5 นาที), `schemas/passport.py` (`PassportUser`), error ใหม่ `PassportUnavailable` / `NotAStudent` (`NOT_STUDENT`) / `NoActivityFrame`, `ActClient` 2 โหมด + `get_subject()` + `build_act_client()`, config `IDENTITY_MODE` / `PASSPORT_BASE_URL`, `Schedule.target_student_codes` + การกรองด้วยรายรหัส, `StudentProfile.from_passport` (id เป็น None ได้), `format_no_frame`, tool ทั้ง 3 จัดการกรณีไม่มีกรอบกิจกรรม, API/CLI ใช้ `get_subject()`, `scripts/passport_login.py`
- **ผล:** `pytest tests/unit` → **328 passed** (เพิ่ม 33: passport 9, act_client โหมด passport 11, filter 5, formatter 2, no-frame 6) · `ruff` ผ่าน · ยิงจริง: Passport → `summary/user/{รหัส}` → `no_frame` จัดการได้ · คุยผ่านหน้าแชทด้วย token จริง 4 คำถาม ตอบถูกทั้งหมด (ทักชื่อได้, บอกว่าไม่มีกรอบกิจกรรม, ค้นหาเจอ 0 รอบที่เปิดรับซึ่งตรงกับของจริง, อธิบายว่าดูประวัติไม่ได้)
- **เจอระหว่างทาง:** logger ของ httpx log URL เต็มที่มีรหัสนักศึกษา → ปิดที่ระดับ WARNING (มี test กันไว้) · `Schedule` schema ผ่านข้อมูลจริง 32 รอบ
- **ปัญหาที่รู้อยู่:**
  - ยังไม่เคยเห็น `StudentSummary` จริง เพราะบัญชีทดสอบไม่มีกรอบกิจกรรม (Q2) ต้องขอบัญชีที่มี
  - นักศึกษาที่ไม่มีกรอบกิจกรรม ไม่รู้ `student_status` (ถือเป็น normal) — ข้อมูลจริงไม่ได้ใช้ `target_student_status` เลย จึงยังไม่กระทบ
  - access token ของ Passport อายุ 1 ปี และไม่ได้ id_token กลับมา — ควรแจ้งทีม Passport
  - `dev.jwt` เก็บ token จริงอายุ 1 ปีไว้ (ผู้ใช้สั่งให้เก็บ) · client secret ถูกวางในแชท ควร rotate หลังพัฒนาเสร็จ
- **ต่อไปต้องรู้:** สลับโหมดได้ที่ `IDENTITY_MODE` ใน .env · เพิ่ม client ใหม่ให้สืบทอด `JsonApi` จะได้ retry/log แบบเดียวกัน · ทุกที่ที่ต้องการ "ผู้ใช้คนนี้คือใคร" ให้ใช้ `ActClient.get_subject()` ไม่ใช่ `get_my_summary()` (กรณีไม่มีกรอบกิจกรรมจะพัง)

### Phase 5 · Evals (โครงเสร็จ) · 2026-10-20
- **เสร็จแล้ว:** persona 3 ชุด + README, `dataset.yaml` 40 ข้อ, `personas.py`, `grading.py`, `fake_model.py`, `run_evals.py` และ `tests/unit/test_evals.py` (43 ข้อ)
- **ผล DoD:** `run_evals.py --self-test` → **40/40 ผ่าน** (โครง eval ใช้งานได้จริง) · `pytest tests/unit` → **286 passed** · `ruff check .` ผ่าน · วัดโมเดลจริง ⬜ · รายงานเทียบ 2 โมเดล ⬜
- **เปลี่ยนจากแผน:** เพิ่มโหมด `--self-test`, ตรึงวันอ้างอิง, `PersonaClient` กรองเหมือน API, เปอร์เซ็นไทล์แบบ interpolate — รายละเอียดใน [phase-5-evals.md](docs/phases/phase-5-evals.md)
- **ปัญหาที่รู้อยู่:**
  - **ยังไม่เคยวัดโมเดลจริง** เกณฑ์ TTFT/เวลาตอบจึงยังไม่ได้ยืนยัน และคำตอบจริงอาจไม่ตรง `must_contain` ที่เขียนไว้ (ถ้าไม่ตรงเพราะเกณฑ์เขียนแคบเกิน ให้แก้เกณฑ์ได้ แต่**ห้ามแก้ให้ผ่านโดยลดความถูกต้อง**)
  - โมเดลปลอมใน `--self-test` ใช้ keyword ง่ายๆ ถ้าเพิ่มข้อใหม่ในภาษาที่ต่างไป อาจต้องเพิ่ม keyword ใน `fake_model.py` (ไม่กระทบ eval จริง)
  - ยังไม่มีการวัดความถูกต้องแบบให้ LLM เป็นผู้ตัดสิน (LLM-as-judge) ใช้แค่ `must_contain` ซึ่งตรวจข้อเท็จจริงได้ แต่ไม่ตรวจความลื่นไหลของภาษา
- **Phase ถัดไปต้องรู้:**
  - เวลาจะเทียบโมเดล: `--model <ชื่อ>` แล้วรายงานจะแยกไฟล์ตามวันและชื่อโมเดลให้เอง
  - ถ้าแก้ `prompts/system_prompt.th.md` หรือ docstring ของ tool **ต้องรัน eval ซ้ำ** (กฎใน CLAUDE.md) และข้อที่เคยผ่านต้องไม่กลับมาไม่ผ่าน
  - `tests/evals/reports/` ไม่ commit (มีคำตอบของโมเดลซึ่งอ้างอิง persona จำลอง แต่กันไว้เป็นนิสัย)

### Phase 4 · API Layer (โค้ดเสร็จ) · 2026-10-20
- **เสร็จแล้ว:** `api/main.py` (lifespan + `create_app`), `api/deps.py`, `api/schemas.py`, `api/sse.py`, `api/routes/chat.py`, `api/routes/health.py` + `agent/errors.py` (`LLMUnavailable`), `agent/stream.py` และ test 4 ไฟล์ (chat 24, health 10, lifespan 2, sse 18)
- **ผล DoD:** `python -m uv run pytest tests/unit -q` → **243 passed** · coverage **98%** (`api/` 100%) · `ruff check .` ผ่าน
  · รัน uvicorn จริงโดยชี้ upstream ไป port ที่ไม่มีอะไรฟัง: `/v1/health` → `{"status":"degraded","ollama":"down","activity_api":"down"}` · service key ผิด → 401 · `/v1/chat` → `event: error UPSTREAM_UNAVAILABLE` (HTTP 200 ตาม contract)
  · curl ด้วย JWT + Ollama จริง ⬜
- **เปลี่ยนจากแผน:** `LLMUnavailable` อยู่ชั้น agent, `create_app(graph=...)` สำหรับ test, `ThinkFilter` รองรับ tag ข้าม chunk, health มี `model_missing`/`unknown` — รายละเอียดใน [phase-4-api.md](docs/phases/phase-4-api.md)
- **ปัญหาที่รู้อยู่:**
  - ยังไม่เคยเห็น token ไหลจากโมเดลจริง (ทดสอบด้วย `FakeChat` ที่ stream เองใน test)
  - `GET /v1/health` เปิดให้เรียกได้โดยไม่ต้องมี service key (ไว้ให้ monitoring) ถ้าไม่ต้องการ ให้เพิ่ม `ServiceKey` เข้าไปใน route
  - provider `openai_compatible` ยังไม่มี health check (คืน `"unknown"`)
  - ยังไม่มี rate limit และยังไม่จำกัด CORS (ตอนนี้มีแต่ backend เรียก ถ้าเปิดให้ frontend เรียกตรงต้องเพิ่ม)
- **Phase ถัดไปต้องรู้:**
  - รัน: `python -m uv run uvicorn aura_agent.api.main:app --host 0.0.0.0 --port 8000`
  - บน Git Bash ให้ส่ง body จากไฟล์ (`--data-binary @body.json`) ข้อความไทยใน `-d` จะเพี้ยนจนได้ HTTP 400
  - eval เรียก graph ตรงๆ ได้เลย (เร็วกว่าและไม่ต้องยิง HTTP): `build_graph(InMemorySaver(serde=state_serializer()))` + `set_llm()` / `set_act_client()`
  - ถ้าอยากวัดเวลาแบบที่ผู้ใช้เจอจริง ใช้ `latency_ms` ใน event `done` ได้เลย

### Phase 3 · Tools + Agent (โค้ดเสร็จ) · 2026-10-20
- **เสร็จแล้ว:** tool 4 ตัว (`progress.py`, `schedules.py`, `recommend.py`, `registrations.py` + `context.py`), `TOOLS`/`TOOL_STATUS`, agent (`state.py`, `llm.py`, `prompts.py`, `nodes.py`, `graph.py`, `checkpointer.py`), `clock.py`, `cli.py` และ test 5 ไฟล์ (tools 26, prompts/llm 9, graph 15, cli 9, clock 3)
- **ผล DoD:** `python -m uv run pytest tests/unit -q` → **189 passed** · coverage ของแพ็กเกจ **97%** (`tools/` 100%, `agent/` 99%) · `ruff check .` ผ่าน · ทดสอบ CLI ด้วย JWT จริง ⬜ (ต้องมี tunnel + token)
- **เปลี่ยนจากแผน:** เพิ่ม `clock.py`, `tools/context.py`, `agent/checkpointer.py`, `set_act_client()`/`set_llm()` และสร้าง checkpointer เองเพื่อใส่ serializer — รายละเอียดอยู่ในหัวข้อ "สิ่งที่ทำจริง" ของ [phase-3-agent.md](docs/phases/phase-3-agent.md)
- **ปัญหาที่รู้อยู่:**
  - ยังไม่เคยคุยกับโมเดลจริงเลย พฤติกรรมการเลือก tool, ความยาวคำตอบ และการปฏิเสธ (ขอข้อมูลคนอื่น / ขอให้ลงทะเบียนแทน) ต้องวัดจริงใน CLI และ eval ของ Phase 5
  - `prompts/system_prompt.th.md` อยู่นอกแพ็กเกจ (`PROMPT_PATH` ชี้ขึ้นไป 3 ชั้นจาก `agent/prompts.py`) ถ้าวันหลัง build เป็น wheel ไปติดตั้งที่อื่น ต้องย้ายไฟล์เข้าแพ็กเกจหรือเพิ่ม setting ชี้ path
  - `cli.py` ยังไม่มี test ส่วน REPL loop (coverage 71%) ส่วนที่เหลือคือ loop รับ input
- **Phase ถัดไปต้องรู้:**
  - เรียก graph: `async with sqlite_checkpointer() as cp: graph = build_graph(cp)` แล้ว `graph.astream(..., run_config(user_id=..., thread_id=..., jwt=...), stream_mode=["updates","messages"])`
  - **ต้องได้ `user_id` ก่อนเรียก graph** (เรียก `get_my_summary(jwt)` ครั้งหนึ่ง — ถูก cache 120 วิอยู่แล้ว) เพื่อสร้าง `thread_id` ที่เก็บจริง `f"{user_id}:{thread_id}"` ตาม `thread_key()`
  - `event: status` ของ SSE เอาจาก `TOOL_STATUS[tool_name]` โดยดู `tool_calls` ของ AIMessage ที่ node `agent` ส่งออกมา (ดู `_print_tool_status` ใน `cli.py`)
  - error ที่จะขึ้นมาถึงชั้น API คือ `TokenExpired` / `UpstreamUnavailable` / `UpstreamRejected` / `UpstreamSchemaError` ใช้ `error.code` กับ `error.message_th` ได้เลย ส่วน error จาก Ollama ต้อง map เป็น `LLM_UNAVAILABLE` เอง
  - lifespan ของ FastAPI ควรสร้าง `ActClient` เองแล้วใส่ด้วย `set_act_client()` และปิดด้วย `close_act_client()`

### Phase 2 · Processing · 2026-10-20
- **เสร็จแล้ว:** `models.py`, `gap_analyzer.py`, `schedule_filter.py`, `recommender.py`, `registration_mapper.py`, `formatter.py` + test 5 ไฟล์ (gaps 9, filter 16, recommend 11, registrations 15, formatter 29)
- **ผล DoD:** `python -m uv run pytest tests/unit -q --cov=aura_agent.processing` → **127 passed · coverage 100%** · `ruff check .` ผ่าน
- **เปลี่ยนจากแผน:** `filter_eligible` คืน `list[EligibleSchedule]` (ห่อ `Schedule` + ธง `eligibility_uncertain`) แทน `list[Schedule]`, ไม่ย่อชื่อหมวด, เพิ่ม `tzdata`/`pytest-cov` — รายละเอียดทั้งหมดอยู่ในหัวข้อ "สิ่งที่ทำจริง" ของ [phase-2-processing.md](docs/phases/phase-2-processing.md)
- **ปัญหาที่รู้อยู่:**
  - เงื่อนไขรุ่นปียังเทียบไม่ได้ (Q4) ทุกรอบที่จำกัดรุ่นจะติดป้าย "ไม่แน่ใจเรื่องสิทธิ์สมัคร" ไปก่อน — ถ้า Q4 ตอบแล้วให้แก้ `_matches_year_prefix` + `YEAR_PREFIX_RULE_KNOWN` ใน `schedule_filter.py`
  - ถ้า Q3 ยืนยันว่า endpoint D กรองสิทธิ์ให้แล้ว `filter_eligible` จะเหลือหน้าที่แค่ตัด `is_full`/หมดเวลา (ตามที่แผน Phase 2 เขียนไว้)
  - ยังไม่เคยทดสอบกับข้อมูลจริง ตัวเลขทั้งหมดอ้างจาก fixture
- **Phase ถัดไปต้องรู้:**
  - ลำดับการต่อใน tool: `get_my_summary` → `analyze_gaps` → `format_progress` (ใช้ใน `load_student`) · `get_schedules` → `filter_eligible` → `format_schedules` · `recommend(report.gaps, eligible)` → `format_recommendations` · `get_registrations` → `map_registrations` → `format_registrations`
  - **`today` ต้องสร้างในชั้น agent** เช่น `datetime.now(ZoneInfo(settings.timezone)).date()` แล้วส่งเข้า `filter_eligible` เพราะ processing ห้ามเรียก `datetime.now()`
  - `StudentProfile.from_user(summary.user)` คือค่าที่ต้องเก็บใน `state["student"]` (`.id` คือ user_id ที่เชื่อถือได้)
  - `RegistrationFilter` = `Literal["registered","checked_in","completed","cancelled"]` ใช้เป็น type ของ parameter ใน tool `get_my_registrations` ได้เลย
  - formatter ตัดรายการที่ 10 เองแล้ว (`MAX_ITEMS`) ส่วน prompt สั่งให้บอทแสดงไม่เกิน 5 รายการ — ไม่ต้องตัดซ้ำในชั้น tool
  - ป้ายที่ formatter ใส่คือข้อความ `ไม่แน่ใจเรื่องสิทธิ์สมัคร` ตรงกับกฎข้อ 8 ใน `prompts/system_prompt.th.md` แล้ว

### Phase 1 · Data Layer (โค้ดเสร็จ) · 2026-10-20
- **เสร็จแล้ว:** `data/errors.py` (4 exception พร้อม `code`/`message_th`), `data/cache.py` (`MemoryCache` TTL ต่อ key, `NullCache`, `make_cache_key`), schema 3 ชุด + `base.py`, `ActClient` (summary/schedules/registrations/ping + retry + cache), fixture 3 ไฟล์ + README, `scripts/check_act_api.py`
- **ผล DoD:** `pytest tests/unit` **47/47 ผ่าน** (test_act_client 31, test_cache 9, test_config 7 — นับรวม parametrize) · `ruff check .` ผ่าน · `ruff format src tests scripts` แล้ว · ทดสอบกับ API จริง ⬜ (ต้องใช้ JWT ของผู้พัฒนา) · Q3 ⬜
- **เปลี่ยนจากแผน:** ดูตาราง "สิ่งที่ทำจริง" ใน [phase-1-data-layer.md](docs/phases/phase-1-data-layer.md) สรุปคือเพิ่ม `UpstreamRejected`, `schemas/base.py`, `NullCache`, `get_act_client()`, test_cache.py และ script ทดสอบ API จริง
- **ปัญหาที่รู้อยู่:**
  - ยังไม่เคยยิง API จริงเลย schema ทั้งหมดมาจาก**ตัวอย่างในคู่มือ** ถ้าของจริงต่าง (เช่น `/summary/me` ครอบ `data` อีกชั้น) ต้องแก้ `_unwrap` กับ schema
  - คู่มือไม่มีตัวอย่าง response ของ `/summary/me` มีแต่ `/summary/user/{id}` (Q2)
  - `ping()` ใช้ `per_page=1` ซึ่งคู่มือไม่ได้ระบุไว้ ถ้า API ไม่รองรับก็ยังทำงานได้ (ได้ 200 หรือ 4xx ก็ถือว่าเซิร์ฟเวอร์ตอบ)
- **Phase ถัดไปต้องรู้:**
  - ใช้แค่ schema + fixture ไม่ต้องเรียก HTTP — `from aura_agent.data import ...` หรือ `from aura_agent.data.schemas import ...`
  - fixture ใช้วันอ้างอิง **2026-10-20** และตั้งใจให้ขาดหมวด 2 (จิตอาสา 2 กิจกรรม/8 ชม.) กับหมวด 5 (กีฬา 2 กิจกรรม/6 ชม.) ส่วนหมวด 7 ชั่วโมงเกินเกณฑ์ไว้ทดสอบว่า `missing_hours` ไม่ติดลบ
  - `Schedule.duration_hours` อาจเป็น `None` และ `category_id` อาจเป็น `None` ใน `filter_eligible`/`recommend` ต้องเผื่อไว้
  - `Registration.attendance_minutes` เป็น `None` ได้เมื่อเช็คอินแล้วแต่ยังไม่เช็คเอาท์ (status 4)
  - `StudentProfile` ที่ Phase 2–3 ใช้ ยังไม่มี ให้สร้างใน `processing/models.py` จาก `StudentSummary.user`

### Phase 0 · Setup (บางส่วน) · 2026-10-20
- **เสร็จแล้ว:** `uv init --package` (Python 3.12) + `git init` (ยังไม่มี commit), เพิ่ม dependencies ตามแผน, โครงโฟลเดอร์ 5 ชั้น + `tests/`, `config.py`, `.env.example`, `.gitignore`, สร้าง `.env` บนเครื่องพร้อม `SERVICE_KEY` แบบสุ่ม
- **ผล DoD:** `get_settings().llm_model` → `qwen3.6:35b-a3b` ✅ · `ruff check` ผ่าน ✅ · `pytest` 7/7 ✅ · Ollama tunnel ⬜ · Q1 ⬜
- **เปลี่ยนจากแผน:** ใช้ `get_settings()` + `lru_cache` แทนการสร้าง `settings = Settings()` ตอน import (test ส่งค่าเองได้), `service_key` เป็น `SecretStr` ยาว ≥ 16 ตัว, ฟิลด์ที่มีตัวเลือกจำกัดเป็น `Literal`, เพิ่ม `llm_base_url` สำหรับ vLLM
- **ปัญหาที่รู้อยู่:** `ruff format` จัดรูปแบบ code block ใน `docs/*.md` ด้วย (เปลี่ยนแค่ whitespace ไม่เสียหาย)
- **Phase ถัดไปต้องรู้:** `.gitignore` ignore เฉพาะ `/data/` ที่ root เพราะ `src/aura_agent/data/` เป็นโค้ด อย่าเปลี่ยนเป็น `data/`

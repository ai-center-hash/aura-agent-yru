# 00 · Architecture

## ภาพรวม

```
┌──────────┐    ┌──────────────┐    ┌───────────────────────────────────────────────┐
│ Frontend │───►│ Backend เดิม  │───►│ AURA-AGENT                                    │
│ (แชท)    │◄───│ (ตรวจ JWT)    │◄───│                                               │
└──────────┘SSE └──────────────┘SSE │ ① API         รับคำถาม / stream คำตอบ           │
                                    │ ② Agent       LLM ตัดสินใจว่าต้องใช้ข้อมูลอะไร ─────┼──► Ollama 10.20.41.54
                                    │ ③ Tools       เครื่องมือที่ LLM เรียกได้ (4 ตัว)     │    qwen3.6:35b-a3b
                                    │ ④ Processing  ข้อมูลดิบ → ข้อเท็จจริงสั้นๆ          │
                                    │ ⑤ Data        ดึง Activity API + cache       ───┼──► api831.yru.ac.th
                                    └───────────────────────────────────────────────┘
```

**กฎการพึ่งพา:** ชั้นบนเรียกชั้นล่างได้อย่างเดียว ชั้นล่างห้าม import ชั้นบน
`④ Processing` เป็น pure function ไม่มี I/O จึงทดสอบได้โดยไม่ต้องต่อ API

## หน้าที่ของแต่ละชั้น

| ชั้น | โฟลเดอร์ | หน้าที่ | ห้ามทำ |
|---|---|---|---|
| ① API | `api/` | รับ request, ตรวจ service key, stream SSE, แปลง error เป็นข้อความไทย | มี business logic |
| ② Agent | `agent/` | LangGraph graph, state, system prompt, ประวัติแชท | เรียก HTTP เอง |
| ③ Tools | `tools/` | ห่อ data + processing ให้ LLM เรียก และคืนข้อความสั้น | รับรหัสนักศึกษาเป็น parameter |
| ④ Processing | `processing/` | คำนวณหมวดที่ขาด, กรอง, แนะนำ, จัดรูปแบบ | I/O ทุกชนิด |
| ⑤ Data | `data/` | HTTP client, Pydantic schema, cache, แปลง error | ตีความข้อมูล |

## Flow: "ผมขาดหมวดไหน แนะนำกิจกรรมหน่อย"

```
1. Frontend ──(คำถาม + JWT)──► Backend ──(ตรวจ JWT)──► POST /v1/chat
2. load_student : data.get_my_summary(jwt)  [Passport userinfo → รหัส → summary/user/{รหัส}]
                  → processing.analyze_gaps() → เก็บใน state
3. agent        : Qwen อ่าน system prompt (มีหมวดที่ขาดอยู่แล้ว) → เรียก recommend_activities()
4. tool         : data.get_schedules() → filter_eligible() → recommend() → ข้อความสั้น
5. agent        : Qwen เรียบเรียงคำตอบภาษาไทย
6. API          : stream token ทีละชิ้น → Backend → Frontend
```

## Graph (LangGraph)

```
START → load_student → agent ⇄ tools → END
```

- `load_student` ทำงานเฉพาะเมื่อ state ยังไม่มีข้อมูลนักศึกษา หรือข้อมูลเก่าเกิน 2 นาที
- `agent` → `tools` เมื่อ LLM ขอเรียก tool และจำกัดไม่เกิน **4 รอบต่อคำถาม** กันวนไม่จบ

## หลักความปลอดภัย (ห้ามละเมิด)

1. **ตัวตนมาจาก token เท่านั้น** ไม่ใช่จากข้อความที่ผู้ใช้พิมพ์ (ดู "การยืนยันตัวตน" ด้านล่าง)
2. **JWT ไม่เก็บใน state** ส่งผ่าน `RunnableConfig["configurable"]["jwt"]` เพราะ state ถูกบันทึกลง SQLite
3. **thread ผูกกับผู้ใช้** key ที่เก็บจริงคือ `f"{subject}:{thread_id}"` (`subject` = `passport:{sub}`) คนอื่นจึงอ่านแชทของเราไม่ได้แม้รู้ thread_id
4. **อ่านอย่างเดียว** ไม่มี tool ที่เขียนข้อมูล ถ้าวันหลังเพิ่ม ต้องใช้ `interrupt()` ให้ผู้ใช้ยืนยันก่อน
5. **ไม่ log ข้อมูลส่วนบุคคล** log ได้แค่ user_id แบบ hash, ชื่อ tool, เวลาที่ใช้ และ error code

## การยืนยันตัวตน (เปลี่ยนเมื่อ 2026-10-21)

Activity API **ไม่รับ** access token ของ YRU Passport (`/summary/me` ตอบ 401) แต่เส้น
`/summary/user/{รหัสนักศึกษา}` เป็น public จึงยืนยันตัวตนกับ Passport เองแล้วใช้เส้นนั้น

```
token ของผู้ใช้ ──► Passport /oidc/userinfo ──► sub, username(รหัสนักศึกษา), user_type, คณะ
                     (401 = token หมดอายุ · user_type≠student = NOT_STUDENT)
                                  │
                                  ▼ รหัสนักศึกษา (มาจาก token ไม่ใช่จากแชท)
                    Activity API /summary/user/{รหัส}   ← ไม่แนบ token
                                  │
              ┌───────────────────┴────────────────────┐
              ▼                                         ▼
    มีกรอบกิจกรรม → StudentSummary            no_frame → NoActivityFrame
    (user.id ใช้ค้นประวัติลงทะเบียน)          คุยต่อได้: รู้ตัวตนจาก Passport, ค้นหากิจกรรมได้
                                              แต่ดูความคืบหน้าและประวัติไม่ได้
```

| โหมด (`IDENTITY_MODE`) | ตัวตนมาจาก | ส่ง token ให้ Activity API | ใช้เมื่อ |
|---|---|---|---|
| `passport` (ค่าเริ่มต้น) | Passport `/oidc/userinfo` | **ไม่ส่ง** (เส้น public) | ตอนนี้ |
| `activity_me` | Activity API `/summary/me` | ส่ง | เมื่อเจ้าของ API รับ token ได้ (Q8) |

กฎที่ต้องรักษาไม่ว่าจะโหมดไหน: token ของ Passport ใช้กับ Passport เท่านั้น ·
log ใช้ label แบบ template ไม่มีรหัสนักศึกษา และ logger ของ httpx ถูกตั้งไว้ที่ WARNING

## สิ่งที่เปลี่ยนได้ผ่าน `.env` (เตรียมไว้สำหรับ Phase 2 server ใหม่)

| ส่วน | Phase 1 | Phase 2 |
|---|---|---|
| LLM | `LLM_PROVIDER=ollama` | `openai_compatible` (vLLM) |
| ประวัติแชท | `CHECKPOINTER=sqlite` | `postgres` |
| Cache | `CACHE=memory` | `redis` |

# 02 · Activity API Reference (เฉพาะส่วนที่ AURA-AGENT ใช้)

ที่มา: https://top-ita.github.io/act-aihub-api/
Base URL: `https://api831.yru.ac.th/act/api` (ใช้ทั้ง dev และ prod ตามคู่มือ **เป็นข้อมูลจริง**)

## Endpoint ที่ใช้

| # | Endpoint | ใช้ใน | Cache TTL |
|---|---|---|---|
| A | `GET /v1/report/summary/user/{รหัสนักศึกษา}` (public · โหมด `passport`) | `load_student`, `get_my_progress` | 120s |
| A′ | `GET /v1/report/summary/me` (โหมด `activity_me` · **ตอนนี้ใช้ไม่ได้** Passport token ได้ 401) | — | 120s |
| B | `GET /v1/act/activity-schedules` | `search_activities`, `recommend_activities` | 120s |
| C | `GET /v1/act/act-registrations?user_id={id}` | `get_my_registrations` | 60s |
| D | `GET /v1/act/activities` (Student Mode) | ⚠️ ต้องเช็คใน Phase 1 ว่าใช้กรองสิทธิ์สมัครได้ไหม | 120s |

**ไม่ใช้:** `/v1/auth/users` (ข้อมูลนักศึกษาทุกคน), `/v1/act/activities?with_trashed=true` (โหมดแอดมิน)

**ทำไมใช้ `/summary/user/{id}` ได้โดยไม่เกิด IDOR:** รหัสที่ส่งไปมาจาก Passport userinfo ของ token ผู้ใช้เท่านั้น
ไม่มี tool ไหนรับรหัสจากข้อความในแชท (กฎใน CLAUDE.md) · ส่วนการที่ API เปิดเส้นนี้เป็น public เป็นปัญหาฝั่ง API ที่แจ้งเจ้าของแล้ว

**รูปร่าง response จริงของ A** (ยิงจริง 2026-10-21): `{"success", "message", "no_frame", "data"}`
ถ้ายังไม่มีกรอบกิจกรรม → `no_frame: true`, `data: null`, `message: "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้"`

**การจำกัดสิทธิ์จริงใน B:** ใช้ `target_student_codes` (รายรหัสนักศึกษา) 30/32 รอบ — schema อ่านฟิลด์นี้แล้ว
และ `filter_eligible` คัดเฉพาะรอบที่รหัสของผู้ใช้อยู่ในรายชื่อ

ทุก request ส่ง `Authorization: Bearer <jwt>` และ `Accept: application/json`

## A · `summary/me`: ความคืบหน้าของนักศึกษา

ฟิลด์ที่ใช้:
```
data.user        → id, name, student_id, faculty, major, level, student_status (normal|transfer)
data.frame       → id, title, start_date, end_date
data.summary     → total_activities, total_hours, overall_status
data.categories[] → category_id, category_name, type_name
  .frame_items[] → requirement{normal_activity_min, normal_hour_min, transfer_activity_min, transfer_hour_min},
                   count, total_hours, is_passed, activities[]{title, attendance_hours, checkin_at}
```
- `data.user.id` คือ `user_id` **แหล่งเดียว** ที่ใช้กับ endpoint C
- เลือกเกณฑ์ตาม `student_status`: `normal` ใช้ `normal_*`, `transfer` ใช้ `transfer_*`

## B · `activity-schedules`: รอบกิจกรรม

Query ที่ใช้เสมอ: `paginate=false&is_published=true&sort_by=registration_start_date&sort_order=asc`
และเพิ่มตามการใช้งาน: `registration_phase=open|upcoming`, `activity_date_from`, `activity_date_to`, `search`

ฟิลด์ที่ใช้:
```
id, activity_id, category_id, category_label, type_label,
registration_start_date, registration_end_date, activity_start_date, activity_end_date,
duration_hours, max_participants, current_participants, available_slots,
is_registration_open, is_full, is_restricted,
target_student_year_prefix[], target_faculties[], target_student_status,
activity.title, activity.organizer_name
```

## C · `act-registrations`: ประวัติลงทะเบียน

Query: `paginate=false&user_id={id}&sort_by=registered_at&sort_order=desc`

ฟิลด์ที่ใช้: `activity.title, schedule.activity_start_date, status, registered_at, checkin_at, checkout_at, attendance_minutes`

| status | ความหมาย |
|---|---|
| 1 | ลงทะเบียนแล้ว |
| 4 | เช็คอินแล้ว |
| 5 | เข้าร่วมสมบูรณ์ |
| 6 | ยกเลิก |

## บันทึกจากคู่มือ (อ่านฉบับเต็มเมื่อ 2026-10-20)

สิ่งที่คู่มือระบุไว้และมีผลกับการออกแบบ (ยังต้องยืนยันกับ API จริงอีกครั้ง):

- **endpoint C และ `/report/summary/user/{id}` เป็น public route** (ไม่ต้องส่ง token) ส่วน `/summary/me` ต้องใช้ token
  → ยิ่งต้องยึดกฎ "`user_id` มาจาก `summary/me` เท่านั้น" เพราะถ้าหลุดให้ LLM รับ `user_id` ได้ จะดูข้อมูลคนอื่นได้ทันที
- `summary` ฝั่ง server **cache ไว้ 2 นาที** ต่อ `(user_id, frame_id)` เท่ากับ TTL ที่เราตั้งไว้ (120 วิ)
- `summary` นับเฉพาะการลงทะเบียนที่ `status ∈ (4, 5)` และมี `checkin_at` และไม่รวมกิจกรรมที่ไม่อนุมัติ
- `summary` รับ query `fields=user,summary` เพื่อลดขนาด response และ `frame_id` เพื่อระบุกรอบเอง (ตอนนี้ยังไม่ใช้ทั้งคู่)
- `activity-schedules` ส่ง `duration_minutes` มาคู่กับ `duration_hours`, มี `is_expired` และ `status` เป็น string (`active`/`inactive`/`closed`)
  ส่วน `registration_phase` รองรับ `closed` ด้วย (เราใช้แค่ `open`/`upcoming`)
- รอบที่ไม่จำกัดกลุ่มเป้าหมายส่ง `target_*` มาเป็น `null` และรหัสรุ่นอาจมาเป็นตัวเลข schema จึงแปลงเป็น `list[str]` ให้
- **Q4:** ตัวอย่างใน `summary` มี `activities[].joined_year` (เช่น `"65"`) แยกจาก `user.student_id` (เช่น `"406510024"`)
  แปลว่า `target_student_year_prefix` น่าจะเทียบกับ**ปีที่เข้าศึกษา** ไม่ใช่สองตัวแรกของรหัสนักศึกษา — ยังต้องถามเจ้าของ API ให้ชัด
- **Q3:** คู่มือระบุว่า endpoint D แบบ Student Mode (ไม่ส่ง `with_trashed`) คืนผลเป็น "1 รายการ = 1 รอบ"
  และ**กรองตามกลุ่มเป้าหมาย (ชั้นปี, คณะ, หลักสูตร) ของนักศึกษา** ให้แล้ว เหลือยืนยันว่าใช้ตัวตนจาก token ที่ส่งไปจริงไหม

## เรื่องที่ยังไม่ชัด (ต้องเช็คใน Phase 0–1)

| # | คำถาม | ผลกระทบ |
|---|---|---|
| Q1 | JWT ของ YRU Passport ใช้กับ endpoint A ได้ไหม | **blocker** ถ้าไม่ได้ ต้องคุยเรื่องแลก token กับเจ้าของ API |
| Q2 | response ของ `/summary/me` หน้าตาเหมือน `/summary/user/{id}` ไหม | ต้องแก้ schema ถ้าต่างกัน |
| Q3 | endpoint D (Student Mode) กรองตามสิทธิ์ของผู้ที่ login ได้ไหม | ถ้าได้ ใช้ D แทนการกรองเอง (แม่นกว่า) |
| Q4 | `target_student_year_prefix` เทียบกับฟิลด์ไหนของนักศึกษา (รหัสนักศึกษาหรือปีที่เข้า) | ใช้ในการกรองเองถ้า Q3 ใช้ไม่ได้ |
| Q5 | endpoint C กรองด้วย `user_id` แล้วต้องใช้ token ไหม หรือเป็น public | ถ้าเป็น public ต้องระวังเป็นพิเศษว่า user_id มาจาก A เท่านั้น |

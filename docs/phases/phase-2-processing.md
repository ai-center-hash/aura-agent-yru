# Phase 2 · Processing

**เป้าหมาย:** แปลงข้อมูลดิบเป็นข้อเท็จจริงสั้นๆ ที่ LLM เอาไปตอบได้เลย **LLM ไม่ต้องคำนวณเลขเอง**

ทุกฟังก์ชันเป็น **pure function** (ไม่มี I/O ไม่เรียก `datetime.now()` เอง ให้รับ `today` เป็น argument)

## Files

```
src/aura_agent/processing/
├── models.py              # dataclass ของผลลัพธ์ (Gap, ProgressReport, ...)
├── gap_analyzer.py
├── schedule_filter.py
├── recommender.py
├── registration_mapper.py
└── formatter.py           # วันที่ไทย / ข้อความสั้นสำหรับ LLM
tests/unit/test_processing_*.py
```

## 1. `gap_analyzer.py`

```python
def analyze_gaps(summary: StudentSummary) -> ProgressReport: ...
```

- เลือกเกณฑ์จาก `student_status` (`normal` → `normal_*`, `transfer` → `transfer_*`)
- ต่อ frame_item: `missing_activities = max(0, activity_min - count)` และ `missing_hours = max(0, hour_min - total_hours)`
- ผลลัพธ์: `ProgressReport(frame_title, overall_status, passed_items, gaps: list[Gap], total_hours)`
- `Gap(category_id, category_name, type_name, missing_activities, missing_hours)`

## 2. `schedule_filter.py`

```python
def filter_eligible(
    schedules: list[Schedule], student: StudentProfile, today: date
) -> list[Schedule]: ...
```

ตัดทิ้งเมื่อ:
- `is_full` หรือหมดเวลารับสมัครไปแล้ว (`registration_end_date < today`)
- `is_restricted` และไม่ตรงเงื่อนไข: คณะไม่อยู่ใน `target_faculties`, `target_student_status` ไม่ตรง, `target_student_year_prefix` ไม่ตรง (**วิธีเทียบรอผล Q4** ถ้ายังไม่รู้ ให้ปล่อยผ่านไว้ก่อน แล้วติดป้าย `eligibility_uncertain=True`)

> ถ้า Q3 ยืนยันว่า Student Mode กรองให้แล้ว ให้ใช้ผลจาก API เป็นหลัก ฟังก์ชันนี้เหลือแค่ตัด is_full/หมดเวลา

## 3. `recommender.py`

```python
def recommend(
    gaps: list[Gap], eligible: list[Schedule], limit: int = 5
) -> list[Recommendation]: ...
```

- จับคู่ `schedule.category_id` กับ `gap.category_id`
- เรียงตาม: กิจกรรมบังคับก่อน → วันจัดกิจกรรมใกล้ที่สุด → ชั่วโมงที่ช่วยปิดช่องว่างได้มากที่สุด
- `Recommendation(schedule, gap, covers_hours)`
- ถ้าไม่มีหมวดที่ขาด คืน `[]` (agent จะแสดงความยินดีว่าครบแล้ว)

## 4. `registration_mapper.py`

แปลง status เป็นข้อความไทย (1 ลงทะเบียนแล้ว / 4 เช็คอินแล้ว / 5 เข้าร่วมสมบูรณ์ / 6 ยกเลิก) และ `attendance_minutes` เป็นชั่วโมง

## 5. `formatter.py`

ผลลัพธ์ทั้งหมดถูกแปลงเป็น**ข้อความสั้น**ก่อนส่งให้ LLM เพราะสั้นกว่า JSON และ Qwen อ่านแม่นกว่า

```
[ความคืบหน้า] กรอบ: กรอบกิจกรรมพัฒนานักศึกษา 2565-2568 | สถานะรวม: ยังไม่ผ่าน | รวม 36.5 ชม.
[ยังขาด]
- กิจกรรมเสริมสร้างคุณธรรมฯ (บังคับ): ขาด 1 กิจกรรม / 3 ชม.
- กิจกรรมจิตอาสา (เลือก): ขาด 2 ชม.
```

```
[กิจกรรมที่สมัครได้] 2 รายการ
1. ปฐมนิเทศนักศึกษาใหม่ | หมวด: คุณธรรมฯ | 20 มิ.ย. 2569 09:00-16:00 | 6 ชม. | ว่าง 15/200 | ปิดรับสมัคร 15 มิ.ย. 2569
```

- วันที่เป็นแบบไทย ปี พ.ศ. timezone `Asia/Bangkok`
- ตัดรายการสูงสุด 10 รายการ ถ้ามีมากกว่าให้บอก `(แสดง 10 จาก 37 รายการ)`

## Tests (ใช้ fixture จาก Phase 1)

| Test | กรณี |
|---|---|
| gap normal vs transfer | ได้เกณฑ์ต่างกัน |
| ครบทุกหมวด | gaps ว่าง |
| ชั่วโมงเกินเกณฑ์ | missing_hours = 0 ไม่ติดลบ |
| filter | ตัดรอบที่เต็ม หมดเวลา และต่างคณะ |
| recommend | เรียงลำดับถูก ตัดตาม limit |
| formatter | วันที่ 2026-06-20 → `20 มิ.ย. 2569` |

## สิ่งที่ทำจริง (2026-10-20)

| ไฟล์ | ของจริง |
|---|---|
| `models.py` | `StudentProfile` (+ `from_user()`, `is_transfer`), `Gap`, `PassedItem`, `ProgressReport`, `EligibleSchedule`, `Recommendation`, `RegistrationView` — frozen dataclass ทั้งหมด |
| `gap_analyzer.py` | `analyze_gaps(summary) -> ProgressReport` |
| `schedule_filter.py` | `filter_eligible(schedules, student, today) -> list[EligibleSchedule]` |
| `recommender.py` | `recommend(gaps, eligible, limit=5) -> list[Recommendation]` |
| `registration_mapper.py` | `map_registrations(registrations, status=None)`, `status_label()`, `attendance_hours()` |
| `formatter.py` | `format_progress/format_schedules/format_recommendations/format_registrations` + `thai_date/thai_datetime/thai_period/format_hours` |

เปลี่ยนจากแผน:

- **`filter_eligible` คืน `list[EligibleSchedule]` ไม่ใช่ `list[Schedule]`** เพราะธง `eligibility_uncertain` เป็นข้อสรุปของชั้น processing
  จะไปเติมใน `Schedule` ของชั้น data ไม่ได้ (`recommend` และ `format_schedules` จึงรับ `EligibleSchedule`)
- `EligibleSchedule` มี `uncertain_reason` ด้วย ตอนนี้มีค่าเดียวคือ `"จำกัดรุ่นปี"` (รอ Q4)
- `schedule_filter.YEAR_PREFIX_RULE_KNOWN = False` และ `_matches_year_prefix()` ยังเป็น `NotImplementedError`
  **เมื่อ Q4 มีคำตอบ: เติมวิธีเทียบในฟังก์ชันนั้น แล้วเปลี่ยนธงเป็น `True`** (มี test ยืนยันสถานะนี้ไว้)
- วันสุดท้ายของการรับสมัครยังถือว่าสมัครได้ (`registration_end_date.date() < today` จึงตัด)
- `formatter` ใช้**ชื่อหมวดเต็มจาก API** ไม่ย่อแบบตัวอย่างในแผน (`คุณธรรมฯ`) เพราะ prompt ห้ามบอทแต่งชื่อกิจกรรม/หมวดเอง
  แต่ย่อชื่อประเภทเป็น `(บังคับ)` / `(เลือก)` เพื่อลดความยาว
- รอบที่ยังไม่เปิดรับสมัครแสดง `เปิดรับสมัคร <วัน>` ส่วนรอบที่เปิดอยู่แสดง `ปิดรับสมัคร <วัน>`
- บรรทัดแนะนำจะไม่พูดชื่อหมวดซ้ำถ้าหมวดของรอบตรงกับหมวดที่ขาด (เหลือแค่ `ช่วยปิดช่องว่างได้ 6 ชม.`)
- `map_registrations` รับค่า `status` ที่ไม่รู้จักแล้ว**ไม่กรอง** (ค่ามาจาก LLM ซึ่งพิมพ์ผิดได้) ไม่ใช่คืน list ว่าง
- `ProgressReport` เพิ่ม `total_activities`, `is_complete`, `mandatory_gaps` และ `passed_items` เป็น `PassedItem` (แผนไม่ได้ระบุชนิด)
- **dependency ที่เพิ่ม:** `tzdata` (runtime — Python ของ uv บน Windows ไม่มี tz database `ZoneInfo("Asia/Bangkok")` จะ error) และ `pytest-cov` (dev — ใช้วัด DoD)

## Definition of Done

- `uv run pytest tests/unit/test_processing_*.py` ผ่าน coverage ≥ 90% ในโฟลเดอร์ `processing/`

ผลจริง (2026-10-20): `python -m uv run pytest tests/unit -q --cov=aura_agent.processing`
→ **127 passed · coverage 100%** (test ของ processing 80 ข้อใน 5 ไฟล์)

## Handoff → Phase 3

- ส่งต่อ: ฟังก์ชันทั้ง 5 กลุ่ม + ตัวอย่างข้อความจาก formatter
- tool ใน Phase 3 = `ActClient` + ฟังก์ชันพวกนี้ + `formatter` เท่านั้น ไม่ควรมี logic เพิ่ม

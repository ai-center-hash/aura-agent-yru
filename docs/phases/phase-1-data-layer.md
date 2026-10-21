# Phase 1 · Data Layer

**เป้าหมาย:** ดึงข้อมูลจาก Activity API แล้วได้ Pydantic object ที่ถูกต้อง พร้อม cache และ error ที่ชัดเจน

## Files

```
src/aura_agent/data/
├── act_client.py      # HTTP client
├── cache.py           # TTL cache
├── errors.py          # exception ของชั้นนี้
└── schemas/
    ├── summary.py     # Endpoint A
    ├── schedule.py    # Endpoint B
    └── registration.py# Endpoint C
tests/fixtures/  summary_me.json, schedules.json, registrations.json
tests/unit/test_act_client.py
```

## Tasks

- [x] Pydantic schema ตามฟิลด์ใน [02-activity-api-reference.md](../02-activity-api-reference.md) ใช้ `extra="ignore"` ฟิลด์ที่อาจไม่มีให้เป็น `Optional`
- [x] `ActClient` (async, ใช้ `httpx.AsyncClient` ตัวเดียวตลอดอายุของแอป)
- [x] แปลง error: 401 → `TokenExpired`, timeout/5xx → `UpstreamUnavailable`, parse ไม่ผ่าน → `UpstreamSchemaError`
- [x] retry 1 ครั้งเฉพาะ timeout/5xx (ไม่ retry 4xx)
- [x] cache: key = `(endpoint, params, sha256(jwt)[:16])` **ห้ามใช้ JWT ดิบเป็น key**
- [x] fixture สร้างจากตัวอย่างในคู่มือ API ไม่ใช้ข้อมูลจริง
- [ ] **เช็ค Q3:** (ต้องใช้ JWT จริง — รัน `scripts/check_act_api.py` ส่วน `[D]`) ลองเรียก `/v1/act/activities` (Student Mode) ด้วย JWT แล้วดูว่ากรองตามสิทธิ์ของผู้ใช้หรือไม่ บันทึกผลลง HANDOFF

## Interface

```python
class ActClient:
    def __init__(self, base_url: str, timeout_s: float, cache: Cache): ...

    async def get_my_summary(self, jwt: str) -> StudentSummary: ...
    async def get_schedules(
        self,
        jwt: str,
        *,
        phase: Literal["open", "upcoming"] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
    ) -> list[Schedule]: ...
    async def get_registrations(self, jwt: str, user_id: int) -> list[Registration]: ...
    async def ping(self) -> bool: ...  # ใช้ใน /v1/health
```

- ทุก method รับ `jwt` เป็น argument ไม่เก็บไว้ใน instance
- `get_registrations` รับ `user_id` ได้ เพราะชั้นนี้ไม่รู้ว่าค่ามาจากไหน **ส่วนที่รับประกันว่าค่ามาจาก summary/me คือ tool (Phase 3)**
- Streamed JSON (`paginate=false`) parse ได้ตามปกติด้วย `response.json()` เพราะผลรวมยังเป็น JSON ก้อนเดียว

## Tests (ใช้ `respx` mock HTTP)

| Test | ตรวจอะไร |
|---|---|
| parse fixture ทั้ง 3 ตัว | schema ถูกต้อง |
| 401 | ได้ `TokenExpired` |
| timeout 2 ครั้ง | retry 1 ครั้ง แล้วได้ `UpstreamUnavailable` |
| เรียกซ้ำภายใน TTL | ยิง HTTP แค่ครั้งเดียว |
| JWT ต่างกัน | ไม่ใช้ cache ร่วมกัน |

## สิ่งที่ทำจริง (2026-10-20)

ไฟล์ที่เพิ่มนอกเหนือจากแผน และเหตุผล:

| ไฟล์ | เหตุผล |
|---|---|
| `data/schemas/base.py` | `ActModel` (`extra="ignore"`) ให้ทุก schema สืบทอด ไม่ต้องเขียน `model_config` ซ้ำ |
| `tests/unit/test_cache.py` | แยก test ของ cache key / TTL ออกจาก test ของ client |
| `tests/fixtures/README.md` | อธิบายแต่ละแถวใน fixture และ **วันอ้างอิง 2026-10-20** ที่ Phase 2 ต้องใช้ |
| `scripts/check_act_api.py` | ปิด DoD ข้อที่ต้องใช้ JWT จริง โดยพิมพ์เฉพาะโครงสร้าง ไม่พิมพ์ข้อมูลส่วนบุคคล |

เปลี่ยนจากแผน:

- เพิ่ม error ตัวที่ 4 คือ `UpstreamRejected` สำหรับ 4xx อื่นที่ไม่ใช่ 401 (ไม่ retry) แผนเดิมมี 3 ตัว
  ทุก error มี `code`/`message_th` ตรงกับตารางใน [01-api-contract.md](../01-api-contract.md) ชั้น API จึงไม่ต้องแปลงอีก
- cache ใช้ `cachetools.TLRUCache` เพราะตั้ง TTL แยกต่อ key ได้ (summary/schedules 120 วิ, registrations 60 วิ)
  interface เป็น async (`get`/`set`) เพื่อให้สลับไปใช้ Redis ใน Phase 2 ได้โดยไม่ต้องแก้ `ActClient` และมี `NullCache` ไว้ใช้ตอนทดสอบกับ API จริง
- cache เก็บ JSON ดิบ ไม่เก็บ Pydantic object เพื่อให้ผู้เรียกแก้ object ที่ได้ไปโดยไม่กระทบของคนอื่น
- `ping()` ยิง `activity-schedules?paginate=true&per_page=1` และถือว่า 4xx = เซิร์ฟเวอร์ยังตอบ (เพราะไม่ได้ส่ง token)
- เพิ่ม `get_act_client()` / `close_act_client()` ให้ Phase 3–4 ใช้ `httpx.AsyncClient` ตัวเดียวตลอดอายุแอป
- schema **ไม่ประกาศ** ฟิลด์ที่ไม่ได้ใช้ซึ่งเป็นข้อมูลส่วนบุคคล (`email`, `user_name`, `user_code`) `extra="ignore"` จะทิ้งให้เอง
- ข้อความใน `UpstreamSchemaError` ใส่แค่ชื่อฟิลด์ที่ผิด ไม่ใส่ค่าที่ได้มา เพราะ error อาจถูก log

## Definition of Done

- `uv run pytest tests/unit/test_act_client.py` ผ่านทั้งหมด
- รัน script ทดสอบกับ API จริงด้วย JWT ของผู้พัฒนาแล้วได้ object ครบทั้ง 3 endpoint (ห้าม commit script ที่มี token)

## Handoff → Phase 2

- ส่งต่อ: `ActClient`, schema ทั้ง 3 ชุด, fixture, ผลของ Q3
- Phase 2 ใช้แค่ **schema + fixture** ไม่ต้องเรียก HTTP

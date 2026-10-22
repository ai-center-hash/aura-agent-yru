"""Exception ของชั้น data

`code` และ `message_th` ตรงกับตาราง error ใน docs/01-api-contract.md
ชั้น API (Phase 4) จึงหยิบไปใส่ `event: error` ได้เลยโดยไม่ต้องแปลงอีก
"""


class ActApiError(Exception):
    """error พื้นฐานของการเรียก Activity API"""

    code = "INTERNAL"
    message_th = "ขออภัยครับ ระบบมีปัญหาชั่วคราว ลองใหม่อีกครั้งนะครับ"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail or self.code)


class TokenExpired(ActApiError):
    """Activity API ตอบ 401 (token หมดอายุหรือใช้ไม่ได้)"""

    code = "TOKEN_EXPIRED"
    message_th = "เซสชันหมดอายุแล้วครับ กรุณาเข้าสู่ระบบใหม่"


class UpstreamUnavailable(ActApiError):
    """ต่อ Activity API ไม่ได้ timeout หรือตอบ 5xx (ยิงใหม่แล้วยังไม่ได้)"""

    code = "UPSTREAM_UNAVAILABLE"
    message_th = "ระบบกิจกรรมไม่พร้อมใช้งานชั่วคราวครับ ลองใหม่อีกครั้งในอีกสักครู่"


class UpstreamRejected(ActApiError):
    """Activity API ปฏิเสธ request ด้วย 4xx อื่นที่ไม่ใช่ 401 (เช่น 403, 404, 422)

    ไม่ยิงใหม่เพราะยิงอีกก็ได้ผลเดิม ใช้ code เดียวกับ UPSTREAM_UNAVAILABLE
    เพราะ frontend ทำอะไรต่างจากนั้นไม่ได้
    """

    code = "UPSTREAM_UNAVAILABLE"
    message_th = "ระบบกิจกรรมไม่รับคำขอนี้ครับ ถ้ายังเจออยู่รบกวนแจ้งกองพัฒนานักศึกษา"


class UpstreamSchemaError(ActApiError):
    """response ของ Activity API ไม่ตรงกับ schema ที่เราคาดไว้"""

    code = "INTERNAL"
    message_th = "ข้อมูลจากระบบกิจกรรมอยู่ในรูปแบบที่ผมอ่านไม่ได้ครับ รบกวนแจ้งกองพัฒนานักศึกษา"


class PassportUnavailable(UpstreamUnavailable):
    """ต่อ YRU Passport ไม่ได้ (ยืนยันตัวตนผู้ใช้ไม่ได้ชั่วคราว)"""

    message_th = "ระบบยืนยันตัวตน (YRU Passport) ไม่พร้อมใช้งานชั่วคราวครับ ลองใหม่อีกครั้งในอีกสักครู่"


class NotAStudent(ActApiError):
    """token ใช้ได้ แต่เจ้าของไม่ใช่นักศึกษา (เช่น อาจารย์ เจ้าหน้าที่)

    บุคลากรยังคุยกับบอทได้ (ค้นหารอบกิจกรรม) แต่ไม่มีความคืบหน้าหรือประวัติของตัวเอง
    `ActClient.get_my_summary` จึงโยน error นี้แทนการเอา username ของบุคลากรไปค้นข้อมูลนักศึกษา
    พก `identity` มาด้วยเหมือน `NoActivityFrame` เพื่อให้ agent รู้ว่าคุยกับใคร
    """

    code = "NOT_STUDENT"
    message_th = "ส่วนนี้ใช้ได้เฉพาะนักศึกษาครับ บัญชีที่เข้าสู่ระบบอยู่ไม่ใช่บัญชีนักศึกษา"

    def __init__(self, detail: str = "", *, identity: object | None = None) -> None:
        super().__init__(detail)
        self.identity = identity


class NoActivityFrame(ActApiError):
    """ระบบกิจกรรมยังไม่มีกรอบกิจกรรมที่ตรงกับกลุ่มของนักศึกษาคนนี้ (`no_frame: true`)

    ไม่ใช่ความผิดพลาดของระบบ แต่เป็นสถานะของนักศึกษา จึงพก `identity` (ถ้ารู้) มาด้วย
    เพื่อให้ยังคุยต่อได้ เช่น ค้นหากิจกรรม แม้จะดูความคืบหน้าไม่ได้
    """

    code = "NO_FRAME"
    message_th = (
        "ระบบกิจกรรมยังไม่มีกรอบกิจกรรมที่ตรงกับกลุ่มของคุณครับ จึงยังดูความคืบหน้าไม่ได้ รบกวนติดต่อกองพัฒนานักศึกษา"
    )

    def __init__(self, detail: str = "", *, identity: object | None = None) -> None:
        super().__init__(detail)
        self.identity = identity

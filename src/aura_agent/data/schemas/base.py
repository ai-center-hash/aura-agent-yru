"""base ของทุก schema ในชั้น data"""

from pydantic import BaseModel, ConfigDict


class ActModel(BaseModel):
    """ฟิลด์ที่ไม่รู้จักให้ข้ามไป เพื่อไม่ให้พังเมื่อ Activity API เพิ่มฟิลด์ใหม่

    ผลพลอยได้: ฟิลด์ที่เราไม่ได้ใช้ (เช่น email, ชื่อผู้ลงทะเบียนคนอื่น) จะไม่ถูกเก็บไว้ในหน่วยความจำ
    """

    model_config = ConfigDict(extra="ignore")

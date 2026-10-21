"""state ของ graph

**JWT ไม่อยู่ใน state** เพราะ state ถูกบันทึกลง SQLite — ส่งผ่าน `config["configurable"]["jwt"]` เท่านั้น
ทุกฟิลด์อาจยังไม่มีค่าในรอบแรก ให้อ่านด้วย `state.get(...)` เสมอ
"""

from langgraph.graph import MessagesState

from ..processing import StudentProfile

STUDENT_TTL_S = 120.0  # ข้อมูลนักศึกษาเก่ากว่านี้ให้ load_student ดึงใหม่
MAX_TOOL_ROUNDS = 4  # เกินนี้บังคับให้ LLM ตอบจากข้อมูลที่มี กันเรียก tool วนไม่จบ


class AgentState(MessagesState):
    student: StudentProfile | None  # มาจาก summary/me เท่านั้น (.id คือ user_id ที่เชื่อถือได้)
    progress_text: str | None  # ผลจาก format_progress ใส่ใน system prompt ทุกครั้ง
    loaded_at: float | None  # epoch วินาทีที่โหลดข้อมูลนักศึกษาล่าสุด
    tool_rounds: int  # จำนวนรอบที่เรียก tool ในคำถามนี้ (reset ทุกข้อความใหม่)

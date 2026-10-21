"""สร้าง LLM ตาม `LLM_PROVIDER`

Phase 1 ใช้ Ollama · Phase 2 (server ใหม่) สลับเป็น vLLM ผ่าน `LLM_PROVIDER=openai_compatible`
โดยไม่ต้องแก้โค้ดส่วนอื่น
"""

import os

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from ..config import get_settings

MISSING_OPENAI_PACKAGE = (
    "LLM_PROVIDER=openai_compatible ต้องติดตั้ง langchain-openai ก่อน"
    " (python -m uv add langchain-openai)"
)


def build_llm() -> BaseChatModel:
    """สร้าง LLM ใหม่ตามค่าใน .env"""
    settings = get_settings()

    if settings.llm_provider == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_ctx=settings.llm_num_ctx,
            reasoning=settings.llm_think,  # False = ปิด thinking (เร็วกว่ามากกับ qwen3.6)
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as error:  # pragma: no cover - ขึ้นกับ dependency ที่ติดตั้ง
        raise RuntimeError(MISSING_OPENAI_PACKAGE) from error

    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=os.environ.get("LLM_API_KEY", "not-needed"),  # vLLM ไม่ตรวจ key
        temperature=settings.llm_temperature,
    )


_llm: BaseChatModel | None = None


def get_llm() -> BaseChatModel:
    """LLM ตัวเดียวของแอป (สร้างครั้งแรกที่เรียก)"""
    global _llm
    if _llm is None:
        _llm = build_llm()
    return _llm


def set_llm(llm: BaseChatModel | None) -> None:
    """ตั้ง LLM ที่ใช้ร่วมกัน ใช้ใน test หรือเวลาต้องการสลับโมเดลตอนรัน"""
    global _llm
    _llm = llm

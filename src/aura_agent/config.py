"""ค่าตั้งค่าทั้งหมดของแอป อ่านจาก environment variable หรือไฟล์ .env"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: Literal["ollama", "openai_compatible"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    llm_base_url: str | None = None  # ใช้เมื่อ llm_provider=openai_compatible (เช่น vLLM)
    llm_model: str = "qwen3.6:35b-a3b"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_think: bool = False
    llm_num_ctx: int = Field(default=16384, gt=0)

    # Activity API
    act_api_base_url: str = "https://api831.yru.ac.th/act/api"
    act_api_timeout_s: float = Field(default=15, gt=0)

    # ยืนยันตัวตน: passport = ถาม YRU Passport แล้วเรียกเส้น public ด้วยรหัสนักศึกษา
    #              activity_me = ส่ง token ตรงไปที่ /summary/me (เมื่อ Activity API รับ token ได้แล้ว)
    identity_mode: Literal["passport", "activity_me"] = "passport"
    passport_base_url: str = "https://passport.yru.ac.th"
    passport_timeout_s: float = Field(default=10, gt=0)

    # OAuth client ของ YRU Passport — ใช้เฉพาะหน้าแชททดสอบและสคริปต์ในเครื่องผู้พัฒนา
    # (ของจริง backend เดิมเป็นคนทำ login แล้วส่ง token มาให้ AURA)
    passport_client_id: str | None = None
    passport_client_secret: SecretStr | None = None
    passport_redirect_uri: str | None = None  # ไม่ใส่ = http://127.0.0.1[:port]/callback

    # Service
    service_key: SecretStr = Field(min_length=16)
    checkpointer: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = "./data/aura.sqlite"
    cache: Literal["memory", "redis"] = "memory"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    expose_docs: bool = False  # เปิด /docs และ /openapi.json (เครื่องผู้พัฒนา) · เครื่องจริงปิดไว้
    # username ที่ได้สิทธิ์ผู้ดูแลระบบในบอทแม้ไม่มี role admin ในระบบกิจกรรม คั่นด้วย comma
    # **ใช้บนเครื่องผู้พัฒนาเท่านั้น** ค่าเริ่มต้นว่าง · ทุกการใช้สิทธิ์ถูกบันทึกใน audit log
    dev_admin_usernames: str = ""
    timezone: str = "Asia/Bangkok"

    @property
    def dev_admins(self) -> frozenset[str]:
        return frozenset(
            name.strip().lower() for name in self.dev_admin_usernames.split(",") if name.strip()
        )

    @model_validator(mode="after")
    def _check_provider_url(self) -> "Settings":
        if self.llm_provider == "openai_compatible" and not self.llm_base_url:
            raise ValueError("LLM_BASE_URL is required when LLM_PROVIDER=openai_compatible")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

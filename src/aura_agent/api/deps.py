"""dependency ของ API: ตรวจ service key, ดึง JWT, หยิบ graph

**ไม่ verify ลายเซ็น JWT เอง** ให้ Activity API เป็นผู้ตัดสิน (ถ้าใช้ไม่ได้จะรู้ตอนเรียก `summary/me`)
"""

import secrets
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from ..config import get_settings

BEARER_PREFIX = "bearer "

BAD_SERVICE_KEY = "X-Service-Key ไม่ถูกต้องหรือไม่ได้ส่งมา"
BAD_AUTHORIZATION = "ต้องส่ง header Authorization: Bearer <JWT ของนักศึกษา>"
GRAPH_NOT_READY = "ระบบยังไม่พร้อมใช้งาน"


async def check_service_key(x_service_key: Annotated[str | None, Header()] = None) -> None:
    """เทียบ key แบบ constant time กันการเดาจากเวลาที่ใช้ตอบ"""
    expected = get_settings().service_key.get_secret_value()
    if not x_service_key or not secrets.compare_digest(x_service_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_SERVICE_KEY)


async def get_jwt(authorization: Annotated[str | None, Header()] = None) -> str:
    """ดึง JWT ของนักศึกษาจาก header (ไม่ log ค่า)"""
    if not authorization or not authorization.lower().startswith(BEARER_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_AUTHORIZATION)

    jwt = authorization[len(BEARER_PREFIX) :].strip()
    if not jwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_AUTHORIZATION)
    return jwt


async def get_optional_jwt(authorization: Annotated[str | None, Header()] = None) -> str | None:
    """JWT ถ้ามี · ไม่ส่ง header มาเลย = ผู้ใช้ที่ไม่ได้เข้าสู่ระบบ (ค้นหากิจกรรมได้อย่างเดียว)

    ส่ง header มาแต่รูปแบบผิด ยังตอบ 401 เพื่อให้ฝั่งที่เรียกรู้ว่าส่งผิด ไม่ใช่กลายเป็นผู้ใช้ทั่วไปเงียบๆ
    """
    if authorization is None:
        return None
    return await get_jwt(authorization)


def get_graph(request: Request) -> Any:
    """graph ที่ lifespan สร้างไว้"""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:  # pragma: no cover - เกิดได้เฉพาะเมื่อ lifespan ไม่ทำงาน
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, GRAPH_NOT_READY)
    return graph


Jwt = Annotated[str, Depends(get_jwt)]
OptionalJwt = Annotated[str | None, Depends(get_optional_jwt)]
ServiceKey = Annotated[None, Depends(check_service_key)]
Graph = Annotated[Any, Depends(get_graph)]

"""ติดตั้ง/อัปเดต Function `aura` ใน YRU Nexus ผ่าน SSH (ทำแบบเดียวกับ Admin Panel → Functions)

รันใน container ของ Nexus · อ่าน SERVICE_KEY จาก stdin (ไม่ผ่าน argv)
ไฟล์ Pipe ต้องอยู่ที่ /tmp/aura_pipe.py
ขั้นตอนเต็มอยู่ใน docs/05-openwebui-nexus.md หัวข้อ "ติดตั้งผ่าน SSH"
"""

import asyncio
import json
import sys
from pathlib import Path

from open_webui.models.functions import FunctionForm, FunctionMeta, Functions
from open_webui.models.users import Users
from open_webui.utils.plugin import load_function_module_by_id

FUNCTION_ID = "aura"
AURA_URL = "http://10.20.41.54:8100"


async def main() -> None:
    key = sys.stdin.read().strip()
    assert len(key) >= 32, "SERVICE_KEY สั้นผิดปกติ"
    content = Path("/tmp/aura_pipe.py").read_text(encoding="utf-8")  # noqa: ASYNC240

    module, function_type, frontmatter = await load_function_module_by_id(
        FUNCTION_ID, content=content
    )
    assert function_type == "pipe", function_type
    name = frontmatter.get("title", "AURA กิจกรรมนักศึกษา")
    meta = FunctionMeta(description=frontmatter.get("description"), manifest=frontmatter)

    existing = await Functions.get_function_by_id(FUNCTION_ID)
    if existing is None:
        admin = await Users.get_super_admin_user()
        assert admin is not None, "ไม่พบ admin"
        created = await Functions.insert_new_function(
            admin.id,
            function_type,
            FunctionForm(id=FUNCTION_ID, name=name, content=content, meta=meta),
        )
        assert created is not None, "insert ไม่สำเร็จ"
        action = "created"
    else:
        await Functions.update_function_by_id(
            FUNCTION_ID, {"content": content, "name": name, "meta": meta.model_dump()}
        )
        action = "updated"

    await Functions.update_function_by_id(FUNCTION_ID, {"is_active": True})
    await Functions.update_function_valves_by_id(
        FUNCTION_ID, {"AURA_BASE_URL": AURA_URL, "AURA_SERVICE_KEY": key}
    )

    saved = await Functions.get_function_by_id(FUNCTION_ID)
    print(
        json.dumps(
            {
                "action": action,
                "id": saved.id,
                "name": saved.name,
                "type": saved.type,
                "is_active": saved.is_active,
                "pipes": module.pipes(),  # load_function_module_by_id คืน instance ของ Pipe แล้ว
                "has_valves": bool(await Functions.get_function_valves_by_id(FUNCTION_ID)),
            },
            ensure_ascii=False,
        )
    )


asyncio.run(main())

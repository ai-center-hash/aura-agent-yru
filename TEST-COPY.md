# AURA-AGENT-TEST · สำเนาสำหรับทดสอบโมเดลและเซิร์ฟเวอร์ใหม่

สร้าง 2026-11-05 จาก `main` ที่ `5532937` ของ AURA-AGENT เพื่อลองโมเดล/เซิร์ฟเวอร์ GPU ใหม่บน Google Cloud
โดยไม่แตะโปรเจกต์ตัวจริง

## ข้อแตกต่างจากตัวจริง

- **push ถูกปิด** (`git remote set-url --push origin DISABLED-...`) เพราะเครื่องจริง deploy จาก `main` บน GitHub
  ถ้าผลทดสอบดีและอยากนำไปใช้ ให้นำการแก้ไปทำใน AURA-AGENT แล้วรัน eval ที่นั่น
- ทำงานบน branch `model-test`
- **ห้ามรัน `deploy/install.sh` จากโฟลเดอร์นี้** และห้ามคัดลอก `.env` นี้ไปเครื่องจริง (มี `DEV_ADMIN_USERNAMES`)
- `.env` คัดลอกมาจากตัวจริง ส่วนท้ายไฟล์มีตัวอย่างการตั้งค่าเซิร์ฟเวอร์ใหม่
- ฐานข้อมูลแชท `./data/aura.sqlite` แยกจากตัวจริง (path เป็นแบบ relative)
- `scripts/dev_chat.py` ใช้ port 80 เหมือนตัวจริง จึงเปิดพร้อมกันทั้ง 2 โฟลเดอร์ไม่ได้

## ขั้นตอนทดสอบโมเดลใหม่

```bash
python -m uv run python tests/evals/run_evals.py --model <ชื่อโมเดล>   # เทียบกับ qwen3.6:35b-a3b บน yru-ai (69/69)
python -m uv run python scripts/dev_chat.py                          # ลองคุยเอง
```

ผลอ้างอิงของตัวจริง (qwen3.6:35b-a3b บน yru-ai, 2026-10-29): eval 69/69 · tool/fact/safety 100% · TTFT p50 3.2 วิ · เวลาตอบรวม p50 5.1 วิ

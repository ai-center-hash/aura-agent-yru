# AURA-AGENT-TEST · สำเนาสำหรับทดสอบโมเดลและเซิร์ฟเวอร์ใหม่

สร้าง 2026-11-05 จาก `main` ที่ `5532937` ของ AURA-AGENT เพื่อลองโมเดล/เซิร์ฟเวอร์ GPU ใหม่บน Google Cloud
โดยไม่แตะโปรเจกต์ตัวจริง

## ข้อแตกต่างจากตัวจริง

- ทำงานบน branch `model-test` · **push ได้เฉพาะ `model-test`** (`git push` เฉยๆ ส่งแค่ branch นี้ และ hook `pre-push` ปฏิเสธ `main`)
  เพราะเครื่องจริง deploy จาก `main` บน GitHub · ถ้าผลทดสอบดีและอยากนำไปใช้ ให้นำการแก้ไปทำใน AURA-AGENT แล้วรัน eval ที่นั่น
- **ห้ามรัน `deploy/install.sh` จากโฟลเดอร์นี้** (ตัวทดสอบใช้ `deploy/install-test.sh`) และห้ามคัดลอก `.env` นี้ไปเครื่องจริง (มี `DEV_ADMIN_USERNAMES`)
- `.env` คัดลอกมาจากตัวจริง ส่วนท้ายไฟล์มีตัวอย่างการตั้งค่าเซิร์ฟเวอร์ใหม่
- ฐานข้อมูลแชท `./data/aura.sqlite` แยกจากตัวจริง (path เป็นแบบ relative)
- `scripts/dev_chat.py` ใช้ port 80 เหมือนตัวจริง จึงเปิดพร้อมกันทั้ง 2 โฟลเดอร์ไม่ได้

## ขั้นตอนทดสอบโมเดลใหม่

```bash
python -m uv run python tests/evals/run_evals.py --model <ชื่อโมเดล>   # เทียบกับ qwen3.6:35b-a3b บน yru-ai (69/69)
python -m uv run python scripts/dev_chat.py                          # ลองคุยเอง
```

ผลอ้างอิงของตัวจริง (qwen3.6:35b-a3b บน yru-ai, 2026-10-29): eval 69/69 · tool/fact/safety 100% · TTFT p50 3.2 วิ · เวลาตอบรวม p50 5.1 วิ

## ผลทดสอบเซิร์ฟเวอร์ Google Cloud `136.80.98.1` · 2026-11-05

- Open WebUI 0.13.0 ที่ port 3000 · Ollama 0.40.14 ที่ port 11434 · โมเดล `qwen2.5:14b` (Q4_K_M, 9 GB)
- **โมเดลรันบน CPU** (`/api/ps` → `size_vram: 0`): อ่าน prompt ~10 token/วิ · ตอบ ~1.8 token/วิ
  system prompt + tool ของ AURA ราว 3–4 พัน token → ข้อเดียวหลายนาที (eval 2 ข้อไม่เสร็จใน 10 นาที) · ตัวจริงบน yru-ai TTFT 3.2 วิ
- **port 11434 เปิดสู่อินเทอร์เน็ตโดยไม่มีการยืนยันตัวตน** ต้องปิดด้วย firewall ของ Google Cloud แล้วใช้ SSH tunnel แบบ yru-ai
- `.env` ของโฟลเดอร์นี้ชี้ไปที่เครื่องนี้แล้ว (`OLLAMA_BASE_URL`, `LLM_MODEL=qwen2.5:14b`)

## ตัวทดสอบบน yru-ai · `http://10.20.41.54:8101`

แยกจากตัวจริง (`:8100`) ทั้งหมด: `/opt/aura-agent-test` · service `aura-agent-test` · ฐานข้อมูลแชทของตัวเอง ·
ลบแชทเก่าด้วย `aura-prune-test.timer` (03:30) · ใช้ user `aura` และ deploy key เดียวกับตัวจริง ·
API และ `SERVICE_KEY` เหมือนตัวจริง backend เปลี่ยนแค่ URL ([docs/01-api-contract.md](docs/01-api-contract.md))

ครั้งแรก (บน yru-ai · ดึงสคริปต์จาก branch นี้ผ่าน repo ของตัวจริง ไม่แตะไฟล์ของตัวจริง):

```bash
sudo -u aura env GIT_SSH_COMMAND="ssh -i /etc/aura-agent/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/aura-agent/known_hosts" git -C /opt/aura-agent fetch -q origin model-test && sudo -u aura git -C /opt/aura-agent show FETCH_HEAD:deploy/install-test.sh > /tmp/install-test.sh && sudo bash /tmp/install-test.sh
```

ครั้งต่อไป: `sudo bash /opt/aura-agent-test/deploy/install-test.sh` · เปลี่ยนโมเดล: แก้ `LLM_MODEL` ใน `/opt/aura-agent-test/.env`
แล้ว `sudo systemctl restart aura-agent-test` · log: `journalctl -u aura-agent-test -n 50`

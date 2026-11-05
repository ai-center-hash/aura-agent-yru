#!/usr/bin/env bash
# ติดตั้งหรืออัปเดต AURA-AGENT-TEST (ทดสอบโมเดล/เซิร์ฟเวอร์ใหม่) บนเครื่อง yru-ai · รันด้วย sudo
#
#   sudo bash install-test.sh                       # ครั้งแรก (ดาวน์โหลดไฟล์นี้มาก่อน ดู TEST-COPY.md)
#   sudo bash /opt/aura-agent-test/deploy/install-test.sh   # ครั้งต่อไป: pull + sync + restart
#
# แยกจากตัวจริงทั้งหมด: โฟลเดอร์ /opt/aura-agent-test · branch model-test · service aura-agent-test · port 8101
# ใช้ user `aura` และ deploy key เดียวกับตัวจริง (install.sh ต้องเคยรันแล้ว)
# .env ครั้งแรกคัดลอกจาก /opt/aura-agent/.env แล้วเปลี่ยนเฉพาะค่าของโมเดล · ครั้งต่อไปสคริปต์ไม่แตะไฟล์นี้
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:ai-center-hash/aura-agent-yru.git}"
BRANCH="${BRANCH:-model-test}"
APP_DIR=/opt/aura-agent-test
PROD_DIR=/opt/aura-agent
PORT=8101
SERVICE=aura-agent-test
APP_USER=aura
KEY_DIR=/etc/aura-agent
GIT_SSH="ssh -i $KEY_DIR/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$KEY_DIR/known_hosts -o StrictHostKeyChecking=accept-new"
TEST_OLLAMA_URL="${TEST_OLLAMA_URL:-http://136.80.98.1:11434}"
TEST_MODEL="${TEST_MODEL:-qwen2.5:14b}"

as_app() {
  sudo -u "$APP_USER" env HOME="$APP_DIR" GIT_SSH_COMMAND="$GIT_SSH" \
    UV_CACHE_DIR="$APP_DIR/.uv-cache" UV_PYTHON_INSTALL_DIR="$APP_DIR/.uv-python" "$@"
}

# แทนค่า KEY=... ใน .env (ไม่มีก็เพิ่มท้ายไฟล์) · ไม่ใส่ comment ท้ายบรรทัด เพราะ EnvironmentFile ของ systemd ไม่ตัดให้
set_env() {
  if grep -q "^$1=" "$APP_DIR/.env"; then
    sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"
  else
    echo "$1=$2" >>"$APP_DIR/.env"
  fi
}

if [[ $EUID -ne 0 ]]; then
  echo "ต้องรันด้วย sudo" >&2
  exit 1
fi
if [[ ! -f "$KEY_DIR/deploy_key" || ! -f "$PROD_DIR/.env" ]]; then
  echo "ยังไม่มีตัวจริงบนเครื่องนี้ ($KEY_DIR/deploy_key, $PROD_DIR/.env) ให้รัน deploy/install.sh ก่อน" >&2
  exit 1
fi

cd /
if [[ ! -d "$APP_DIR/.git" ]]; then
  install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
  as_app git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  as_app git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  as_app git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  install -m 600 -o "$APP_USER" -g "$APP_USER" "$PROD_DIR/.env" "$APP_DIR/.env"
  sed -i '/^DEV_ADMIN_USERNAMES=/d' "$APP_DIR/.env"
  set_env LLM_PROVIDER ollama
  set_env OLLAMA_BASE_URL "$TEST_OLLAMA_URL"
  set_env LLM_MODEL "$TEST_MODEL"
  echo "สร้าง $APP_DIR/.env จากตัวจริงแล้ว (โมเดล $TEST_MODEL ที่ $TEST_OLLAMA_URL)"
fi
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data"

cd "$APP_DIR"
as_app /usr/local/bin/uv sync --frozen --no-dev

# unit ของตัวทดสอบสร้างจากของตัวจริง: เปลี่ยน path, port และชื่อ (ตัวลบแชทเก่ารัน 03:30 ไม่ชนกับตัวจริง)
to_test() {
  sed -e "s|$PROD_DIR|$APP_DIR|g" -e "s|--port 8100|--port $PORT|" \
    -e "s|Description=AURA-AGENT|Description=AURA-AGENT-TEST|" \
    -e "s|After=network-online.target ollama.service|After=network-online.target|" \
    -e "s|03:00:00|03:30:00|" "$1" >"$2"
  chmod 644 "$2"
}
to_test "$APP_DIR/deploy/aura-agent.service" "/etc/systemd/system/$SERVICE.service"
to_test "$APP_DIR/deploy/aura-prune.service" /etc/systemd/system/aura-prune-test.service
to_test "$APP_DIR/deploy/aura-prune.timer" /etc/systemd/system/aura-prune-test.timer
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl enable --quiet --now aura-prune-test.timer
systemctl restart "$SERVICE"

echo "รอ service ขึ้น..."
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
    curl -sS "http://127.0.0.1:$PORT/v1/health"
    echo
    echo "deploy ตัวทดสอบสำเร็จ: $(as_app git -C "$APP_DIR" rev-parse --short HEAD) → http://10.20.41.54:$PORT"
    exit 0
  fi
  sleep 2
done
echo "service ไม่ตอบ /v1/health ภายใน 60 วินาที ดู log: journalctl -u $SERVICE -n 50" >&2
exit 1

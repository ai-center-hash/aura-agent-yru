#!/usr/bin/env bash
# ติดตั้งหรืออัปเดต AURA-AGENT บนเครื่อง yru-ai (Ubuntu) · รันด้วย sudo
#
#   sudo bash deploy/install.sh            # ครั้งแรก: สร้าง user, clone, ติดตั้ง service
#   sudo bash /opt/aura-agent/deploy/install.sh   # ครั้งต่อไป: pull + sync + restart
#
# ไฟล์ /opt/aura-agent/.env ต้องสร้างเองครั้งแรก (คัดลอกจาก .env.example) สคริปต์ไม่แตะไฟล์นี้
# repo เป็น private: clone ด้วย deploy key (อ่านอย่างเดียว) ที่ /etc/aura-agent/deploy_key
# ครั้งแรกสคริปต์จะสร้าง key ให้ แล้วหยุดให้ไปเพิ่ม public key ใน GitHub → Settings → Deploy keys
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:ai-center-hash/aura-agent-yru.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/aura-agent
APP_USER=aura
KEY_DIR=/etc/aura-agent
GIT_SSH="ssh -i $KEY_DIR/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=$KEY_DIR/known_hosts -o StrictHostKeyChecking=accept-new"

# รันคำสั่งในนาม user ของแอป · ส่งตัวแปรผ่าน env เพราะ sudo ของ Ubuntu 26.04 (sudo-rs) ไม่รองรับ -E
as_app() {
  sudo -u "$APP_USER" env HOME="$APP_DIR" GIT_SSH_COMMAND="$GIT_SSH" \
    UV_CACHE_DIR="$APP_DIR/.uv-cache" UV_PYTHON_INSTALL_DIR="$APP_DIR/.uv-python" "$@"
}

if [[ $EUID -ne 0 ]]; then
  echo "ต้องรันด้วย sudo" >&2
  exit 1
fi

if ! command -v /usr/local/bin/uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

if [[ ! -f "$KEY_DIR/deploy_key" ]]; then
  install -d -m 750 -o root -g "$APP_USER" "$KEY_DIR"
  ssh-keygen -q -t ed25519 -N "" -C "aura-agent@yru-ai" -f "$KEY_DIR/deploy_key"
  chown "$APP_USER:$APP_USER" "$KEY_DIR/deploy_key" "$KEY_DIR/deploy_key.pub"
  chmod 600 "$KEY_DIR/deploy_key"
  install -m 664 -o root -g "$APP_USER" /dev/null "$KEY_DIR/known_hosts"
fi

cd /
if ! as_app git ls-remote "$REPO_URL" >/dev/null 2>&1; then
  echo "เครื่องนี้ยังอ่าน repo ไม่ได้ เพิ่ม public key นี้ใน GitHub → repo → Settings → Deploy keys (ไม่ต้องติ๊ก write):" >&2
  cat "$KEY_DIR/deploy_key.pub" >&2
  exit 2
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
  as_app git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  as_app git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  as_app git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "ยังไม่มี $APP_DIR/.env — คัดลอกจาก .env.example แล้วแก้ค่า จากนั้นรันสคริปต์นี้อีกครั้ง" >&2
  exit 1
fi
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data"

cd "$APP_DIR"
as_app /usr/local/bin/uv sync --frozen --no-dev

install -m 644 "$APP_DIR/deploy/aura-agent.service" /etc/systemd/system/aura-agent.service
systemctl daemon-reload
systemctl enable --quiet aura-agent
systemctl restart aura-agent

echo "รอ service ขึ้น..."
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8100/v1/health >/dev/null 2>&1; then
    curl -sS http://127.0.0.1:8100/v1/health
    echo
    echo "deploy สำเร็จ: $(as_app git -C "$APP_DIR" rev-parse --short HEAD)"
    exit 0
  fi
  sleep 2
done
echo "service ไม่ตอบ /v1/health ภายใน 60 วินาที ดู log: journalctl -u aura-agent -n 50" >&2
exit 1

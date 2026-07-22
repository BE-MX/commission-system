#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/social-customer-mcp
SERVICE_NAME=social-customer-mcp

for command_name in python3 curl systemctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: $command_name is required. Install the documented OS packages first." >&2
    exit 1
  fi
done

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "ERROR: python3-venv is required. Install the documented OS packages first." >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "ERROR: $APP_DIR/.env is missing; create the 0600 environment file first." >&2
  exit 1
fi

cd "$APP_DIR"

if ! id "$SERVICE_NAME" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_NAME"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.lock"

chown -R root:"$SERVICE_NAME" "$APP_DIR"
chmod 0750 "$APP_DIR"
chmod 0600 "$APP_DIR/.env"
find "$APP_DIR/social_customer_mcp" -type d -exec chmod 0750 {} +
find "$APP_DIR/social_customer_mcp" -type f -exec chmod 0640 {} +

install -o root -g root -m 0644 \
  "$APP_DIR/deploy/social-customer-mcp.service" \
  "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 2
systemctl is-active --quiet "$SERVICE_NAME"
curl --fail --silent --show-error http://127.0.0.1:8100/health >/dev/null
systemctl --no-pager --full status "$SERVICE_NAME"

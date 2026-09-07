#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo ./scripts/install-systemd.sh" >&2
  exit 1
fi
APP_DIR=/opt/bird-corroborator
if [ ! -f "$APP_DIR/pyproject.toml" ]; then
  echo "Copy the repository to $APP_DIR before running this script." >&2
  exit 1
fi
command -v python3 >/dev/null
if ! id birdcorroborator >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin birdcorroborator
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install "$APP_DIR"
install -d -o birdcorroborator -g birdcorroborator -m 0750 "$APP_DIR/data"
if [ ! -f "$APP_DIR/.env" ]; then
  install -o root -g birdcorroborator -m 0640 "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "Created $APP_DIR/.env; configure it before starting the service."
else
  chown root:birdcorroborator "$APP_DIR/.env"
  chmod 0640 "$APP_DIR/.env"
fi
install -o root -g root -m 0644 "$APP_DIR/deploy/bird-corroborator.service" /etc/systemd/system/bird-corroborator.service
systemctl daemon-reload
echo "Installed but NOT enabled and NOT started. Edit .env, then run: sudo systemctl start bird-corroborator"

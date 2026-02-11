#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ACB-prgm/HomeAutomation.git}"
BRANCH="${BRANCH:-codex/ai-dev}"
INSTALL_DIR="${INSTALL_DIR:-/opt/homeautomation}"
CONFIG_PATH="${CONFIG_PATH:-/etc/home-satellite/satellite.json}"
IDENTITY_PATH="${IDENTITY_PATH:-/var/lib/satellite/identity.json}"
ENV_FILE="${ENV_FILE:-/etc/default/home-satellite}"
MQTT_BROKER="${MQTT_BROKER:-127.0.0.1}"
MQTT_PORT="${MQTT_PORT:-1883}"
UPDATE_TOKEN="${UPDATE_TOKEN:-change-me}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$USER}}"
SKIP_APT=0

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Provision a Raspberry Pi with satellites-only sparse checkout, bootstrap runtime,
and install systemd services for runtime + updater.

Options:
  --repo-url <url>         Git repository URL (default: $REPO_URL)
  --branch <name>          Git branch to deploy (default: $BRANCH)
  --install-dir <path>     Install directory (default: $INSTALL_DIR)
  --config-path <path>     Persistent satellite config path (default: $CONFIG_PATH)
  --identity-path <path>   Persistent identity path (default: $IDENTITY_PATH)
  --service-user <name>    User running home-satellite.service (default: $SERVICE_USER)
  --mqtt-broker <host>     MQTT broker for updater daemon (default: $MQTT_BROKER)
  --mqtt-port <port>       MQTT broker port (default: $MQTT_PORT)
  --update-token <token>   Shared token for update messages (default: change-me)
  --skip-apt               Skip apt installation
  -h, --help               Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo-url)
		REPO_URL="$2"
		shift 2
		;;
	--branch)
		BRANCH="$2"
		shift 2
		;;
	--install-dir)
		INSTALL_DIR="$2"
		shift 2
		;;
	--config-path)
		CONFIG_PATH="$2"
		shift 2
		;;
	--identity-path)
		IDENTITY_PATH="$2"
		shift 2
		;;
	--service-user)
		SERVICE_USER="$2"
		shift 2
		;;
	--mqtt-broker)
		MQTT_BROKER="$2"
		shift 2
		;;
	--mqtt-port)
		MQTT_PORT="$2"
		shift 2
		;;
	--update-token)
		UPDATE_TOKEN="$2"
		shift 2
		;;
	--skip-apt)
		SKIP_APT=1
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "Unknown option: $1" >&2
		usage
		exit 1
		;;
	esac
done

log() {
	echo "[pi-install] $*"
}

require_cmd() {
	local cmd="$1"
	if ! command -v "$cmd" >/dev/null 2>&1; then
		echo "Missing required command: $cmd" >&2
		exit 1
	fi
}

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
	if command -v sudo >/dev/null 2>&1; then
		exec sudo --preserve-env=REPO_URL,BRANCH,INSTALL_DIR,CONFIG_PATH,IDENTITY_PATH,ENV_FILE,MQTT_BROKER,MQTT_PORT,UPDATE_TOKEN,SERVICE_USER,SKIP_APT "$0" "$@"
	else
		echo "Run as root (or install sudo)." >&2
		exit 1
	fi
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
	echo "Service user '$SERVICE_USER' does not exist." >&2
	exit 1
fi

if [[ "$SKIP_APT" -eq 0 && -f /etc/debian_version ]]; then
	log "Installing OS dependencies"
	apt-get update
	apt-get install -y git python3 python3-venv python3-pip ca-certificates curl
fi

require_cmd git
require_cmd python3
require_cmd systemctl

log "Preparing install directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
	log "Cloning repository"
	rm -rf "$INSTALL_DIR"
	git clone --filter=blob:none --no-checkout "$REPO_URL" "$INSTALL_DIR"
fi

log "Configuring sparse checkout for satellites/"
git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
git -C "$INSTALL_DIR" sparse-checkout init --cone
git -C "$INSTALL_DIR" sparse-checkout set satellites
git -C "$INSTALL_DIR" fetch origin "$BRANCH"
git -C "$INSTALL_DIR" checkout -B "$BRANCH" "origin/$BRANCH"

log "Preparing persistent config + identity directories"
mkdir -p "$(dirname "$CONFIG_PATH")"
mkdir -p "$(dirname "$IDENTITY_PATH")"
chown "$SERVICE_USER":"$SERVICE_USER" "$(dirname "$IDENTITY_PATH")"

if [[ ! -f "$CONFIG_PATH" ]]; then
	cp "$INSTALL_DIR/satellites/config/satellite.json" "$CONFIG_PATH"
fi

python3 - <<PY
from pathlib import Path
import json

cfg_path = Path("${CONFIG_PATH}")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
cfg.setdefault("identity", {})
cfg["identity"]["path"] = "${IDENTITY_PATH}"
cfg["identity"].setdefault("room", "unassigned")
cfg_path.write_text(json.dumps(cfg, indent=2) + "\\n", encoding="utf-8")
PY

chown "$SERVICE_USER":"$SERVICE_USER" "$CONFIG_PATH"
chmod 640 "$CONFIG_PATH"

log "Writing environment file: $ENV_FILE"
cat > "$ENV_FILE" <<EOF
SAT_CONFIG_PATH=$CONFIG_PATH
SAT_VENV_DIR=$INSTALL_DIR/sat_venv
SAT_GIT_DIR=$INSTALL_DIR
SAT_GIT_BRANCH=$BRANCH
SAT_SERVICE_USER=$SERVICE_USER
SAT_UPDATE_SCRIPT=$INSTALL_DIR/satellites/scripts/update_satellite.sh
SAT_IDENTITY_PATH=$IDENTITY_PATH
SAT_MQTT_BROKER=$MQTT_BROKER
SAT_MQTT_PORT=$MQTT_PORT
SAT_UPDATE_TOKEN=$UPDATE_TOKEN
SAT_UPDATE_TOPIC=home/satellites/all/update
SAT_UPDATE_TOPIC_PREFIX=home/satellites
EOF
chmod 600 "$ENV_FILE"

render_service() {
	local src="$1"
	local dst="$2"
	sed \
		-e "s|__ENV_FILE__|$ENV_FILE|g" \
		-e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
		-e "s|__SERVICE_USER__|$SERVICE_USER|g" \
		"$src" > "$dst"
}

log "Installing systemd units"
render_service \
	"$INSTALL_DIR/satellites/systemd/home-satellite.service.tmpl" \
	"/etc/systemd/system/home-satellite.service"
render_service \
	"$INSTALL_DIR/satellites/systemd/home-satellite-updater.service.tmpl" \
	"/etc/systemd/system/home-satellite-updater.service"

chmod 644 /etc/systemd/system/home-satellite.service /etc/systemd/system/home-satellite-updater.service

log "Ensuring runtime permissions for service user"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

log "Bootstrapping satellite runtime (without apt)"
if command -v sudo >/dev/null 2>&1; then
	sudo -u "$SERVICE_USER" env \
		SAT_VENV_DIR="$INSTALL_DIR/sat_venv" \
		SAT_CONFIG_PATH="$CONFIG_PATH" \
		"$INSTALL_DIR/satellites/satellite_bootstrap.sh" --skip-apt
else
	runuser -u "$SERVICE_USER" -- env \
		SAT_VENV_DIR="$INSTALL_DIR/sat_venv" \
		SAT_CONFIG_PATH="$CONFIG_PATH" \
		"$INSTALL_DIR/satellites/satellite_bootstrap.sh" --skip-apt
fi

log "Enabling + starting services"
systemctl daemon-reload
systemctl enable --now home-satellite.service
systemctl enable --now home-satellite-updater.service

log "Provisioning complete."
log "Runtime status: systemctl status home-satellite.service --no-pager"
log "Updater status: systemctl status home-satellite-updater.service --no-pager"

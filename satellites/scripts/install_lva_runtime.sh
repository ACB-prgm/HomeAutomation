#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SAT_LVA_REPO_URL:-https://github.com/OHF-Voice/linux-voice-assistant.git}"
REF="${SAT_LVA_REF:-main}"
INSTALL_DIR="${SAT_LVA_DIR:-/opt/homeautomation/linux-voice-assistant}"
VENV_DIR="${SAT_LVA_VENV_DIR:-$INSTALL_DIR/.venv}"
SERVICE_USER="${SAT_SERVICE_USER:-${SUDO_USER:-$USER}}"
SKIP_APT=0

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Install or update Linux Voice Assistant runtime on Raspberry Pi/Linux.

Options:
  --repo-url <url>       Linux Voice Assistant git repo URL (default: $REPO_URL)
  --ref <name|sha>       Git ref/branch/tag/commit to checkout (default: $REF)
  --install-dir <path>   Target checkout path (default: $INSTALL_DIR)
  --venv <path>          Python virtualenv path (default: $VENV_DIR)
  --service-user <name>  User owning runtime files (default: $SERVICE_USER)
  --skip-apt             Skip apt dependency installation
  -h, --help             Show help
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo-url)
		REPO_URL="$2"
		shift 2
		;;
	--ref)
		REF="$2"
		shift 2
		;;
	--install-dir)
		INSTALL_DIR="$2"
		shift 2
		;;
	--venv)
		VENV_DIR="$2"
		shift 2
		;;
	--service-user)
		SERVICE_USER="$2"
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
	echo "[install-lva] $*"
}

require_cmd() {
	local cmd="$1"
	if ! command -v "$cmd" >/dev/null 2>&1; then
		echo "Missing required command: $cmd" >&2
		exit 1
	fi
}

install_apt_deps() {
	if [[ "$SKIP_APT" -eq 1 ]]; then
		log "Skipping apt dependency installation."
		return
	fi

	if [[ ! -f /etc/debian_version ]]; then
		log "Non-Debian system detected. Skipping apt dependency installation."
		return
	fi

	if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
		log "Not running as root; skipping apt dependency installation."
		return
	fi

	log "Installing Linux Voice Assistant OS dependencies"
	apt-get update
	apt-get install -y \
		build-essential \
		git \
		python3 \
		python3-venv \
		python3-dev \
		pkg-config \
		libportaudio2 \
		portaudio19-dev \
		libmpv2 \
		libpulse0 \
		libasound2-plugins \
		pulseaudio
}

sync_checkout() {
	mkdir -p "$(dirname "$INSTALL_DIR")"
	if [[ ! -d "$INSTALL_DIR/.git" ]]; then
		log "Cloning Linux Voice Assistant repository"
		git clone "$REPO_URL" "$INSTALL_DIR"
	fi

	log "Updating Linux Voice Assistant checkout"
	git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
	git -C "$INSTALL_DIR" fetch --all --tags --prune
	git -C "$INSTALL_DIR" checkout "$REF"
	if git -C "$INSTALL_DIR" show-ref --verify --quiet "refs/remotes/origin/$REF"; then
		git -C "$INSTALL_DIR" reset --hard "origin/$REF"
	fi
}

install_python_deps() {
	require_cmd python3
	log "Preparing virtualenv at $VENV_DIR"
	python3 -m venv "$VENV_DIR"
	"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
	"$VENV_DIR/bin/pip" install -e "$INSTALL_DIR"

	# Validate the module import so service startup failures are caught early.
	"$VENV_DIR/bin/python" - <<'PY'
import importlib
importlib.import_module("linux_voice_assistant")
print("linux_voice_assistant module import ok")
PY
}

fix_permissions() {
	if [[ "${EUID:-$(id -u)}" -eq 0 ]] && id "$SERVICE_USER" >/dev/null 2>&1; then
		log "Setting ownership for $SERVICE_USER"
		chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR" "$VENV_DIR"
	fi
}

require_cmd git
install_apt_deps
sync_checkout
install_python_deps
fix_permissions
log "Linux Voice Assistant runtime is ready."

#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/default/home-satellite}"
if [[ -f "$ENV_FILE" ]]; then
	# shellcheck disable=SC1090
	source "$ENV_FILE"
fi

GIT_DIR="${SAT_GIT_DIR:-/opt/homeautomation}"
SAT_SERVICE="${SAT_SERVICE_NAME:-home-satellite.service}"
SERVICE_USER="${SAT_SERVICE_USER:-pi}"
LOCK_FILE="${SAT_UPDATE_LOCK_FILE:-/tmp/home-satellite-update.lock}"
BRANCH_DEFAULT="${SAT_GIT_BRANCH:-codex/ai-dev}"
RUNTIME_MODE="${SAT_RUNTIME_MODE:-custom}"
CONFIG_PATH="${SAT_CONFIG_PATH:-$GIT_DIR/satellites/config/satellite.json}"
VENV_DIR="${SAT_VENV_DIR:-$GIT_DIR/sat_venv}"
RESPEAKER_TOOLS_DIR="${SAT_RESPEAKER_TOOLS_DIR:-$GIT_DIR/satellites/tools/respeaker_xvf3800/host_control/rpi_64bit}"
WAKEWORDS_FILE="${SAT_WAKEWORDS_FILE:-$GIT_DIR/satellites/config/wakewords.txt}"
LVA_REPO_URL="${SAT_LVA_REPO_URL:-https://github.com/OHF-Voice/linux-voice-assistant.git}"
LVA_REF="${SAT_LVA_REF:-main}"
LVA_DIR="${SAT_LVA_DIR:-$GIT_DIR/linux-voice-assistant}"
LVA_VENV_DIR="${SAT_LVA_VENV_DIR:-$LVA_DIR/.venv}"
UPDATE_TARGET=""
DRY_RUN=0

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Safely update the satellite checkout and restart home-satellite service.

Options:
  --target <branch:name|commit:sha>  Update target (default: branch from env)
  --dry-run                           Print steps without applying changes
  -h, --help                          Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--target)
		UPDATE_TARGET="$2"
		shift 2
		;;
	--dry-run)
		DRY_RUN=1
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
	echo "[sat-update] $*"
}

run_cmd() {
	if [[ "$DRY_RUN" -eq 1 ]]; then
		echo "[dry-run] $*"
		return
	fi
	"$@"
}

run_as_service_user() {
	if [[ "$DRY_RUN" -eq 1 ]]; then
		echo "[dry-run as $SERVICE_USER] $*"
		return
	fi
	if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
		if command -v sudo >/dev/null 2>&1; then
			sudo -u "$SERVICE_USER" "$@"
		else
			runuser -u "$SERVICE_USER" -- "$@"
		fi
	else
		"$@"
	fi
}

if [[ "$RUNTIME_MODE" != "custom" && "$RUNTIME_MODE" != "lva" ]]; then
	echo "Invalid SAT_RUNTIME_MODE='$RUNTIME_MODE' (expected custom|lva)." >&2
	exit 1
fi

if [[ ! -d "$GIT_DIR/.git" ]]; then
	echo "Git checkout not found: $GIT_DIR" >&2
	exit 1
fi

mkdir -p "$(dirname "$LOCK_FILE")"
LOCK_DIR_FALLBACK="${LOCK_FILE}.d"
if command -v flock >/dev/null 2>&1; then
	exec 9>"$LOCK_FILE"
	if ! flock -n 9; then
		echo "Another update is in progress (lock: $LOCK_FILE)" >&2
		exit 1
	fi
else
	if ! mkdir "$LOCK_DIR_FALLBACK" 2>/dev/null; then
		echo "Another update is in progress (lock: $LOCK_DIR_FALLBACK)" >&2
		exit 1
	fi
	trap 'rmdir "$LOCK_DIR_FALLBACK" 2>/dev/null || true' EXIT
fi

TARGET_KIND="branch"
TARGET_VALUE="$BRANCH_DEFAULT"

if [[ -n "$UPDATE_TARGET" ]]; then
	if [[ "$UPDATE_TARGET" == branch:* ]]; then
		TARGET_KIND="branch"
		TARGET_VALUE="${UPDATE_TARGET#branch:}"
	elif [[ "$UPDATE_TARGET" == commit:* ]]; then
		TARGET_KIND="commit"
		TARGET_VALUE="${UPDATE_TARGET#commit:}"
	else
		echo "Invalid --target value: $UPDATE_TARGET" >&2
		exit 1
	fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
	PREV_REV="$(git -C "$GIT_DIR" rev-parse HEAD)"
else
	PREV_REV="$(run_as_service_user git -C "$GIT_DIR" rev-parse HEAD)"
fi

ROLLBACK_NEEDED=0

rollback() {
	local rc="$1"
	if [[ "$ROLLBACK_NEEDED" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
		log "Rolling back to previous revision: $PREV_REV"
		run_as_service_user git -C "$GIT_DIR" checkout -f "$PREV_REV" || true
		systemctl start "$SAT_SERVICE" || true
	fi
	exit "$rc"
}

trap 'rollback $?' ERR

log "Stopping $SAT_SERVICE"
run_cmd systemctl stop "$SAT_SERVICE"

log "Fetching repository state"
run_as_service_user git -C "$GIT_DIR" fetch --all --prune
run_as_service_user git -C "$GIT_DIR" sparse-checkout init --cone
run_as_service_user git -C "$GIT_DIR" sparse-checkout set satellites

if [[ "$TARGET_KIND" == "branch" ]]; then
	log "Updating to branch: $TARGET_VALUE"
	run_as_service_user git -C "$GIT_DIR" checkout -B "$TARGET_VALUE" "origin/$TARGET_VALUE"
else
	log "Updating to commit: $TARGET_VALUE"
	run_as_service_user git -C "$GIT_DIR" checkout -f "$TARGET_VALUE"
fi

ROLLBACK_NEEDED=1

if [[ "${EUID:-$(id -u)}" -eq 0 ]] && [[ -x "$GIT_DIR/satellites/scripts/install_respeaker_udev.sh" ]]; then
	log "Ensuring ReSpeaker udev permissions"
	run_cmd "$GIT_DIR/satellites/scripts/install_respeaker_udev.sh"
fi

BOOTSTRAP_ARGS=(--skip-apt)
if [[ "$RUNTIME_MODE" == "lva" ]]; then
	BOOTSTRAP_ARGS+=(--skip-models)
fi

log "Running bootstrap (${BOOTSTRAP_ARGS[*]})"
run_as_service_user env \
	SAT_CONFIG_PATH="$CONFIG_PATH" \
	SAT_VENV_DIR="$VENV_DIR" \
	SAT_RESPEAKER_TOOLS_DIR="$RESPEAKER_TOOLS_DIR" \
	"$GIT_DIR/satellites/satellite_bootstrap.sh" "${BOOTSTRAP_ARGS[@]}"

if [[ "$RUNTIME_MODE" == "custom" && -f "$WAKEWORDS_FILE" ]]; then
	log "Applying wakewords from: $WAKEWORDS_FILE"
	run_as_service_user env \
		SAT_VENV_DIR="$VENV_DIR" \
		SAT_WAKEWORDS_FILE="$WAKEWORDS_FILE" \
		"$GIT_DIR/satellites/scripts/set_wakewords.sh" --file "$WAKEWORDS_FILE"
elif [[ "$RUNTIME_MODE" == "custom" ]]; then
	log "No wakewords file found at $WAKEWORDS_FILE; skipping wakeword apply."
fi

if [[ "$RUNTIME_MODE" == "lva" ]] && [[ -x "$GIT_DIR/satellites/scripts/install_lva_runtime.sh" ]]; then
	log "Ensuring Linux Voice Assistant runtime is installed"
	run_as_service_user env \
		SAT_SERVICE_USER="$SERVICE_USER" \
		SAT_LVA_REPO_URL="$LVA_REPO_URL" \
		SAT_LVA_REF="$LVA_REF" \
		SAT_LVA_DIR="$LVA_DIR" \
		SAT_LVA_VENV_DIR="$LVA_VENV_DIR" \
		"$GIT_DIR/satellites/scripts/install_lva_runtime.sh" \
			--repo-url "$LVA_REPO_URL" \
			--ref "$LVA_REF" \
			--install-dir "$LVA_DIR" \
			--venv "$LVA_VENV_DIR" \
			--service-user "$SERVICE_USER" \
			--skip-apt
fi

if [[ -x "$GIT_DIR/satellites/scripts/respeaker_configure.sh" ]]; then
	log "Applying ReSpeaker runtime configuration"
	run_as_service_user env \
		SAT_CONFIG_PATH="$CONFIG_PATH" \
		SAT_VENV_DIR="$VENV_DIR" \
		SAT_RESPEAKER_TOOLS_DIR="$RESPEAKER_TOOLS_DIR" \
		"$GIT_DIR/satellites/scripts/respeaker_configure.sh"
fi

log "Starting $SAT_SERVICE"
run_cmd systemctl start "$SAT_SERVICE"

ROLLBACK_NEEDED=0
log "Update successful (runtime mode: $RUNTIME_MODE)."

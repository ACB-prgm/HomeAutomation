#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SAT_DIR/.." && pwd)"

CONFIG_PATH="${SAT_CONFIG_PATH:-$SAT_DIR/config/satellite.json}"
LVA_DIR="${SAT_LVA_DIR:-$REPO_ROOT/linux-voice-assistant}"
LVA_VENV_DIR="${SAT_LVA_VENV_DIR:-$LVA_DIR/.venv}"
LVA_PYTHON="$LVA_VENV_DIR/bin/python"

SATELLITE_NAME_OVERRIDE=""
WAKE_MODEL="${SAT_LVA_WAKE_MODEL:-okay_nabu}"
STOP_WORD_MODEL="${SAT_LVA_STOP_WORD_MODEL:-}"
HOST_OVERRIDE="${SAT_LVA_HOST:-}"
PORT_OVERRIDE="${SAT_LVA_PORT:-}"
NETWORK_INTERFACE="${SAT_LVA_NETWORK_INTERFACE:-}"
AUTO_INSTALL=1

usage() {
	cat <<EOF
Usage: $(basename "$0") [options] [-- extra-lva-args]

Launch Linux Voice Assistant using satellite config defaults.

Options:
  --config <path>        Config file path (default: $CONFIG_PATH)
  --lva-dir <path>       LVA checkout directory (default: $LVA_DIR)
  --venv <path>          LVA virtualenv path (default: $LVA_VENV_DIR)
  --name <value>         Override satellite name
  --wake-model <value>   Wake model name (default: $WAKE_MODEL)
  --stop-model <value>   Stop word model name (default: disabled)
  --host <value>         Override advertised host/IP
  --port <value>         Override ESPHome port
  --interface <value>    Override network interface
  --no-install           Do not auto-run install_lva_runtime.sh when missing
  -h, --help             Show help
EOF
}

EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
	--config)
		CONFIG_PATH="$2"
		shift 2
		;;
	--lva-dir)
		LVA_DIR="$2"
		shift 2
		;;
	--venv)
		LVA_VENV_DIR="$2"
		shift 2
		;;
	--name)
		SATELLITE_NAME_OVERRIDE="$2"
		shift 2
		;;
	--wake-model)
		WAKE_MODEL="$2"
		shift 2
		;;
	--stop-model)
		STOP_WORD_MODEL="$2"
		shift 2
		;;
	--host)
		HOST_OVERRIDE="$2"
		shift 2
		;;
	--port)
		PORT_OVERRIDE="$2"
		shift 2
		;;
	--interface)
		NETWORK_INTERFACE="$2"
		shift 2
		;;
	--no-install)
		AUTO_INSTALL=0
		shift
		;;
	--)
		shift
		EXTRA_ARGS+=("$@")
		break
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

LVA_PYTHON="$LVA_VENV_DIR/bin/python"

check_lva_install() {
	if [[ ! -x "$LVA_PYTHON" ]]; then
		return 1
	fi
	"$LVA_PYTHON" - <<'PY' >/dev/null 2>&1
import importlib
importlib.import_module("linux_voice_assistant")
PY
}

ensure_pulseaudio() {
	if ! command -v pulseaudio >/dev/null 2>&1; then
		return
	fi
	if pulseaudio --check >/dev/null 2>&1; then
		return
	fi
	# Linux Voice Assistant's soundcard backend expects a running PulseAudio daemon.
	pulseaudio --start >/dev/null 2>&1 || true
}

if ! check_lva_install; then
	if [[ "$AUTO_INSTALL" -eq 0 ]]; then
		echo "LVA runtime missing under $LVA_VENV_DIR and auto-install disabled." >&2
		exit 1
	fi
	"$SAT_DIR/scripts/install_lva_runtime.sh" \
		--install-dir "$LVA_DIR" \
		--venv "$LVA_VENV_DIR" \
		--skip-apt
	if ! check_lva_install; then
		echo "LVA install attempted but runtime is still unavailable." >&2
		exit 1
	fi
fi

ensure_pulseaudio

if [[ ! -f "$CONFIG_PATH" ]]; then
	echo "Config not found at $CONFIG_PATH. It will be auto-created by the custom runtime path." >&2
fi

CONFIG_TSV="$("$LVA_PYTHON" - <<PY
import json
from pathlib import Path

cfg_path = Path(r"""$CONFIG_PATH""")
name = "Home Satellite"
audio_input = ""
audio_output = ""

if cfg_path.exists():
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    ident = data.get("identity", {}) or {}
    audio = data.get("audio", {}) or {}
    name = str(ident.get("friendly_name", name))
    in_dev = audio.get("input_device")
    out_dev = audio.get("output_device")
    if in_dev is not None:
        audio_input = str(in_dev)
    if out_dev is not None:
        audio_output = str(out_dev)

print(name)
print(audio_input)
print(audio_output)
PY
)"

SATELLITE_NAME="$(echo "$CONFIG_TSV" | sed -n '1p')"
AUDIO_INPUT_DEVICE="$(echo "$CONFIG_TSV" | sed -n '2p')"
AUDIO_OUTPUT_DEVICE="$(echo "$CONFIG_TSV" | sed -n '3p')"

if [[ -n "$SATELLITE_NAME_OVERRIDE" ]]; then
	SATELLITE_NAME="$SATELLITE_NAME_OVERRIDE"
fi

CMD=("$LVA_PYTHON" -m linux_voice_assistant --name "$SATELLITE_NAME")

if [[ -n "$AUDIO_INPUT_DEVICE" ]]; then
	CMD+=(--audio-input-device "$AUDIO_INPUT_DEVICE")
fi
if [[ -n "$AUDIO_OUTPUT_DEVICE" ]]; then
	CMD+=(--audio-output-device "$AUDIO_OUTPUT_DEVICE")
fi
if [[ -n "$WAKE_MODEL" ]]; then
	CMD+=(--wake-model "$WAKE_MODEL")
fi
if [[ -n "$STOP_WORD_MODEL" ]]; then
	CMD+=(--stop-model "$STOP_WORD_MODEL")
fi
if [[ -n "$HOST_OVERRIDE" ]]; then
	CMD+=(--host "$HOST_OVERRIDE")
fi
if [[ -n "$PORT_OVERRIDE" ]]; then
	CMD+=(--port "$PORT_OVERRIDE")
fi
if [[ -n "$NETWORK_INTERFACE" ]]; then
	CMD+=(--network-interface "$NETWORK_INTERFACE")
fi
if [[ "${SAT_LVA_DEBUG:-0}" == "1" ]]; then
	CMD+=(--debug)
fi

CMD+=("${EXTRA_ARGS[@]}")
exec "${CMD[@]}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "$SAT_DIR/.." && pwd)"
VENV_DIR="${SAT_VENV_DIR:-$REPO_ROOT/sat_venv}"
CONFIG_PATH="${SAT_CONFIG_PATH:-$SAT_DIR/config/satellite.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

SKIP_APT=0
SKIP_PYTHON=0
SKIP_MODELS=0
FORCE_MODELS=0

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Bootstrap the satellite runtime for Raspberry Pi:
- installs OS dependencies (Debian/Ubuntu)
- creates/updates a Python virtual environment
- installs Python dependencies from sat_requirements.txt
- downloads wakeword and VAD model assets

Options:
  --skip-apt        Skip apt package installation
  --skip-python     Skip virtualenv and pip installation
  --skip-models     Skip model downloads
  --force-models    Re-download and overwrite model assets
  -h, --help        Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--skip-apt)
		SKIP_APT=1
		shift
		;;
	--skip-python)
		SKIP_PYTHON=1
		shift
		;;
	--skip-models)
		SKIP_MODELS=1
		shift
		;;
	--force-models)
		FORCE_MODELS=1
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
	echo "[sat-bootstrap] $*"
}

require_cmd() {
	local cmd="$1"
	if ! command -v "$cmd" >/dev/null 2>&1; then
		echo "Missing required command: $cmd" >&2
		exit 1
	fi
}

download() {
	local url="$1"
	local output="$2"

	if command -v curl >/dev/null 2>&1; then
		curl -L --fail -o "$output" "$url"
	elif command -v wget >/dev/null 2>&1; then
		wget -O "$output" "$url"
	else
		echo "Neither curl nor wget is installed." >&2
		exit 1
	fi
}

extract_rename() {
	local filename="$1"
	local target_dir="$2"

	local roots
	roots="$(
		tar -tjf "$filename" \
			| sed 's|^\./||' \
			| cut -d/ -f1 \
			| sort -u
	)"

	tar -xjf "$filename"

	local root_count
	root_count="$(echo "$roots" | wc -l | tr -d ' ')"

	if [[ "$root_count" -eq 1 && -d "$roots" ]]; then
		rm -rf "$target_dir"
		mv "$roots" "$target_dir"
	else
		rm -rf "$target_dir"
		mkdir -p "$target_dir"
		for item in $roots; do
			[[ -e "$item" ]] && mv "$item" "$target_dir/"
		done
	fi

	rm -f "$filename"
	if [[ -d "$target_dir/test_wavs" ]]; then
		rm -rf "$target_dir/test_wavs"
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

	require_cmd apt-get
	local packages=(
		build-essential
		python3-venv
		python3-dev
		python3-pip
		portaudio19-dev
		libportaudio2
		libsndfile1
		curl
		ca-certificates
	)
	if apt-cache show libatlas-base-dev >/dev/null 2>&1; then
		packages+=(libatlas-base-dev)
	fi

	log "Installing apt packages: ${packages[*]}"
	if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
		apt-get update
		apt-get install -y "${packages[@]}"
	else
		sudo apt-get update
		sudo apt-get install -y "${packages[@]}"
	fi
}

install_python_deps() {
	if [[ "$SKIP_PYTHON" -eq 1 ]]; then
		log "Skipping virtualenv and pip installation."
		return
	fi

	require_cmd "$PYTHON_BIN"
	log "Using Python: $PYTHON_BIN"

	if [[ ! -x "$VENV_DIR/bin/python" ]]; then
		log "Creating virtualenv at $VENV_DIR"
		"$PYTHON_BIN" -m venv "$VENV_DIR"
	fi

	log "Installing Python dependencies in $VENV_DIR"
	"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
	"$VENV_DIR/bin/pip" install -r "$SAT_DIR/sat_requirements.txt"
}

install_models() {
	if [[ "$SKIP_MODELS" -eq 1 ]]; then
		log "Skipping model download."
		return
	fi

	local model_dir="$SAT_DIR/speech/models"
	local wakeword_dir="$model_dir/wakeword"
	local kws_archive="sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2"
	local kws_url="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/${kws_archive}"
	local vad_file="vad.int8.onnx"
	local vad_url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.int8.onnx"

	mkdir -p "$model_dir"
	pushd "$model_dir" >/dev/null

	if [[ "$FORCE_MODELS" -eq 1 || ! -f "$wakeword_dir/encoder-epoch-12-avg-2-chunk-16-left-64.onnx" ]]; then
		log "Downloading wakeword model bundle"
		download "$kws_url" "$kws_archive"
		extract_rename "$kws_archive" "wakeword"
	else
		log "Wakeword model already present."
	fi

	if [[ "$FORCE_MODELS" -eq 1 || ! -f "$vad_file" ]]; then
		log "Downloading VAD model"
		download "$vad_url" "silero_vad.int8.onnx"
		mv -f "silero_vad.int8.onnx" "$vad_file"
	else
		log "VAD model already present."
	fi

	# Keep wakeword keyword files in the path expected by wakeword.py.
	local kws_dir="$model_dir/wakeword_keywords"
	mkdir -p "$kws_dir"
	if [[ -f "$wakeword_dir/keywords_raw.txt" ]]; then
		cp -f "$wakeword_dir/keywords_raw.txt" "$kws_dir/keywords_raw.txt"
	fi
	if [[ -f "$wakeword_dir/keywords.txt" ]]; then
		cp -f "$wakeword_dir/keywords.txt" "$kws_dir/keywords.txt"
	fi

	popd >/dev/null
}

ensure_default_config() {
	if [[ -f "$CONFIG_PATH" ]]; then
		log "Config exists: $CONFIG_PATH"
		return
	fi

	local python_for_config="$VENV_DIR/bin/python"
	if [[ ! -x "$python_for_config" ]]; then
		require_cmd "$PYTHON_BIN"
		python_for_config="$PYTHON_BIN"
	fi

	log "Config missing. Creating default config at $CONFIG_PATH"
	"$python_for_config" - <<PY
from pathlib import Path
import json

cfg = Path("${CONFIG_PATH}").expanduser().resolve()
cfg.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "identity": {"friendly_name": "Home Satellite", "path": "../identity.json", "room": "unassigned"},
    "audio": {"sample_rate": 16000, "channels": 1, "block_size": 512, "input_device": None, "output_device": None, "volume": 0.8},
    "vad": {"mode": "sherpa", "threshold": 0.25, "min_silence_duration": 0.5, "min_speech_duration": 0.01, "max_utterance_s": 10.0},
    "speech": {"debug": True},
    "runtime": {"log_level": "INFO", "reconnect_min_s": 1.0, "reconnect_max_s": 30.0},
}
with cfg.open("w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\\n")
print(cfg)
PY
}

log "Starting satellite bootstrap"
install_apt_deps
install_python_deps
install_models
ensure_default_config
log "Bootstrap complete."
log "Run the satellite with: $SAT_DIR/scripts/run_satellite.sh"

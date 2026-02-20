#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SAT_DIR/.." && pwd)"
VENV_DIR="${SAT_VENV_DIR:-$REPO_ROOT/sat_venv}"
CONFIG_PATH="${SAT_CONFIG_PATH:-$SAT_DIR/config/satellite.json}"
AUTO_BOOTSTRAP=1

usage() {
	cat <<EOF
Usage: $(basename "$0") [options] [-- extra-main-args]

Launches the satellite runtime using the satellite virtualenv.

Options:
  --config <path>   Config file path (default: $CONFIG_PATH)
  --venv <path>     Virtualenv directory (default: $VENV_DIR)
  --no-bootstrap    Do not auto-run satellite_bootstrap.sh when deps are missing
  -h, --help        Show this help text
EOF
}

EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
	--config)
		CONFIG_PATH="$2"
		shift 2
		;;
	--venv)
		VENV_DIR="$2"
		shift 2
		;;
	--no-bootstrap)
		AUTO_BOOTSTRAP=0
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

PYTHON="$VENV_DIR/bin/python"

check_python_deps() {
	"$PYTHON" - <<'PY'
import importlib
import sys

required = [
    "numpy",
    "sounddevice",
    "soundfile",
    "paho.mqtt.client",
    "sherpa_onnx",
]

missing = []
for mod in required:
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(mod)

if missing:
    print("Missing Python modules:", ", ".join(missing))
    sys.exit(1)
PY
}

check_models() {
	local models_dir="$SAT_DIR/speech/models"
	local required=(
		"$models_dir/vad.int8.onnx"
		"$models_dir/wakeword/encoder-epoch-12-avg-2-chunk-16-left-64.onnx"
		"$models_dir/wakeword/decoder-epoch-12-avg-2-chunk-16-left-64.onnx"
		"$models_dir/wakeword/joiner-epoch-12-avg-2-chunk-16-left-64.onnx"
		"$models_dir/wakeword/tokens.txt"
	)
	local missing=0
	for file in "${required[@]}"; do
		if [[ ! -f "$file" ]]; then
			echo "Missing model file: $file"
			missing=1
		fi
	done
	return $missing
}

NEED_VENV=0
NEED_PY_DEPS=0
NEED_MODELS=0

if [[ ! -x "$PYTHON" ]]; then
	NEED_VENV=1
else
	if ! check_python_deps; then
		NEED_PY_DEPS=1
	fi
fi

if ! check_models; then
	NEED_MODELS=1
fi

if [[ "$NEED_VENV" -eq 1 || "$NEED_PY_DEPS" -eq 1 || "$NEED_MODELS" -eq 1 ]]; then
	if [[ "$AUTO_BOOTSTRAP" -eq 0 ]]; then
		echo "Satellite preflight failed and auto-bootstrap is disabled." >&2
		echo "Run $SAT_DIR/satellite_bootstrap.sh then retry." >&2
		exit 1
	fi

	BOOTSTRAP_ARGS=()
	if [[ "$NEED_VENV" -eq 0 ]]; then
		BOOTSTRAP_ARGS+=(--skip-apt)
	fi
	if [[ "$NEED_PY_DEPS" -eq 0 && "$NEED_VENV" -eq 0 ]]; then
		BOOTSTRAP_ARGS+=(--skip-python)
	fi
	if [[ "$NEED_MODELS" -eq 0 ]]; then
		BOOTSTRAP_ARGS+=(--skip-models)
	fi

	echo "Preflight failed. Running bootstrap: $SAT_DIR/satellite_bootstrap.sh ${BOOTSTRAP_ARGS[*]}"
	"$SAT_DIR/satellite_bootstrap.sh" "${BOOTSTRAP_ARGS[@]}"
	PYTHON="$VENV_DIR/bin/python"

	if [[ ! -x "$PYTHON" ]] || ! check_python_deps || ! check_models; then
		echo "Bootstrap completed, but dependencies are still incomplete." >&2
		exit 1
	fi
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
	echo "Config not found at $CONFIG_PATH. It will be auto-created on startup."
fi

exec "$PYTHON" "$SAT_DIR/main.py" --config "$CONFIG_PATH" "${EXTRA_ARGS[@]}"

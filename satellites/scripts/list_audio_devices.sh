#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SAT_DIR/.." && pwd)"
VENV_DIR="${SAT_VENV_DIR:-$REPO_ROOT/sat_venv}"
PYTHON="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON" ]]; then
	echo "Virtualenv python not found at: $PYTHON" >&2
	echo "Run $SAT_DIR/satellite_bootstrap.sh first." >&2
	exit 1
fi

"$PYTHON" - <<'PY'
import sounddevice as sd

devices = sd.query_devices()
defaults = sd.default.device

print("Default input index:", defaults[0])
print("Default output index:", defaults[1])
print("")
print("Index | In | Out | Name")
print("------+----+-----+---------------------------------------------------------")
for idx, dev in enumerate(devices):
    in_ch = int(dev.get("max_input_channels", 0))
    out_ch = int(dev.get("max_output_channels", 0))
    name = dev.get("name", "").strip()
    print(f"{idx:5} | {in_ch:2} | {out_ch:3} | {name}")
PY

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="${SAT_RESPEAKER_TOOLS_DIR:-$SAT_DIR/tools/respeaker_xvf3800/host_control/rpi_64bit}"
XVF_HOST="$TOOLS_DIR/xvf_host"

if [[ ! -x "$XVF_HOST" ]]; then
	echo "[respeaker-led] xvf_host not found at $XVF_HOST; skipping."
	exit 0
fi

# Ignore failures so missing device at boot does not fail the service.
"$XVF_HOST" LED_EFFECT 0 >/dev/null 2>&1 || true
"$XVF_HOST" GPO_WRITE_VALUE 33 0 >/dev/null 2>&1 || true

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SAT_DIR/.." && pwd)"
VENV_DIR="${SAT_VENV_DIR:-$REPO_ROOT/sat_venv}"
CONFIG_PATH="${SAT_CONFIG_PATH:-$SAT_DIR/config/satellite.json}"
TOOLS_DIR="${SAT_RESPEAKER_TOOLS_DIR:-$SAT_DIR/tools/respeaker_xvf3800/host_control/rpi_64bit}"

if [[ -x "$VENV_DIR/bin/python" ]]; then
	PYTHON_BIN="$VENV_DIR/bin/python"
else
	PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
	echo "[respeaker-config] python not found: $PYTHON_BIN" >&2
	exit 0
fi

cd "$SAT_DIR"

SAT_CONFIG_PATH="$CONFIG_PATH" SAT_RESPEAKER_TOOLS_DIR="$TOOLS_DIR" "$PYTHON_BIN" - <<'PY'
import logging
import os

from speech.respeaker_xvf3800 import ReSpeakerLedController, ReSpeakerXVF3800Control
from utils.config import ConfigManager

logging.basicConfig(level=logging.INFO, format="[respeaker-config] %(message)s")
log = logging.getLogger("respeaker-config")

config_path = os.environ.get("SAT_CONFIG_PATH")
tools_dir = os.environ.get("SAT_RESPEAKER_TOOLS_DIR")

cfg = ConfigManager(path=config_path).load(create_if_missing=True)
if not cfg.respeaker.enabled:
	log.info("ReSpeaker integration disabled in config; skipping.")
	raise SystemExit(0)

try:
	control = ReSpeakerXVF3800Control(
		backend=cfg.respeaker.control_backend,
		tools_dir=tools_dir,
	)
except Exception as exc:
	log.warning("ReSpeaker control unavailable: %s", exc)
	raise SystemExit(0)

if not control.available:
	log.warning("ReSpeaker control backend not available; skipping.")
	raise SystemExit(0)

try:
	control.configure_audio_route(cfg.respeaker.channel_strategy)
	log.info("Configured channel strategy: %s", cfg.respeaker.channel_strategy)
except Exception as exc:
	log.warning("Failed to configure channel strategy: %s", exc)

leds = ReSpeakerLedController(
	control=control,
	enabled=cfg.respeaker.led_enabled,
	listening_effect=cfg.respeaker.led_listening_effect,
	listening_color=cfg.respeaker.led_listening_color,
	idle_effect=cfg.respeaker.led_idle_effect,
)

if cfg.respeaker.led_enabled:
	leds.set_idle()
	log.info("Applied LED idle state: %s", leds.state)
else:
	control.set_led_off()
	log.info("LED disabled; forced off.")
PY

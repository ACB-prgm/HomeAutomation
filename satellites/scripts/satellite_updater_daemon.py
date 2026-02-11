#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt


def _env(name: str, default: str) -> str:
	return os.environ.get(name, default).strip()


BROKER = _env("SAT_MQTT_BROKER", "127.0.0.1")
PORT = int(_env("SAT_MQTT_PORT", "1883"))
USERNAME = _env("SAT_MQTT_USERNAME", "")
PASSWORD = _env("SAT_MQTT_PASSWORD", "")
TOKEN = _env("SAT_UPDATE_TOKEN", "change-me")
TOPIC_ALL = _env("SAT_UPDATE_TOPIC", "home/satellites/all/update")
TOPIC_PREFIX = _env("SAT_UPDATE_TOPIC_PREFIX", "home/satellites")
IDENTITY_PATH = Path(_env("SAT_IDENTITY_PATH", "/var/lib/satellite/identity.json"))
UPDATE_SCRIPT = _env("SAT_UPDATE_SCRIPT", "/opt/homeautomation/satellites/scripts/update_satellite.sh")
DEFAULT_BRANCH = _env("SAT_GIT_BRANCH", "codex/ai-dev")

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s %(levelname)s sat-updater %(message)s",
)
LOG = logging.getLogger("sat-updater")
_update_lock = threading.Lock()


def _load_satellite_id() -> str | None:
	try:
		data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
		sat_id = data.get("satellite_id")
		if sat_id:
			return str(sat_id)
	except Exception:
		return None
	return None


def _topic_for_satellite(satellite_id: str | None) -> str | None:
	if not satellite_id:
		return None
	return f"{TOPIC_PREFIX}/{satellite_id}/update"


def _parse_payload(raw_payload: bytes) -> dict[str, Any] | None:
	try:
		obj = json.loads(raw_payload.decode("utf-8"))
		if isinstance(obj, dict):
			return obj
	except Exception:
		return None
	return None


def _validate_message(topic: str, payload: dict[str, Any], local_satellite_id: str | None) -> tuple[bool, str]:
	token = str(payload.get("auth_token", ""))
	if token != TOKEN:
		return False, "auth token mismatch"

	target_satellite_id = payload.get("satellite_id")
	if target_satellite_id and local_satellite_id and str(target_satellite_id) not in ("all", local_satellite_id):
		return False, f"payload satellite_id={target_satellite_id} not for this device"

	expected = _topic_for_satellite(local_satellite_id)
	if topic not in (TOPIC_ALL, expected):
		return False, f"unexpected topic {topic}"

	return True, "ok"


def _build_target(payload: dict[str, Any]) -> str:
	target = str(payload.get("target", "")).strip()
	if target:
		if target.startswith("branch:") or target.startswith("commit:"):
			return target
		# If target is plain value, treat as branch.
		return f"branch:{target}"
	return f"branch:{DEFAULT_BRANCH}"


def _run_update(target: str) -> None:
	cmd = [UPDATE_SCRIPT, "--target", target]
	LOG.info("Executing update command: %s", " ".join(cmd))
	subprocess.run(cmd, check=True)


def _on_connect(client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
	LOG.info("Connected to MQTT broker=%s port=%s", BROKER, PORT)
	sat_id = _load_satellite_id()
	client.subscribe(TOPIC_ALL)
	LOG.info("Subscribed: %s", TOPIC_ALL)
	topic_sat = _topic_for_satellite(sat_id)
	if topic_sat:
		client.subscribe(topic_sat)
		LOG.info("Subscribed: %s", topic_sat)
	else:
		LOG.warning("Satellite identity not found yet; only all-satellites topic is active.")


def _on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
	payload = _parse_payload(msg.payload)
	if payload is None:
		LOG.warning("Ignoring non-JSON update payload on topic=%s", msg.topic)
		return

	local_sat_id = _load_satellite_id()
	valid, reason = _validate_message(msg.topic, payload, local_sat_id)
	if not valid:
		LOG.warning("Ignoring update request: %s", reason)
		return

	target = _build_target(payload)
	if not _update_lock.acquire(blocking=False):
		LOG.warning("Update already in progress; ignoring request.")
		return

	try:
		LOG.info("Accepted update request target=%s", target)
		_run_update(target)
		LOG.info("Update finished successfully.")
	except subprocess.CalledProcessError as err:
		LOG.exception("Update script failed with code %s", err.returncode)
	except Exception:
		LOG.exception("Unhandled updater error")
	finally:
		_update_lock.release()


def main() -> None:
	if TOKEN == "change-me":
		LOG.warning("SAT_UPDATE_TOKEN is still default 'change-me'; replace it in /etc/default/home-satellite.")

	client = mqtt.Client(client_id="satellite-updater", callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
	if USERNAME:
		client.username_pw_set(USERNAME, PASSWORD)
	client.on_connect = _on_connect
	client.on_message = _on_message
	client.connect(BROKER, PORT, 60)
	client.loop_forever()


if __name__ == "__main__":
	main()

from __future__ import annotations

import json
import logging
import uuid

import numpy as np

from .runtime_logging import context_extra


class SatelliteController:
	def __init__(self, identity, device_mgr, mqtt, speech, room: str = "unassigned"):
		self.identity = identity
		self.device_mgr = device_mgr
		self.mqtt = mqtt
		self.room = room
		self.logger = logging.getLogger("satellite.controller")
		self._active_session_id: str | None = None
		self._utterance_count = 0

		self.speech = speech
		self.speech._on_utterance_ended = self.handle_utterance
		self.speech._on_wakeword = self.handle_wakeword

	def start(self):
		# self.mqtt.on_command(self.handle_command)
		self.logger.info(
			"Satellite controller started",
			extra=self._ctx(),
		)
		self.speech.start()

	def handle_wakeword(self, evt: dict):
		self._active_session_id = self._new_id()
		self._utterance_count = 0
		evt_summary = json.dumps(evt, sort_keys=True, default=str)
		self.logger.info(
			f"Wakeword detected evt={evt_summary}",
			extra=self._ctx(session_id=self._active_session_id),
		)

	def handle_utterance(self, audio: np.ndarray, reason: str):
		session_id = self._active_session_id or self._new_id()
		self._utterance_count += 1
		pipeline_run_id = f"{session_id}-{self._utterance_count}"

		num_samples = int(audio.size)
		sample_rate = int(getattr(self.speech, "sample_rate", 16000) or 16000)
		duration_s = float(num_samples / sample_rate) if sample_rate > 0 else 0.0
		self.logger.info(
			f"Utterance captured reason={reason} samples={num_samples} duration_s={duration_s:.3f}",
			extra=self._ctx(
				session_id=session_id,
				pipeline_run_id=pipeline_run_id,
			),
		)
		self._active_session_id = None

	def handle_command(self, command):
		command_type = getattr(command, "type", "unknown")
		session_id = self._active_session_id or "-"
		pipeline_run_id = f"{session_id}-{self._utterance_count}" if session_id != "-" else "-"
		self.logger.info(
			f"Received command type={command_type}",
			extra=self._ctx(session_id=session_id, pipeline_run_id=pipeline_run_id),
		)
		if command_type == "set_volume" and self.device_mgr is not None:
			self.device_mgr.audio.set_volume(command.value)
			self.logger.info(
				f"Applied volume change value={command.value}",
				extra=self._ctx(session_id=session_id, pipeline_run_id=pipeline_run_id),
			)

	def _ctx(self, session_id: str | None = None, pipeline_run_id: str | None = None) -> dict[str, str]:
		return context_extra(
			satellite_id=self.identity.satellite_id,
			room=self.room,
			session_id=session_id,
			pipeline_run_id=pipeline_run_id,
		)

	@staticmethod
	def _new_id() -> str:
		return uuid.uuid4().hex[:12]

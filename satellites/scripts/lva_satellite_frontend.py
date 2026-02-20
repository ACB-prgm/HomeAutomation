#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


# Add satellites/ directory to sys.path so local speech/config modules are importable
SAT_DIR = Path(__file__).resolve().parents[1]
if str(SAT_DIR) not in sys.path:
	sys.path.insert(0, str(SAT_DIR))

# pylint: disable=wrong-import-position
from speech.audio import ArecordInput, AudioConfig, AudioInput
from speech.respeaker_xvf3800 import ReSpeakerGate, ReSpeakerLedController, ReSpeakerXVF3800Control
from speech.speech_engine import SpeechEngine
from speech.vad import SherpaVAD
from speech.wakeword import SherpaWakeword, WakewordConfig
from utils.config import ConfigManager
from utils.runtime_logging import configure_logging

import linux_voice_assistant.__main__ as lva_main


LOGGER = logging.getLogger("satellite.lva_frontend")


@dataclass
class _WakeWordEvent:
	wake_word: str


def _resolve_respeaker_alsa_device() -> Optional[str]:
	"""
	Best-effort parse of `arecord -l` for ReSpeaker XVF3800 capture card.
	Returns ALSA device string like hw:2,0.
	"""
	try:
		proc = subprocess.run(
			["arecord", "-l"],
			check=False,
			capture_output=True,
			text=True,
			timeout=2.0,
		)
	except Exception:
		return None
	if proc.returncode != 0:
		return None

	pattern = re.compile(
		r"^card\s+(?P<card>\d+):\s+(?P<label>[^\[]+)\[[^\]]*reSpeaker XVF3800[^\]]*\],\s+device\s+(?P<dev>\d+):",
		re.IGNORECASE,
	)
	for raw in (proc.stdout or "").splitlines():
		line = raw.strip()
		m = pattern.search(line)
		if m:
			return f"hw:{m.group('card')},{m.group('dev')}"
	return None


def _build_speech_engine(config) -> tuple[SpeechEngine, ReSpeakerLedController]:
	channel_select = 0
	if config.respeaker.channel_strategy == "right_asr" and config.audio.channels > 1:
		channel_select = 1

	audio_cfg = AudioConfig(
		channels=config.audio.channels,
		block_size=config.audio.block_size,
		sample_rate=config.audio.sample_rate,
		device=config.audio.input_device,
		channel_select=channel_select,
	)
	audio_in = AudioInput(audio_cfg)
	if config.audio.input_device is None:
		alsa_dev = _resolve_respeaker_alsa_device()
		if alsa_dev:
			# XVF3800 ALSA capture presents as stereo on this Pi image.
			# Capture both channels and down-select in ArecordInput.
			arecord_cfg = AudioConfig(
				channels=max(2, int(config.audio.channels)),
				block_size=config.audio.block_size,
				sample_rate=config.audio.sample_rate,
				device=config.audio.input_device,
				channel_select=channel_select,
			)
			LOGGER.info("Using ALSA arecord capture backend for ReSpeaker: %s", alsa_dev)
			audio_in = ArecordInput(arecord_cfg, alsa_device=alsa_dev)

	vad = SherpaVAD(
		sample_rate=config.audio.sample_rate,
		threshold=config.vad.threshold,
		min_silence_duration=config.vad.min_silence_duration,
		min_speech_duration=config.vad.min_speech_duration,
		max_speech_duration=config.vad.max_utterance_s,
		num_threads=config.speech.vad_threads,
	)

	wakeword = SherpaWakeword(
		cfg=WakewordConfig(
			sample_rate=config.audio.sample_rate,
			num_threads=config.speech.wakeword_threads,
		)
	)

	control = None
	if config.respeaker.enabled:
		try:
			control = ReSpeakerXVF3800Control(
				backend=config.respeaker.control_backend,
				tools_dir=os.environ.get("SAT_RESPEAKER_TOOLS_DIR"),
			)
			control.configure_audio_route(config.respeaker.channel_strategy)
		except Exception as exc:
			LOGGER.warning("ReSpeaker control unavailable: %s", exc)
			control = None

	gate = ReSpeakerGate(
		control=control,
		mode=config.respeaker.gate_mode,
		poll_interval_ms=config.respeaker.poll_interval_ms,
		speech_energy_high=config.respeaker.speech_energy_high,
		speech_energy_low=config.respeaker.speech_energy_low,
		open_consecutive_polls=config.respeaker.open_consecutive_polls,
		close_consecutive_polls=config.respeaker.close_consecutive_polls,
		rms_threshold=config.speech.wake_rms_gate,
		rms_hold_frames=config.speech.wake_gate_hold_frames,
	)

	leds = ReSpeakerLedController(
		control=control,
		enabled=config.respeaker.led_enabled,
		listening_effect=config.respeaker.led_listening_effect,
		listening_color=config.respeaker.led_listening_color,
		idle_effect=config.respeaker.led_idle_effect,
	)

	def on_state(state: str) -> None:
		leds.handle_state(state)

	engine = SpeechEngine(
		wakeword=wakeword,
		audio_in=audio_in,
		vad=vad,
		sample_rate=config.audio.sample_rate,
		max_utterance_s=config.vad.max_utterance_s,
		debug=config.speech.debug,
		input_gain=config.speech.input_gain,
		wake_rms_gate=config.speech.wake_rms_gate,
		wake_gate_hold_frames=config.speech.wake_gate_hold_frames,
		wake_preroll_enabled=config.speech.wake_preroll_enabled,
		wake_preroll_ms=config.speech.wake_preroll_ms,
		gate=gate,
		state_listener=on_state,
	)
	return engine, leds


def _stream_utterance_to_ha(state, audio: np.ndarray, sample_rate: int) -> None:
	satellite = state.satellite
	if satellite is None:
		return

	x = np.asarray(audio, dtype=np.float32).reshape(-1)
	if x.size == 0:
		return

	pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
	chunk_samples = max(1, int(sample_rate * 0.02))
	chunk_bytes = chunk_samples * 2
	for i in range(0, len(pcm), chunk_bytes):
		satellite.handle_audio(pcm[i : i + chunk_bytes])

	# Send short trailing silence so HA-side VAD can close the stream quickly.
	silence_chunk = b"\x00\x00" * chunk_samples
	for _ in range(10):
		satellite.handle_audio(silence_chunk)


def process_audio(state, mic, block_size):  # noqa: ARG001
	"""Override LVA process_audio with satellites wakeword + VAD pipeline."""
	config_path = os.environ.get("SAT_CONFIG_PATH")
	cfg = ConfigManager(path=config_path).load(create_if_missing=True)

	configure_logging(cfg.runtime.log_level)
	engine, _ = _build_speech_engine(cfg)
	LOGGER.info("Using satellites wake/VAD frontend (wakewords file-backed)")

	def on_wakeword(evt) -> None:
		satellite = state.satellite
		if satellite is None or state.muted:
			return
		keyword = str(evt.get("keyword") or evt.get("text") or "wake")
		LOGGER.info("Custom wakeword detected: %s", keyword)
		try:
			satellite.wakeup(_WakeWordEvent(wake_word=keyword))
		except Exception:
			LOGGER.exception("Failed to start HA voice run")

	def on_utterance(audio: np.ndarray, reason: str) -> None:
		satellite = state.satellite
		if satellite is None or state.muted:
			return
		LOGGER.info("Custom utterance captured: reason=%s samples=%s", reason, int(audio.size))
		try:
			_stream_utterance_to_ha(state, audio, cfg.audio.sample_rate)
		except Exception:
			LOGGER.exception("Failed to stream captured utterance to HA")

	engine._on_wakeword = on_wakeword
	engine._on_utterance_ended = on_utterance

	try:
		engine.start()
	except KeyboardInterrupt:
		pass
	except Exception:
		LOGGER.exception("Custom wake/VAD frontend crashed")
		sys.exit(1)


def main() -> None:
	lva_main.process_audio = process_audio
	asyncio.run(lva_main.main())


if __name__ == "__main__":
	main()

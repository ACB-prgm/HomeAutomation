from __future__ import annotations

import argparse
import logging
from pathlib import Path

from speech import SpeechEngine
from speech.audio import AudioConfig, AudioInput
from speech.vad import SherpaVAD
from speech.wakeword import SherpaWakeword, WakewordConfig
from utils import IdentityManager, SatelliteController
from utils.config import ConfigManager
from utils.runtime_logging import configure_logging, context_extra


def _build_speech_engine(config):
	if config.vad.mode != "sherpa":
		print(f"WARNING: vad.mode '{config.vad.mode}' is not fully wired yet. Using 'sherpa' backend.")

	audio_in = AudioInput(
		AudioConfig(
			channels=config.audio.channels,
			block_size=config.audio.block_size,
			sample_rate=config.audio.sample_rate,
			device=config.audio.input_device,
		)
	)

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

	return SpeechEngine(
		wakeword=wakeword,
		audio_in=audio_in,
		vad=vad,
		sample_rate=config.audio.sample_rate,
		max_utterance_s=config.vad.max_utterance_s,
		debug=config.speech.debug,
		input_gain=config.speech.input_gain,
		wake_rms_gate=config.speech.wake_rms_gate,
		wake_gate_hold_frames=config.speech.wake_gate_hold_frames,
	)


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run the Home Automation satellite runtime.")
	parser.add_argument(
		"--config",
		type=Path,
		default=None,
		help="Path to satellite config (.json by default, .yaml/.yml supported with PyYAML).",
	)
	return parser.parse_args()


def main(config_path: Path | str | None = None):
	try:
		config = ConfigManager(path=config_path).load(create_if_missing=True)
		configure_logging(config.runtime.log_level)
		logger = logging.getLogger("satellite.main")
		logger.info(
			"Config loaded",
			extra=context_extra(room=config.identity.room),
		)
		logger.info(
			f"Starting satellite '{config.identity.friendly_name}'",
			extra=context_extra(room=config.identity.room),
		)
		im = IdentityManager(path=config.identity.path)
		identity = im.load()
		logger.info(
			"Identity loaded",
			extra=context_extra(
				satellite_id=identity.satellite_id,
				room=config.identity.room,
			),
		)

		controller = SatelliteController(
			identity,
			None,
			None,
			_build_speech_engine(config),
			room=config.identity.room,
		)
		controller.start()
	except KeyboardInterrupt:
		logging.getLogger("satellite.main").info("Shutdown requested by user")


if __name__ == "__main__":
	args = _parse_args()
	main(config_path=args.config)

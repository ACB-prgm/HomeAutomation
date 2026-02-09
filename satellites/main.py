from __future__ import annotations

import argparse
from pathlib import Path

from speech import SpeechEngine
from speech.audio import AudioConfig, AudioInput
from speech.vad import SherpaVAD
from utils import IdentityManager, SatelliteController
from utils.config import ConfigManager


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
	)

	return SpeechEngine(
		audio_in=audio_in,
		vad=vad,
		sample_rate=config.audio.sample_rate,
		max_utterance_s=config.vad.max_utterance_s,
		debug=config.speech.debug,
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
		print(f"Starting satellite '{config.identity.friendly_name}'")
		im = IdentityManager(path=config.identity.path)

		controller = SatelliteController(
			im.load(),
			None,
			None,
			_build_speech_engine(config),
		)
		controller.start()
	except KeyboardInterrupt:
		pass


if __name__ == "__main__":
	args = _parse_args()
	main(config_path=args.config)

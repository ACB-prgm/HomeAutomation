import numpy as np


class SatelliteController:
	def __init__(self, identity, device_mgr, mqtt, speech):
		self.identity = identity
		self.device_mgr = device_mgr
		self.mqtt = mqtt

		self.speech = speech
		self.speech._on_utterance_ended = self.handle_utterance
		self.speech._on_wakeword = self.handle_wakeword

	def start(self):
		# self.mqtt.on_command(self.handle_command)
		self.speech.start()

	def handle_wakeword(self, evt: dict):
		print(evt)

	def handle_utterance(self, audio: np.ndarray, reason: str):
		print(reason)

	def handle_command(self, command):
		if command.type == "set_volume":
			self.device_mgr.audio.set_volume(command.value)

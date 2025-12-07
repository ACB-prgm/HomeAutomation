from stt.whisper_backend import STT
from .triage import UtteranceCategorizer


class CoreService:
    def __init__(self):
        self.stt = STT()
        # self.tts = PiperBackend()
        # self.router = IntentRouter()
        # self.mqtt = MQTTBus()

    def handle_audio(self, wav_file):
        text = self.stt.transcribe(wav_file)
        # intent = self.router.route(text)
        # response_audio = self.tts.synthesize(intent.response)
        # self.mqtt.send_audio_to_satellite(response_audio)
        return text

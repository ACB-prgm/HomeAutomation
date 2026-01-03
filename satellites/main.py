from speech import SpeechEngine, SpeechEngineCallbacks
import soundfile as sf

def on_wakeword(evt: dict):
	print("Wakeword detected!")
	print(evt)

def on_utterance_ended(audio, reason: str):
	print(reason)
	# This automatically writes the correct WAV header and handles float32 data
	sf.write("satellites/test.wav", audio, 16000)
	# quit()

def main():
	callbacks = SpeechEngineCallbacks(
		on_wakeword=on_wakeword,
		on_utterance_ended=on_utterance_ended
	)
	speech_engine = SpeechEngine(callbacks=callbacks, debug=True)
	try:
		speech_engine.start()
	except KeyboardInterrupt:
		pass

if __name__ == "__main__":
	main()
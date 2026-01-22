from speech import SpeechEngine
from utils import IdentityManager, SatelliteController


def main():
	try:
		im = IdentityManager()

		controller = SatelliteController(
			im.load(),
			None, 
			None,
			SpeechEngine(debug=True)
		)
		controller.start()
	except KeyboardInterrupt:
		pass

if __name__ == "__main__":
	main()
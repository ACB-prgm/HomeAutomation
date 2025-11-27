import subprocess
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = BASE / "runtime"
VENV = RUNTIME / "venv"

def start_home_assistant():
    hass_bin = VENV / "bin" / "hass"
    if not hass_bin.exists():
        raise RuntimeError("Home Assistant is not installed. Run bootstrap/install_ha_venv.sh first.")
    subprocess.run([str(hass_bin)], check=True)

if __name__ == "__main__":
    start_home_assistant()

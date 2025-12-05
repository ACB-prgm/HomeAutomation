# Home Automation

## Directory Structure
```
HomeAutomation/
├── bootstrap.sh              # Sets up .venv, installs deps, starts server (optional)
├── requirements.txt          # Python deps for server + tools (no HA here now)
├── .gitignore
├── .venv/                    # Python venv (not committed, just here physically)
│
├── server/                   # ⬅ Flask (or FastAPI) server entrypoint lives here
│   ├── __init__.py
│   ├── app.py                # ⬅ main Flask app: HTTP + health endpoints
│   ├── config.py             # config loading (env vars, YAML, etc.)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── audio_endpoints.py   # /api/audio/upload, /tts/stream, etc.
│   │   └── status_endpoints.py  # /api/status, /api/debug
│   └── wsgi.py               # optional if you ever run under gunicorn/uwsgi
│
├── core/                     # ⬅ custom Python modules used by the server
│   ├── __init__.py
│   ├── mqtt_bus.py           # MQTT connect, subscribe, publish helpers
│   ├── routing.py            # intent router (weather/smart-home/time vs LLM)
│   ├── stt/
│   │   ├── whisper_backend.py   # wrapper for Whisper or other STT
│   │   └── apple_stt_backend.py # wrapper for macOS STT if you use it
│   ├── tts/
│   │   ├── piper_backend.py     # wrapper for Piper or chosen TTS engine
│   │   └── apple_tts_backend.py # wrapper for macOS TTS if used
│   ├── llm/
│   │   ├── router.py            # “simple vs LLM” decision logic if you want it separated
│   │   └── client.py            # LLM client (local or remote)
│   ├── homeassistant/
│   │   ├── ha_client.py         # REST/WebSocket client to HA on the Pi
│   │   └── models.py            # small dataclasses for HA entities/services
│   └── triage/
│       ├── models/              # Contains the joblib NLP model exports
│       └── triage.py            # Utterance intent classifier
│
├── satellites/               # Code that runs *on* the Pi satellites (client side)
│   ├── pi_client/
│   │   ├── __init__.py
│   │   ├── main.py             # entrypoint: wake word + VAD + MQTT client
│   │   ├── audio_io.py         # ALSA I/O, play/record
│   │   ├── mqtt_client.py      # MQTT loop on the Pi
│   │   ├── config.py
│   │   └── hardware/           # GPIO, buttons, display drivers, etc.
│   │       ├── display.py
│   │       └── buttons.py
│   └── README.md
│
├── config/                   # Non-secret config files for the server
│   ├── server.yaml           # ports, MQTT broker address, HA URL, etc.
│   ├── logging.yaml          # logging levels/formatters
│   └── .env.example          # example ENV vars (HA tokens, API keys)
│
├── scripts/                  # CLI scripts / ops helpers (optional but handy)
│   ├── run_server.sh         # activate .venv + `python -m server.app`
│   ├── dev_shell.sh          # spawn venv shell
│   ├── mqtt_debug.py         # small tool to inspect/publish MQTT messages
│   └── generate_test_audio.py
│
├── docs/
│   ├── architecture.md       # describes this flow: satellite → server → HA → satellite
│   └── protocol.md           # JSON schemas for MQTT messages & HTTP endpoints
│
└── tests/
    ├── test_routing.py
    ├── test_mqtt_bus.py
    └── test_ha_client.py
```

# Home Assistant Server (macOS server)

This repository contains the full environment setup for running **Home Assistant in a Python virtual environment** on a macOS server.  
The goal is to provide a clean, reproducible, version-controlled foundation for a local smart-home orchestration system and the future custom assistant stack.

---

## Directory Structure

```
home-assistant-server/
├── bootstrap.sh                # One-step setup script for Home Assistant
├── bootstrap/
│   └── macos_launchd_plist.xml # Launchd config for autostart
├── runtime/                    # Created automatically on first run
│   └── venv/                  # Python virtual environment (not committed)
├── requirements.txt            # Generated after bootstrap installs HA
├── .gitignore
└── README.md
```

**Key points:**

- `bootstrap.sh` performs all provisioning (Python, venv, HA install, launchd registration).
- `runtime/` is for machine-local state. Nothing here should be versioned.
- `requirements.txt` is generated automatically after Home Assistant is installed.

---

## Setup Instructions

### 1. Clone the repo on the server

```
git clone git@github.com:<your-username>/home-assistant-server.git
cd home-assistant-server
```

### 2. Run the bootstrap script

```
./bootstrap.sh
```

The script will:

- Install Python via Homebrew (if missing)
- Create the venv under `runtime/venv`
- Install Home Assistant and freeze dependencies to `requirements.txt`
- Install the launchd plist for automatic startup
- Load the launchd agent so Home Assistant begins running

---

## Starting Home Assistant Manually

You can manually start HA any time using:

```
runtime/venv/bin/hass
```

Once the launchd plist is installed, Home Assistant will start automatically at login.

---

## Accessing Home Assistant

After bootstrap, open:

```
http://<server-ip>:8123
```

You’ll see the Home Assistant onboarding interface.

---

## Updating Home Assistant

To update the pinned version:

1. Activate the venv:

   ```bash
   source runtime/venv/bin/activate
   ```

2. Upgrade Home Assistant:

   ```bash
   pip install --upgrade homeassistant
   ```

3. Freeze dependencies:

   ```bash
   pip freeze > requirements.txt
   ```

Commit the updated `requirements.txt` to version control.

---

## Why the Virtual Environment Is Not Committed

The venv contains platform-dependent binaries and macOS-specific wheels.  
Committing it would break portability, bloat the repo, and cause conflicts.

`requirements.txt` is the source of truth, and `bootstrap.sh` recreates the venv reliably.

---

## Next Steps (Phase 2 and beyond)

Future phases will extend this repo to include:

- MQTT broker (Mosquitto) installation and configuration  
- Assistant orchestration services (TTS, STT, LLM routing)  
- Satellite provisioning scripts (for Raspberry Pi microphone/speaker screens)  
- Local APIs for intents, command dispatch, and multi-device coordination  

The structure is designed to scale cleanly as these pieces are added.

---

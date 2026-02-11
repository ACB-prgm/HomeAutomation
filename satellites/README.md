# Satellites

This directory contains the Raspberry Pi satellite runtime and helper scripts.

## Quick Start (Pi)

1. Bootstrap dependencies, virtualenv, and model assets:

```bash
./satellites/satellite_bootstrap.sh
```

2. Optional: list audio devices and select the right input/output indices:

```bash
./satellites/scripts/list_audio_devices.sh
```

3. Run the satellite:

```bash
./satellites/scripts/run_satellite.sh
```

## Provisioning a New Pi (No Reflash for Updates)

Use the provisioning script once on a new Pi:

```bash
sudo ./satellites/scripts/pi_install_lva.sh \
  --repo-url https://github.com/ACB-prgm/HomeAutomation.git \
  --branch codex/ai-dev \
  --service-user pi \
  --update-token "<strong-shared-token>"
```

What it does:
- Clones repo to `/opt/homeautomation` with sparse checkout (`satellites/` only)
- Creates persistent config at `/etc/home-satellite/satellite.json`
- Preserves identity at `/var/lib/satellite/identity.json`
- Bootstraps runtime and models
- Installs and starts:
  - `home-satellite.service`
  - `home-satellite-updater.service`

Update configuration lives in `/etc/default/home-satellite`.

## Remote Update Contract

Updater daemon listens on:
- `home/satellites/all/update`
- `home/satellites/<satellite_id>/update`

Expected JSON payload:

```json
{
  "auth_token": "<SAT_UPDATE_TOKEN>",
  "target": "branch:codex/ai-dev",
  "satellite_id": "all"
}
```

Notes:
- `target` can be `branch:<name>`, `commit:<sha>`, or plain branch name.
- Updates run through `satellites/scripts/update_satellite.sh`.
- Config and identity are preserved because they are stored outside the repo.

## Scripts

- `satellites/satellite_bootstrap.sh`
  - Installs Debian/Ubuntu OS packages (unless `--skip-apt`)
  - Creates/updates Python runtime (unless `--skip-python`)
  - Creates/updates the satellite virtualenv at `sat_venv`
  - Installs `satellites/sat_requirements.txt`
  - Downloads wakeword + VAD models (unless `--skip-models`)
  - Creates default config if missing
  - Args:
    - `--skip-apt`
    - `--skip-python`
    - `--skip-models`
    - `--force-models`
    - `-h`, `--help`
- `satellites/scripts/run_satellite.sh`
  - Launches `satellites/main.py` with a config path.
  - Runs preflight checks for venv, Python deps, and model files.
  - Auto-runs `satellites/satellite_bootstrap.sh` if requirements are missing.
  - Args:
    - `--config <path>`
    - `--venv <path>`
    - `--no-bootstrap`
    - `--` (pass extra args to `main.py`)
    - `-h`, `--help`
- `satellites/scripts/list_audio_devices.sh`
  - Prints PortAudio device list and default device indices.
  - Args: none
- `satellites/scripts/pi_install_lva.sh`
  - One-time Pi provisioning with sparse checkout + service installation.
  - Args:
    - `--repo-url <url>`
    - `--branch <name>`
    - `--install-dir <path>`
    - `--config-path <path>`
    - `--identity-path <path>`
    - `--service-user <name>`
    - `--mqtt-broker <host>`
    - `--mqtt-port <port>`
    - `--update-token <token>`
    - `--skip-apt`
    - `-h`, `--help`
- `satellites/scripts/update_satellite.sh`
  - Safe update script with rollback to previous revision on failure.
  - Args:
    - `--target <branch:name|commit:sha>`
    - `--dry-run`
    - `-h`, `--help`
- `satellites/scripts/satellite_updater_daemon.py`
  - MQTT daemon that validates tokenized update messages and runs update script.

## Config

Default config path: `satellites/config/satellite.json`

Identity config includes:
- `friendly_name`
- `path` (identity file path)
- `room` (used for structured log context)

You can override when launching:

```bash
./satellites/scripts/run_satellite.sh --config /path/to/satellite.json
```

## Logging

Runtime logs include structured fields:
- `satellite_id`
- `session_id`
- `pipeline_run_id`
- `room`

## Open Validation TODOs

- Validate `./satellites/scripts/list_audio_devices.sh` detects ReSpeaker XVF3800 on target Pi.
- Set and verify `audio.input_device` / `audio.output_device` in `satellites/config/satellite.json` from discovered indices.

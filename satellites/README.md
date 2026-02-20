# Satellites

This directory contains the Raspberry Pi satellite runtime and helper scripts.

## Quick Start (Pi)

1. Bootstrap shared dependencies, virtualenv, and model assets (custom runtime path):

```bash
./satellites/satellite_bootstrap.sh
```

2. Optional: list audio devices and select the right input/output indices:

```bash
./satellites/scripts/list_audio_devices.sh
```

3. Run the custom satellite runtime:

```bash
./satellites/scripts/run_satellite.sh
```

4. Run Linux Voice Assistant runtime (Phase 1B path):

```bash
./satellites/scripts/install_lva_runtime.sh --skip-apt
./satellites/scripts/run_lva_satellite.sh
```

## Provisioning a New Pi (No Reflash for Updates)

Use the provisioning script once on a new Pi:

```bash
sudo ./satellites/scripts/pi_install_lva.sh \
  --repo-url https://github.com/ACB-prgm/HomeAutomation.git \
  --branch codex/ai-dev \
  --runtime-mode lva \
  --service-user pi \
  --update-token "<strong-shared-token>"
```

What it does:
- Clones repo to `/opt/homeautomation` with sparse checkout (`satellites/` only)
- Creates persistent config at `/etc/home-satellite/satellite.json`
- Preserves identity at `/var/lib/satellite/identity.json`
- Bootstraps shared satellite tooling and ReSpeaker setup
- Installs selected runtime mode:
  - `custom`: existing Python runtime in this repo
  - `lva`: Linux Voice Assistant checkout + venv
- Installs and starts:
  - `home-satellite.service`
  - `home-satellite-updater.service`
  - `respeaker-led-off.service` (turns off XVF3800 LEDs at boot)

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
- Updates re-apply wakewords from `satellites/config/wakewords.txt` when `SAT_RUNTIME_MODE=custom`.
- Updates also re-apply wakewords in `SAT_RUNTIME_MODE=lva` when `SAT_LVA_FRONTEND=satellite`.
- Updates re-install/refresh Linux Voice Assistant when `SAT_RUNTIME_MODE=lva`.
- Updates re-apply ReSpeaker channel/LED policy via `satellites/scripts/respeaker_configure.sh`.
- Config and identity are preserved because they are stored outside the repo.

## Home Assistant Onboarding (LVA Mode)

1. Provision Pi with `--runtime-mode lva`.
2. Confirm service is active:

```bash
sudo systemctl status home-satellite.service --no-pager
```

3. In Home Assistant:
   - Go to `Settings -> Devices & Services -> Add Integration`.
   - Add `ESPHome`.
   - Enter the Pi host/IP and port `6053`.
4. Assign the discovered satellite device to the target room/area.

## Scripts

- `satellites/satellite_bootstrap.sh`
  - Installs Debian/Ubuntu OS packages (unless `--skip-apt`)
  - Creates/updates Python runtime (unless `--skip-python`)
  - Creates/updates the satellite virtualenv at `sat_venv`
  - Installs `satellites/sat_requirements.txt`
  - Downloads wakeword + VAD models (unless `--skip-models`)
  - Downloads ReSpeaker XVF3800 host-control tools on Pi 64-bit (unless `--skip-respeaker-tools`)
  - Creates default config if missing
  - Applies ReSpeaker channel/LED policy from config
  - Args:
    - `--skip-apt`
    - `--skip-python`
    - `--skip-models`
    - `--force-models`
    - `--skip-respeaker-tools`
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
  - One-time Pi provisioning with sparse checkout + runtime mode service installation.
  - Args:
    - `--repo-url <url>`
    - `--branch <name>`
    - `--install-dir <path>`
    - `--config-path <path>`
    - `--identity-path <path>`
    - `--service-user <name>`
    - `--runtime-mode <custom|lva>`
    - `--mqtt-broker <host>`
    - `--mqtt-port <port>`
    - `--update-token <token>`
    - `--lva-repo-url <url>`
    - `--lva-ref <name|sha>`
    - `--lva-dir <path>`
    - `--lva-venv <path>`
    - `--lva-wake-model <name>`
    - `--lva-frontend <satellite|lva_default>`
    - `--skip-apt`
    - `-h`, `--help`
- `satellites/scripts/install_lva_runtime.sh`
  - Installs/updates Linux Voice Assistant checkout + virtualenv.
  - Installs required OS audio deps in apt mode, including `pulseaudio` and `libmpv2`.
  - Installs satellites wake/VAD dependencies in the LVA venv when `--frontend satellite`.
  - Args:
    - `--repo-url <url>`
    - `--ref <name|sha>`
    - `--install-dir <path>`
    - `--venv <path>`
    - `--service-user <name>`
    - `--frontend <satellite|lva_default>`
    - `--skip-apt`
    - `-h`, `--help`
- `satellites/scripts/run_lva_satellite.sh`
  - Launches Linux Voice Assistant and maps satellite config defaults (`friendly_name`, input/output devices) to CLI flags.
  - Ensures a PulseAudio user daemon is running before starting Linux Voice Assistant.
  - `--frontend satellite` (default) keeps HA ESPHome transport but replaces wake/VAD front-end with satellites runtime (`CORA/GLADOS/SPARK` via `wakewords.txt`).
  - Auto-runs `install_lva_runtime.sh --skip-apt` if the LVA runtime is missing.
  - Args:
    - `--config <path>`
    - `--lva-dir <path>`
    - `--venv <path>`
    - `--name <value>`
    - `--wake-model <value>`
    - `--stop-model <value>`
    - `--host <value>`
    - `--port <value>`
    - `--interface <value>`
    - `--frontend <satellite|lva_default>`
    - `--no-install`
    - `--` (pass extra args to `linux_voice_assistant`)
    - `-h`, `--help`
- `satellites/scripts/lva_satellite_frontend.py`
  - Custom audio front-end adapter for LVA mode:
    - uses satellites wakeword/VAD/utterance capture
    - streams captured utterance audio through LVA's HA transport (`VoiceSatelliteProtocol`)
- `satellites/scripts/update_satellite.sh`
  - Safe update script with rollback to previous revision on failure.
  - Applies mode-specific runtime refresh:
    - `custom`: bootstrap + wakeword apply
    - `lva`: bootstrap (shared deps) + LVA runtime install/update
  - Args:
    - `--target <branch:name|commit:sha>`
    - `--dry-run`
    - `-h`, `--help`
- `satellites/scripts/satellite_updater_daemon.py`
  - MQTT daemon that validates tokenized update messages and runs update script.
- `satellites/scripts/respeaker_led_off.sh`
  - Uses `xvf_host` to disable ReSpeaker XVF3800 LEDs.
  - Intended for use by `respeaker-led-off.service`.
- `satellites/scripts/respeaker_configure.sh`
  - Applies ReSpeaker channel route and idle LED policy from `satellite.json`.
  - Uses configured backend with fallback to `xvf_host`.
- `satellites/scripts/install_respeaker_udev.sh`
  - Installs udev rule for ReSpeaker XVF3800 USB permissions (VID:PID `2886:001a`).
  - Called by provisioning/update/bootstrap when running as root.
- `satellites/scripts/set_wakewords.sh`
  - Sets custom wakeword phrases and regenerates tokenized keywords.
  - Example:
    - `./satellites/scripts/set_wakewords.sh "HEY CORA" "GLADOS" "SPARK"`
    - `./satellites/scripts/set_wakewords.sh --file ./satellites/config/wakewords.txt`
- `satellites/scripts/test_voice_pipeline.sh`
  - Runs a timed validation and summarizes wake/utterance/gate/LED events with temp+CPU samples.
  - Example:
    - `./satellites/scripts/test_voice_pipeline.sh --duration 1200 --interval 15`

## Config

Default config path: `satellites/config/satellite.json`

Identity config includes:
- `friendly_name`
- `path` (identity file path)
- `room` (used for structured log context)

You can override when launching:

```bash
./satellites/scripts/run_satellite.sh --config /path/to/satellite.json
./satellites/scripts/run_lva_satellite.sh --config /path/to/satellite.json
```

### Speech Runtime Tuning

`speech` settings support low-power tuning:
- `input_gain` (default `1.0`): leave at `1.0` for ReSpeaker unless you need amplification.
- `wake_rms_gate` (default `0.0035`): lightweight RMS gate before wakeword decode.
- `wake_gate_hold_frames` (default `8`): keeps wake decode open briefly after energy drops.
- `wake_preroll_enabled` (default `true`): cache recent wake frames and replay once when gate opens.
- `wake_preroll_ms` (default `400`): pre-roll window size for first-phoneme recovery when gate opens late.
- `wakeword_threads` (default `1`): ONNX threads used by wakeword model.
- `vad_threads` (default `1`): ONNX threads used by Sherpa VAD.

### ReSpeaker Runtime Tuning

`respeaker` settings control hardware-first gating and LEDs:
- `enabled` (default `true`)
- `control_backend` (default `xvf_host`; `pyusb` optional and falls back to `xvf_host`)
- `poll_interval_ms` (default `50`)
- `gate_mode` (`rms`, `xvf`, `hybrid`; default `hybrid`)
- `speech_energy_high` / `speech_energy_low` (Schmitt trigger thresholds)
  - XVF reports speech energy where values `> 0` indicate speech activity.
  - Default `0.001/0.0001` (open/close hysteresis thresholds).
- `open_consecutive_polls` / `close_consecutive_polls` (hysteresis confirmation)
- `led_enabled` (default `true`)
- `led_listening_effect`, `led_listening_color`, `led_idle_effect`
- `channel_strategy` (`left_processed` default, `right_asr` optional A/B path)
- `channel_strategy=right_asr` requires `audio.channels >= 2`

### Wakeword Phrases

Bootstrap now preserves existing `satellites/speech/models/wakeword_keywords/keywords_raw.txt`
and `keywords.txt` unless `--force-models` is used.

Canonical wakewords file:
- `satellites/config/wakewords.txt`

Provisioning and updater flows apply this file automatically via `set_wakewords.sh`.

## Logging

Runtime logs include structured fields:
- `satellite_id`
- `session_id`
- `pipeline_run_id`
- `room`
- `gate_mode`
- `gate_open`
- `speech_energy`
- `led_state`

## Open Validation TODOs

- Validate `./satellites/scripts/list_audio_devices.sh` detects ReSpeaker XVF3800 on target Pi.
- Set and verify `audio.input_device` / `audio.output_device` in `satellites/config/satellite.json` from discovered indices.
- Validate `respeaker.channel_strategy` (`left_processed` vs `right_asr`) using `./satellites/scripts/test_voice_pipeline.sh`.
- Validate `SAT_RUNTIME_MODE=lva` onboarding in Home Assistant via ESPHome integration.

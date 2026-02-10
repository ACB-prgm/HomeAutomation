# Satellite Implementation Plan (Raspberry Pi + ReSpeaker XVF3800 + Home Assistant)

Last updated: 2026-02-09

## 1) Goals and Success Criteria

This plan is aligned to the agreed outcomes:

1. All satellite code runs on Raspberry Pi with ReSpeaker XVF3800 USB mic array.
2. Satellite integrates into Home Assistant as a device and supports room/area assignment.
3. Satellite participates in Home Assistant voice pipeline (send/receive audio and responses).
4. Satellite has internal settings (volume, id, status, etc.) with persistence.
5. Satellite is selectable as a Spotify Connect playback target.

## 2) Final Architecture Decisions

1. Primary satellite runtime: Linux Voice Assistant (LVA) on Pi.
2. HA integration protocol: ESPHome API (via HA ESPHome integration).
3. ReSpeaker audio processing strategy (Phase 1):
   - Use XVF3800 onboard DSP (AEC/AGC/NS/beamforming/VAD) only.
   - Do not enable software echo cancel unless performance fails acceptance tests.
4. VAD strategy:
   - Use hybrid path initially: XVF3800 VAD as gate/hint + Sherpa VAD for utterance endpointing.
   - Keep runtime-selectable VAD modes: `sherpa`, `xvf`, `hybrid`.
5. Media strategy:
   - Voice/TTS playback and Spotify playback use the same physical speaker output path.
   - Spotify device presence implemented via `raspotify` (librespot backend).

## 3) Why This Direction

1. `wyoming-satellite` is archived and marked as replaced by Linux Voice Assistant.
2. LVA is the maintained Linux/Pi path and connects to HA through ESPHome protocol.
3. HA Assist Satellite capabilities (announce, start conversation, ask question) align better with ESPHome-based satellite feature direction.
4. XVF3800 explicitly provides onboard AEC/noise suppression/VAD, so we should exploit hardware DSP before adding software AEC complexity.

## 4) Implementation Roadmap

## Phase 0: Baseline and Repo Hardening

1. Create `satellites/config/satellite.json` schema (with optional YAML support later) with:
   - identity (`satellite_id`, `friendly_name`)
   - audio devices (`input_device`, `output_device`, sample rates)
   - VAD mode (`sherpa`/`xvf`/`hybrid`)
   - runtime options (debug, reconnect backoff, wake model)
2. Implement config loader + validation in `/satellites/utils/config.py` (currently empty).
3. Keep `IdentityManager` as source of persistent `satellite_id`; unify test and production path behavior.
4. Add structured logging fields: `satellite_id`, `session_id`, `room`, `pipeline_run_id`.

Exit criteria:
1. One command starts the satellite locally on Pi.
2. Identity + config persist across reboot.

## Phase 1: LVA Integration on Pi

1. Add a wrapper service manager in this repo:
   - installer script for Pi dependencies
   - systemd unit template for Linux Voice Assistant
2. Configure LVA launch flags:
   - `--name <friendly_name>`
   - explicit `--audio-input-device` and `--audio-output-device`
   - selected wake model(s)
3. Document HA onboarding:
   - Add Integration -> ESPHome -> add satellite host:6053

Exit criteria:
1. Satellite appears in HA as ESPHome-backed device.
2. Satellite entity is stable through HA restart and Pi reboot.

## Phase 2: Audio Path and VAD Pipeline

1. Keep existing Sherpa modules in `/satellites/speech` and add mode adapter:
   - `sherpa`: current logic
   - `xvf`: hardware VAD event-driven capture
   - `hybrid`: XVF gate + Sherpa finalize
2. Add VAD quality metrics:
   - false start count
   - clipped start/end estimates
   - avg turn latency
3. Validate wake/STT while playback is active using only XVF DSP first.

Fallback rule:
1. If barge-in quality fails thresholds, schedule Phase 2b software AEC (disabled by default).

Exit criteria:
1. Wake + command capture works during local playback in real room noise.
2. No software AEC enabled in Phase 1/2 unless test failures require it.

## Phase 3: Home Assistant Voice Pipeline Compliance

1. Ensure end-to-end Assist pipeline compatibility:
   - wake/listen
   - upload stream to HA
   - receive TTS/announce/start_conversation outputs
2. Validate `assist_satellite` action compatibility:
   - `announce`
   - `start_conversation`
   - `ask_question` behavior via configured conversation agent
3. Implement robust reconnect state machine for:
   - HA API disconnect
   - network interruption
   - pipeline timeout/abort

Exit criteria:
1. 50+ sequential voice interactions without crash/stuck state.
2. Announce and conversation actions behave correctly from HA automations.

## Phase 4: Device Settings and Control Surface

1. Expose and persist internal settings:
   - volume
   - mute status
   - current state (`idle/listening/processing/responding`)
   - VAD mode
2. Mirror key settings to HA entities (where supported) for control from UI.
3. Add local admin path:
   - CLI for safe recovery when HA unavailable
   - status dump command for troubleshooting

Exit criteria:
1. Settings survive reboot.
2. Settings changes are reflected in both local runtime and HA UI.

## Phase 5: Spotify Connect Playback Target

1. Install/configure `raspotify` on Pi with deterministic device name.
2. Ensure output device uses satellite speaker path.
3. Validate HA Spotify integration `source` selection workflow.
4. Add optional playback ducking behavior:
   - reduce music volume on wake
   - restore volume after turn completion

Exit criteria:
1. Satellite appears in Spotify Connect source list.
2. HA can select and play Spotify audio to the satellite.

## 5) Test Matrix (Definition of Done)

## Functional

1. Pi boot -> satellite service auto-starts and registers in HA.
2. HA area assignment works and persists.
3. Voice command roundtrip works: wake -> STT -> intent/conversation -> TTS playback.
4. `assist_satellite.announce` and `assist_satellite.start_conversation` work from automation.
5. Spotify Connect playback starts from HA-selected source.

## Reliability

1. HA restart recovery < 60 seconds without manual intervention.
2. Wi-Fi interruption recovery < 90 seconds after network return.
3. 50 wake/query/respond cycles with no process crash.

## Audio Quality

1. Wake detection and STT accuracy acceptable with moderate background noise.
2. Wake + command capture while local playback active (barge-in scenario).
3. If failures exceed threshold, mark for Phase 2b software AEC.

## 6) Deliverables in This Repo

1. `satellites/SATELLITE_IMPLEMENTATION_PLAN.md` (this file).
2. New config module implementation in `/satellites/utils/config.py`.
3. Pi installer + service scripts for LVA + raspotify.
4. Runtime mode adapter for `sherpa/xvf/hybrid` VAD operation.
5. Validation playbooks/checklists in `/satellites/` docs.

## 7) Risks and Mitigations

1. Risk: XVF hardware DSP alone may be insufficient for some speaker/mic placements.
   - Mitigation: strict test gates + optional software AEC in Phase 2b only if needed.
2. Risk: feature drift between LVA and HA releases.
   - Mitigation: pin known-good versions; verify against HA release notes before updates.
3. Risk: Spotify Connect device conflicts (duplicate names or output routing mismatch).
   - Mitigation: enforce unique device name and fixed ALSA/PipeWire output mapping.

## 8) Immediate Next Steps

1. Add structured logging fields (`satellite_id`, `session_id`, `pipeline_run_id`) across satellite runtime.
2. Add `satellites/scripts/pi_install_lva.sh` and systemd unit templates.
3. Add first-pass VAD mode abstraction (`sherpa` default, `hybrid` scaffolded).
4. Validate launcher/bootstrap flow end-to-end on Raspberry Pi hardware (XVF3800 connected).

## References

1. Linux Voice Assistant (ESPHome protocol): https://github.com/OHF-Voice/linux-voice-assistant
2. Wyoming Satellite archive + deprecation notice: https://github.com/rhasspy/wyoming-satellite
3. Home Assistant Assist Satellite integration: https://www.home-assistant.io/integrations/assist_satellite/
4. Home Assistant Assist Satellite entity (developer docs): https://developers.home-assistant.io/docs/core/entity/assist-satellite/
5. Home Assistant Assist pipelines API: https://developers.home-assistant.io/docs/voice/pipelines/
6. Home Assistant ESPHome integration: https://www.home-assistant.io/integrations/esphome
7. Home Assistant Wyoming integration (still supported): https://www.home-assistant.io/integrations/wyoming/
8. Home Assistant area organization: https://www.home-assistant.io/docs/organizing/areas/
9. Home Assistant voice guidance for assigning devices to areas/floors: https://www.home-assistant.io/voice_control/assign_areas_floors/
10. ReSpeaker XVF3800 product page: https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-Mic-Array-p-6488.html
11. ReSpeaker XVF3800 getting started wiki: https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/
12. ReSpeaker XVF3800 Python control wiki: https://wiki.seeedstudio.com/respeaker_xvf3800_python_sdk/
13. Home Assistant Spotify integration: https://www.home-assistant.io/integrations/spotify/
14. Raspotify repository: https://github.com/dtcooper/raspotify

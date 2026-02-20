# ASR Wyoming Service (Core -> Home Assistant)

This repo now exposes a dedicated Wyoming ASR endpoint from `core` while keeping
`/api/audio` for compatibility.

## How It Starts

Start the server as usual:

```bash
python -m server.app
```

`CoreService` automatically starts:
- TTS Wyoming (existing behavior)
- ASR Wyoming (new behavior)

By default, ASR is exposed at:

```text
tcp://<core-host-ip>:10300
```

`CoreService` binds localhost-style URIs to the preferred host IP so Home Assistant
can connect from the network.

## Home Assistant Setup

1. In Home Assistant, add the Wyoming integration.
2. Enter `<core-host-ip>` and port `10300`.
3. Confirm the ASR model appears (English model metadata).
4. Assign this STT provider in your Assist pipeline.

## Compatibility Path

The existing endpoint is unchanged:

```text
POST /api/audio
```

It still transcribes uploaded audio and returns text.

## Troubleshooting

- Port not reachable:
  - verify core is running and listening on `10300`
  - verify firewall/network access from HA host to core host
- Model file errors:
  - confirm files exist:
    - `core/asr/models/asr/model.int8.onnx`
    - `core/asr/models/asr/tokens.txt`
- Empty transcript:
  - check that HA is sending audio frames (`audio-start/chunk/stop`)
  - confirm incoming audio format is valid PCM after conversion
- Logs:
  - core startup logs print resolved ASR URI
  - ASR handler logs decode/event failures with stack traces

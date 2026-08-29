# Minimum Satellite Contract (protocol v1)

Every client implementation — `deskd/satellite.py` today, ESP32-S3 firmware
tomorrow — **MUST** satisfy this contract. The daemon is agnostic to which
client is connected. `scripts/conformance.py` exercises the daemon from a
client's perspective; firmware-phase adds a device-role mode.

## MUST implement

### 1. Handshake
* On connect, send `hello {device, fw, proto=1}` and wait for `welcome`.
* If a later `error proto_mismatch` arrives, display it; connection stays valid.

### 2. Audio uplink
* Stream raw PCM frames — **16 kHz, mono, s16-le** — as binary WS frames.
* Stream **only while recording** (after local PTT-down or during an armed
  listen-window voice activity). Never stream when muted.
* Frame size ≤ 8 KB per binary frame (daemon limit: 1 MiB total message).

### 3. Push-to-talk & follow-up window
* Emit `ptt down` when capture starts, `ptt up` when it ends.
* On `listen_window {seconds}`: arm voice-activity capture for that many
  seconds — on detected speech, synthesize `ptt down`, stream, and after
  ~1.2 s of trailing silence emit `ptt up`. Recommended gate: RMS > 500,
  silence threshold 1.2 s.

### 4. Speaker playback
* Buffer binary frames received between `tts_start` / `tts_stop` markers and
  play them in order at 16 kHz.
* On `abort`: **immediately drain** any buffered/queued audio (barge-in).
* Recommended: start playback only after ≥0.4 s is buffered OR on `tts_stop`,
  whichever first (prevents stutter).

### 5. Mute switch
* When muted: never send mic audio; if muted mid-turn, stop streaming.
* Send `mute {on:true|false}` so the daemon can reflect state.

### 6. Keepalive & tolerance
* Reply to `heartbeat` with an identical message (WS-level pings also run).
* Ignore unknown control types and unknown fields silently.
* Tolerate receiving messages in any order; only audio ordering matters.

## SHOULD implement (recommended UX)

* Display `transcript.text` ("what you heard") and `tts_start.text`
  (caption of what's being spoken).
* Map `state {to}` transitions to LED/audio-cue patterns:
  `idle` breathing · `listening` solid · `thinking` slow spin ·
  `speaking` pulse · plus `chime name=alert|confirm|error`.
* Announce `reminder {title}` with an alert chime before speaking.
* Reconnect with backoff on unexpected disconnect; re-handshake cleanly.
* Honor `mute` hardware/analog kill-switch independent of software state.

## MAY implement (optional capabilities)

* `--wave file` test injection instead of live mic.
* Local clock/idle screen; battery reporting; tamagotchi persona layer.
* On-device wake word (post-firmware phase): negotiated via hello caps in v2.

## Frozen protocol note

Protocol v1 is FROZEN (see docs/protocol.md). Additions require bumping
`proto` and negotiating at handshake. Bug-fixes to this contract are allowed;
behavioral breaks are not.

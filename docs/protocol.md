# Desk Secretary Protocol v1

> **STATUS: FROZEN** — v1 is feature-complete and stable. Any addition
> requires bumping `proto` and handshake negotiation. Clients must ignore
> unknown types/fields (see docs/satellite_contract.md).

Wire protocol between the ESP32-S3 satellite (or `mock_esp32.py`) and the
`deskd` daemon. Two transports carry the same semantics.

## Transports

| Transport | Control | Audio | Notes |
|---|---|---|---|
| WiFi WebSocket | text frames (NDJSON) | binary frames | primary |
| USB CDC serial | NDJSON lines (`\n`-terminated) | not carried in v1 | fallback / provisioning |

## Framing

### Control messages

JSON objects, one per text frame (WS) or one per line (serial).
Every message has a `"type"`. Unknown fields are ignored. Unknown types are
ignored with an optional `"error"` reply.

### Audio frames

Raw PCM: **16 kHz, mono, signed 16-bit little-endian**.
One binary frame = one chunk (~20 ms = 640 bytes recommended; any size accepted,
subject to WS max message size). Direction is implicit:

* device → daemon binary frame: microphone audio
* daemon → device binary frame: TTS audio to play

No headers inside audio frames in v1.

## Message catalog

### Full catalog (v1)

| Direction | Type | Purpose |
|---|---|---|
| → | `hello` | handshake |
| ← | `welcome` | handshake reply |
| → | `ptt` | push-to-talk down/up |
| → | `mute` | mic mute toggle |
| ⇄ | `heartbeat` | liveness ping/echo |
| ← | `state` | idle/listening/thinking/speaking |
| ← | `transcript` | STT result text |
| ← | `tts_start` / `tts_stop` | playback markers (+caption) |
| ← | binary frames | PCM audio (direction-implicit) |
| ← | `abort` | barge-in: flush speaker |
| ← | `listen_window` | arm VAC for N seconds |
| ← | `chime` | local tone alert |
| ← | `reminder` | upcoming reminder notice |
| ⇄ | `error` | protocol/app error |

### Handshake

Device → daemon immediately after connect:

```json
{"type":"hello","device":"esp32s3-satellite","fw":"0.1.0","proto":1}
```

Daemon replies once:

```json
{"type":"welcome","proto":1,"server":"deskd/0.1.0"}
```

If `proto` mismatches the daemon sends `welcome` with its own version and may
close. Devices must tolerate unknown fields.

### State machine (daemon → device)

```json
{"type":"state","to":"idle|listening|thinking|speaking"}
```

Sent on every transition. Device uses it for LED patterns.

### Push-to-talk (device → daemon)

```json
{"type":"ptt","event":"down"}
{"type":"ptt","event":"up"}
```

Mic streaming starts after `ptt down`, stops at `ptt up`.

### Mute switch (device → daemon)

```json
{"type":"mute","on":true}
```

### Barge-in / abort (daemon → device)

```json
{"type":"abort","reason":"barge-in"}
```

The device must **immediately** drain its speaker ring buffer and drop queued
audio. Sent when the user presses PTT while the assistant is speaking, or when
a reminder preempts playback.

### TTS playback markers (daemon → device)

```json
{"type":"tts_start","id":"t17","text":"optional sentence being spoken"}
{"type":"tts_stop","id":"t17"}
```

Binary TTS frames arrive between these markers, in order. `id` is monotonic.
`text` carries the sentence for display/captioning; devices may ignore it.

### Transcript (daemon → device)

```json
{"type":"transcript","text":"what the user said"}
```

Sent after STT completes, before the reply starts.

### Chime (daemon → device)

```json
{"type":"chime","name":"alert|confirm|error"}
```

Device plays a local short tone; no audio frames are sent for it.

### Reminders (daemon → device)

```json
{"type":"reminder","id":"r12","title":"Standup in 5","due":"2026-08-22T17:30:00"}
```

Followed by a `chime` and usually spoken text.

### Heartbeat (either direction)

```json
{"type":"heartbeat"}
```

Peer replies with the same type. WS keepalive pings run at the transport layer
in addition to this.

### Errors (either direction)

```json
{"type":"error","code":"bad_proto","message":"..."}
```

## Turn lifecycle

1. idle → user holds PTT → `ptt down`
2. daemon: state → `listening`; mic frames stream up
3. user releases → `ptt up`
4. daemon: state → `thinking`; STT runs, then LLM streams
5. first complete sentence → state → `speaking`, `tts_start`,
   binary frames, ... , `tts_stop` (pipelined per sentence)
6. done → state → `idle`

Barge-in: pressing PTT during step 5 sends `abort`, kills TTS + LLM stream,
returns to step 2.

## Versioning

`proto` field is an integer. Additive changes bump minor fields only; breaking
changes bump `proto`. Servers and devices must accept messages from their own
major proto and ignore unknown keys/types.

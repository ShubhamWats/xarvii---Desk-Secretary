#!/usr/bin/env python3
"""Protocol conformance suite — validates the daemon from a client's perspective.

Any satellite implementation (laptop mock, ESP32-S3 firmware) can reuse this
as its reference client. Exit code 0 iff all checks pass.

Usage:
    python scripts/conformance.py [--url ws://127.0.0.1:8765] [--wave file.wav]
"""

import argparse
import asyncio
import json
import sys
import wave


def load_wav_16k(path: str) -> bytes:
    import audioop

    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    if width != 2:
        raw = audioop.lin2lin(raw, width, 2)
    if ch == 2:
        raw = audioop.tomono(raw, 2, 0.5, 0.5)
    if rate != 16000:
        raw, _ = audioop.ratecv(raw, 2, 1, rate, 16000, None)
    return raw


class Checker:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def record(self, name: str, ok: bool, note: str = ""):
        self.results.append((name, ok, note))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {note}" if note else ""))

    def summary(self) -> bool:
        failed = [r for r in self.results if not r[1]]
        print("\n════════ CONFORMANCE", "PASS" if not failed else f"FAIL ({len(failed)})", "════════")
        return not failed


async def run_suite(url: str, wave_path: str | None, timeout: float = 60):
    import websockets

    ck = Checker()
    pcm = load_wav_16k(wave_path) if wave_path else b"\x01\x40" * 8000

    # ---- T1 handshake
    async with websockets.connect(url, max_size=1 << 20) as ws:
        await ws.send(json.dumps({"type": "hello", "device": "conformance",
                                  "fw": "conf-1", "proto": 1}))
        m = await asyncio.wait_for(ws.recv(), 10)
        welcome_ok = (not isinstance(m, (bytes, bytearray))
                      and json.loads(m).get("type") == "welcome"
                      and json.loads(m).get("proto") == 1)
        ck.record("T1 handshake hello→welcome proto1", welcome_ok)

        # ---- T2 unknown type tolerated
        await ws.send(json.dumps({"type": "totally_bogus_type", "x": 1}))
        await ws.send(json.dumps({"type": "heartbeat"}))
        seen_hb = False
        try:
            while True:
                m = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(m, (bytes, bytearray)):
                    continue
                if json.loads(m).get("type") == "heartbeat":
                    seen_hb = True
                    break
        except asyncio.TimeoutError:
            pass
        ck.record("T2 unknown-type tolerance + heartbeat echo", seen_hb)

        # ---- T3 full turn lifecycle
        states, captions, audio_frames, transcript = [], [], 0, None
        await ws.send(json.dumps({"type": "ptt", "event": "down"}))
        step = 3200
        for off in range(0, len(pcm), step):
            await ws.send(pcm[off : off + step])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "ptt", "event": "up"}))
        got_stop = False
        while True:
            m = await asyncio.wait_for(ws.recv(), timeout)
            if isinstance(m, (bytes, bytearray)):
                audio_frames += len(m)
                continue
            d = json.loads(m)
            t = d.get("type")
            if t == "state":
                states.append(d.get("to"))
            elif t == "transcript":
                transcript = d.get("text", "")
            elif t == "tts_start":
                captions.append(d.get("text", ""))
            elif t == "tts_stop":
                got_stop = True
                break
        seq_ok = ("listening" in states and "speaking" in states)
        ck.record("T3a turn state sequence",
                  seq_ok,
                  "->".join(states) + " (thinking optional on skill shortcuts)")
        ck.record("T3b transcript delivered", bool(transcript),
                  repr(transcript)[:60] if transcript else "")
        ck.record("T3c tts caption present", bool(captions))
        ck.record("T3d audible frames streamed", audio_frames >= 4000,
                  f"{audio_bytes_fmt(audio_frames)}")

        # ---- T4 abort frame accepted post-turn without breaking session
        await ws.send(json.dumps({"type": "abort", "reason": "conformance"}))
        await ws.send(json.dumps({"type": "heartbeat"}))
        hb_after_abort = False
        try:
            while True:
                m = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(m, (bytes, bytearray)):
                    continue
                if json.loads(m).get("type") == "heartbeat":
                    hb_after_abort = True
                    break
        except asyncio.TimeoutError:
            pass
        ck.record("T4 abort tolerated, session alive", hb_after_abort)

        # ---- T5 mute roundtrip doesn't break session
        await ws.send(json.dumps({"type": "mute", "on": True}))
        await ws.send(json.dumps({"type": "mute", "on": False}))
        await ws.send(json.dumps({"type": "heartbeat"}))
        hb_mute = False
        try:
            while True:
                m = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(m, (bytes, bytearray)):
                    continue
                if json.loads(m).get("type") == "heartbeat":
                    hb_mute = True
                    break
        except asyncio.TimeoutError:
            pass
        ck.record("T5 mute toggle session-safe", hb_mute)

        # ---- T6 listen_window offered after a conversational turn
        await ws.send(json.dumps({"type": "ptt", "event": "down"}))
        for off in range(0, len(pcm), step):
            await ws.send(pcm[off : off + step])
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"type": "ptt", "event": "up"}))
        window_seen = False
        try:
            while True:
                m = await asyncio.wait_for(ws.recv(), timeout)
                if isinstance(m, (bytes, bytearray)):
                    continue
                d = json.loads(m)
                if d.get("type") == "listen_window":
                    window_seen = int(d.get("seconds", 0)) > 0
                    break
                if d.get("type") == "tts_stop":
                    continue
        except asyncio.TimeoutError:
            pass
        ck.record("T6 follow-up listen_window offered", window_seen)

    return ck.summary()


def audio_bytes_fmt(n: int) -> str:
    return f"{n} bytes ({n/32000:.1f}s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--wave", default="tests/fixtures/reminder_query.wav", help="wav to speak; omit → tone fallback")
    opts = ap.parse_args()
    ok = asyncio.run(run_suite(opts.url, opts.wave))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

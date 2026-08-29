#!/usr/bin/env python3
"""Headless end-to-end check against a running deskd.

Streams a wav file as if spoken into the mic and verifies the daemon returns
a transcript, TTS captions and audible frames. No hardware or keyboard needed.

Usage: python scripts/e2e_check.py [--url ws://127.0.0.1:8765] --wave file.wav [--expect TEXT]
"""

import argparse
import asyncio
import json
import wave


def load_wav_16k(path: str) -> bytes:
    try:
        import audioop
    except ImportError:
        import audioop  # noqa

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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--wave", required=True)
    ap.add_argument("--expect", default="", help="substring expected in transcript")
    ap.add_argument("--timeout", type=float, default=60)
    opts = ap.parse_args()

    import websockets

    pcm = load_wav_16k(opts.wave)
    transcript = None
    captions: list[str] = []
    audio_bytes = 0
    states: list[str] = []

    async with websockets.connect(opts.url, max_size=1 << 20) as ws:
        await ws.send(json.dumps({"type": "hello", "device": "e2e-check", "fw": "t", "proto": 1}))
        while True:
            msg = await asyncio.wait_for(ws.recv(), opts.timeout)
            if isinstance(msg, (bytes, bytearray)):
                audio_bytes += len(msg)
                continue
            d = json.loads(msg)
            t = d.get("type")
            if t == "welcome":
                await ws.send(json.dumps({"type": "ptt", "event": "down"}))
                step = 3200
                for off in range(0, len(pcm), step):
                    await ws.send(pcm[off : off + step])
                    await asyncio.sleep(0.02)
                await ws.send(json.dumps({"type": "ptt", "event": "up"}))
            elif t == "transcript":
                transcript = d.get("text", "")
                print(f"[heard] {transcript!r}")
            elif t == "state":
                states.append(d.get("to"))
            elif t == "tts_start":
                captions.append(d.get("text", ""))
                print(f"[say]   {d.get('text', '')!r}")
            elif t == "tts_stop":
                break

    ok = True
    if not transcript:
        print("FAIL: no transcript received"); ok = False
    elif opts.expect and opts.expect.lower() not in transcript.lower():
        print(f"FAIL: transcript missing {opts.expect!r}"); ok = False
    if "speaking" not in states:
        print("FAIL: never reached speaking state"); ok = False
    if not captions:
        print("FAIL: no tts captions"); ok = False
    if audio_bytes < 10000:
        print(f"FAIL: only {audio_bytes} audio bytes"); ok = False

    print(f"captions={captions}")
    print(f"states={states} | audio: {audio_bytes} bytes ({audio_bytes/32000:.2f}s)")
    print("E2E PASS" if ok else "E2E FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

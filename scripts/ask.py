#!/usr/bin/env python3
"""Ask the desk secretary a spoken question without hardware.

Speaks `--text` through Piper → streams as mic audio → prints the reply.

    python scripts/ask.py "what are my reminders"
"""

import argparse
import asyncio
import json
import tempfile
import wave


async def gen_wav(text: str, path: str):
    import shutil

    voice = "~/.local/share/piper/voices/en_US-lessac-medium.onnx"
    piper = shutil.which("piper") or os.path.expanduser(
        "~/desk-secretary/.venv/bin/piper")
    proc = await asyncio.create_subprocess_exec(
        piper, "--model", os.path.expanduser(voice), "--output_file", path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate(text.encode() + b"\n")


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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--timeout", type=float, default=90)
    opts = ap.parse_args()

    import websockets

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    await gen_wav(opts.question, wav_path)
    pcm = load_wav_16k(wav_path)

    async with websockets.connect(opts.url, max_size=1 << 20) as ws:
        await ws.send(json.dumps({"type": "hello", "device": "asker",
                                  "fw": "a", "proto": 1}))
        said = []
        while True:
            m = await asyncio.wait_for(ws.recv(), opts.timeout)
            if isinstance(m, (bytes, bytearray)):
                continue
            d = json.loads(m)
            t = d.get("type")
            if t == "welcome":
                await ws.send(json.dumps({"type": "ptt", "event": "down"}))
                for off in range(0, len(pcm), 3200):
                    await ws.send(pcm[off : off + 3200])
                    await asyncio.sleep(0.02)
                await ws.send(json.dumps({"type": "ptt", "event": "up"}))
            elif t == "transcript":
                print(f"[heard] {d.get('text', '')!r}", flush=True)
            elif t == "tts_start":
                said.append(d.get("text", ""))
            elif t == "tts_stop":
                break
    print("[reply]", " ".join(said))
    return 0


import os  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

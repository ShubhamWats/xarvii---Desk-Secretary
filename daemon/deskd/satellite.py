#!/usr/bin/env python3
"""Virtual ESP32-S3 satellite: exercise deskd end-to-end without hardware.

Controls (terminal):
    ENTER / SPACE   toggle push-to-talk (start/stop speaking into mic)
    m               toggle mute switch
    q / ctrl-C      quit

Modes:
    default        live microphone via sounddevice
    --wave F.wav   play a wav file into the mic channel instead (great for tests)
    --no-audio     control-only, no capture/playback at all
"""

import argparse
import asyncio
import contextlib
import json
import sys
import threading
import wave

import numpy as np
from websockets.exceptions import ConnectionClosedOK

PROTO = 1


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


class SpeakerPlayer:
    """Plays incoming binary PCM frames; abort clears instantly (barge-in)."""

    PREBUFFER_BYTES = 16000 * 2 * 3 // 4     # ~0.75 s

    def __init__(self, device=None, enabled=True):
        self.enabled = enabled
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.stream = None
        if not enabled:
            return
        import sounddevice as sd

        self.stream = sd.OutputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            device=device,
            blocksize=1600,          # 100 ms blocks: tolerant of hiccups
            latency="high",          # prioritize glitch-free playback
            callback=self._callback,
        )

    def _callback(self, outdata, frames, time_info, status):
        need = frames * 2
        with self._lock:
            take = bytes(self._buf[:need])
            del self._buf[:need]
        if len(take) < need:
            take += b"\x00" * (need - len(take))
        outdata[:, 0] = np.frombuffer(take, dtype="<i2", count=frames)

    def feed(self, pcm: bytes):
        pcm = pcm[: len(pcm) & ~1]     # whole frames only (2-byte align)
        if not pcm:
            return
        if self.stream and not self.stream.active:
            with self._lock:
                enough = len(self._buf) + len(pcm) >= self.PREBUFFER_BYTES
            if enough:
                with contextlib.suppress(Exception):
                    self.stream.start()
        with self._lock:
            self._buf.extend(pcm)
            if len(self._buf) > 16000 * 2 * 30:
                del self._buf[: 16000]

    def start_now(self):
        """Force playback start (e.g. utterance finished buffering)."""
        if self.stream and not self.stream.active:
            with contextlib.suppress(Exception):
                self.stream.start()

    def abort(self):
        with self._lock:
            self._buf.clear()

    def pending_s(self) -> float:
        with self._lock:
            return len(self._buf) / 32000.0


class WaveMic:
    def __init__(self, path: str, speed: float = 1.0):
        with wave.open(path, "rb") as w:
            self.rate = w.getframerate()
            self.channels = w.getnchannels()
            self.width = w.getsampwidth()
            self.raw = w.readframes(w.getnframes())
        self.pcm = _to_16k_mono(self.raw, self.rate, self.channels, self.width)
        self.speed = max(0.1, speed)
        self.pos = 0
        eprint(f"[wave] {path}: {len(self.pcm)/32000:.1f}s of audio loaded")

    async def chunks(self, chunk_ms=100):
        step = 16000 * 2 * chunk_ms // 1000
        while self.pos < len(self.pcm):
            yield self.pcm[self.pos : self.pos + step]
            self.pos += step
            await asyncio.sleep(chunk_ms / 1000.0 / self.speed)


class LiveMic:
    def __init__(self, device=None):
        import sounddevice as sd

        self.queue: list[bytes] = []
        self.lock = threading.Lock()
        self.enabled = False
        self.stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            device=device,
            blocksize=800,
            callback=self._cb,
        )

    def _cb(self, indata, frames, time_info, status):
        if status:
            eprint(f"[mic] {status}")
        if not self.enabled:
            return
        with self.lock:
            self.queue.append(bytes(indata))

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.drain()

    def drain(self) -> bytes:
        with self.lock:
            data = b"".join(self.queue)
            self.queue.clear()
            return data


def _to_16k_mono(raw: bytes, rate: int, channels: int, width: int) -> bytes:
    try:
        import audioop

        if width != 2:
            raw = audioop.lin2lin(raw, width, 2)
        if channels == 2:
            raw = audioop.tomono(raw, 2, 0.5, 0.5)
        if rate != 16000:
            raw, _ = audioop.ratecv(raw, 2, 1, rate, 16000, None)
        return raw
    except ImportError:
        import array

        samples = array.array("h")
        usable = raw[: (len(raw) // 2) * 2]
        samples.frombytes(usable)
        step = channels
        mono = array.array("h", (samples[i] for i in range(0, len(samples), step)))
        n_out = int(len(mono) * 16000 / rate)
        out = array.array("h", bytearray(n_out * 2))
        for i in range(n_out):
            j = min(len(mono) - 1, int(i * rate / 16000))
            out[i] = mono[j]
        return out.tobytes()


async def keyboard_events(sink: asyncio.Queue):
    loop = asyncio.get_running_loop()
    if sys.stdin.isatty():
        import termios
        import tty

        old = termios.tcgetattr(sys.stdin.fileno())

        def read_keys():
            try:
                tty.setcbreak(sys.stdin.fileno())
                while True:
                    ch = sys.stdin.read(1)
                    loop.call_soon_threadsafe(sink.put_nowait, ("key", ch))
                    if ch == "q":
                        return
            finally:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)

        await loop.run_in_executor(None, read_keys)
    else:
        def read_lines():
            for line in sys.stdin:
                cmd = line.strip().lower()
                loop.call_soon_threadsafe(sink.put_nowait, ("key", cmd))
                if cmd == "q":
                    return

        await loop.run_in_executor(None, read_lines)


async def run(opts) -> None:
    import websockets
    from websockets.exceptions import ConnectionClosedOK

    speaker = SpeakerPlayer(device=opts.output, enabled=not opts.no_audio)
    mic = None
    wave_mic = None
    recording = False
    muted = False

    if opts.wave:
        wave_mic = WaveMic(opts.wave, opts.speed)
    elif not opts.no_audio:
        mic = LiveMic(device=opts.input)
        mic.stream.start()

    async with websockets.connect(opts.url, max_size=4 << 20) as ws:
        await ws.send(json.dumps({"type": "hello", "device": "mock-satellite",
                                  "fw": "mock", "proto": PROTO}))
        print(f"[mock] connected to {opts.url} — ENTER toggles talk, m mutes, q quits")

        keys = asyncio.Queue()
        state_holder = {"state": "boot"}
        stop = asyncio.Event()

        async def sender():
            nonlocal recording
            while True:
                if not recording:
                    await asyncio.sleep(0.05)
                    continue
                if wave_mic is not None:
                    async for chunk in wave_mic.chunks():
                        if not recording or stop.is_set():
                            break
                        await ws.send(chunk)
                    recording = False
                    await ws.send(json.dumps({"type": "ptt", "event": "up"}))
                elif mic is not None:
                    data = mic.drain()
                    for off in range(0, len(data), 3200):
                        await ws.send(data[off : off + 3200])
                    await asyncio.sleep(0.02)
                else:
                    await asyncio.sleep(0.05)

        async def receiver():
            nonlocal state_holder
            try:
                async for msg in ws:
                    if isinstance(msg, (bytes, bytearray)):
                        speaker.feed(msg)
                        continue
                    m = json.loads(msg)
                    t = m.get("type")
                    if t == "welcome":
                        if m.get("proto") != PROTO:
                            eprint(f"[mock] proto mismatch server={m.get('proto')}")
                    elif t == "state":
                        new = m.get("to")
                        if new != state_holder["state"]:
                            print(f"[state] {state_holder['state']} -> {new}",
                                  flush=True)
                            state_holder["state"] = new
                    elif t == "abort":
                        speaker.abort()
                        print(f"[abort] reason={m.get('reason')}"
                              " (speaker flushed)", flush=True)
                    elif t == "transcript_interim":
                        print(f'[live] {m.get("text", "")}', flush=True)
                    elif t == "transcript":
                        print(f'[heard] "{m.get("text", "")}"', flush=True)
                    elif t == "tts_start":
                        text = m.get("text")
                        label = f' "{text}"' if text else ""
                        print(f"[say]{label}", flush=True)
                    elif t == "tts_stop":
                        speaker.start_now()
                        print(f"[tts] stop id={m.get('id')} "
                              f"({speaker.pending_s():.1f}s buffered)", flush=True)
                    elif t == "chime":
                        print(f"[chime] {m.get('name')}", flush=True)
                    elif t == "reminder":
                        print(f"[reminder] {m.get('title')} due={m.get('due')}",
                              flush=True)
                    elif t == "listen_window":
                        secs = int(m.get("seconds", 10))
                        drain_wait = speaker.pending_s() + 0.35
                        print(f"[followup] listening in {drain_wait:.1f}s "
                              f"for {secs}s — just speak", flush=True)
                        asyncio.create_task(auto_talk(ws, secs, mic,
                                                      drain_wait=drain_wait,
                                                      speaker=speaker))
                    elif t == "heartbeat":
                        await ws.send(json.dumps({"type": "heartbeat"}))
                    elif t == "error":
                        print(f"[server-error] {m.get('code')}: "
                              f"{m.get('message')}", flush=True)
            finally:
                stop.set()
                print("[mock] disconnected from daemon", flush=True)

        async def auto_talk(ws, secs, mic_, drain_wait=0.0, speaker=None):
            import array as _array

            if mic_ is None:
                return
            # never listen to our own voice tail
            await asyncio.sleep(drain_wait)
            if speaker is not None and speaker.pending_s() > 0.05:
                await asyncio.sleep(speaker.pending_s() + 0.2)
            mic_.drain()                      # discard echo-tail audio
            mic_.set_enabled(True)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + secs
            speech_started = False
            silence = 0.0
            try:
                while loop.time() < deadline:
                    data = mic_.drain()
                    if data:
                        samples = _array.array("h")
                        samples.frombytes(data[: (len(data) // 2) * 2])
                        rms = ((sum(x * x for x in samples)
                                / max(1, len(samples))) ** 0.5) \
                            if len(samples) else 0
                        if rms > 500:
                            if not speech_started:
                                print("[followup] voice detected", flush=True)
                                await ws.send(json.dumps(
                                    {"type": "ptt", "event": "down"}))
                            speech_started = True
                            silence = 0.0
                            await ws.send(data)
                        elif speech_started:
                            silence += len(data) / 32000.0
                            await ws.send(data)
                            if silence > 1.2:
                                break
                    else:
                        await asyncio.sleep(0.02)
            finally:
                mic_.set_enabled(False)
                if speech_started:
                    await ws.send(json.dumps({"type": "ptt", "event": "up"}))
                    print("[followup] sent", flush=True)

        async def controller():
            nonlocal recording, muted
            while True:
                _, val = await keys.get()
                if val in ("q", "\x03"):
                    return
                if val in ("\r", "\n", " ", "t"):
                    if muted:
                        continue
                    recording = not recording
                    ev = "down" if recording else "up"
                    print(f"[ptt] {ev}", flush=True)
                    if mic is not None:
                        if recording:
                            mic.drain()
                            mic.set_enabled(True)
                        else:
                            mic.set_enabled(False)
                    await ws.send(json.dumps({"type": "ptt", "event": ev}))
                    if recording and wave_mic is not None:
                        wave_mic.pos = 0
                elif val == "m":
                    muted = not muted
                    print(f"[mute] {muted}", flush=True)
                    await ws.send(json.dumps({"type": "mute", "on": muted}))

        key_task = asyncio.create_task(keyboard_events(keys))
        tasks = [
            asyncio.create_task(receiver()),
            asyncio.create_task(controller()),
            asyncio.create_task(sender()),
            key_task,
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for d in tasks:
                if d.done():
                    exc = d.exception()
                    if exc and not isinstance(exc, (ConnectionClosedOK,
                                                    KeyboardInterrupt)):
                        eprint(f"[mock] task failed: {exc!r}")
        except KeyboardInterrupt:
            pass
        finally:
            for t_ in tasks:
                t_.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "ptt", "event": "up"}))

    if mic is not None and mic.stream:
        mic.stream.stop()
        mic.stream.close()
    if speaker.stream:
        speaker.stream.stop()
        speaker.stream.close()
    print("[mock] bye")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--wave", help="wav file to stream as microphone input")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--input", type=int, default=None, help="input device index")
    ap.add_argument("--output", type=int, default=None, help="output device index")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--list-devices", action="store_true")
    opts = ap.parse_args()

    if opts.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    try:
        asyncio.run(run(opts))
    except ConnectionRefusedError:
        eprint("cannot connect to daemon — is deskd running?")
        sys.exit(1)


if __name__ == "__main__":
    main()

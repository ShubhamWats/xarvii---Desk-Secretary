"""Microsoft Edge neural TTS (free, no key) decoded to 16 kHz PCM via PyAV."""

import asyncio
import io
import logging

log = logging.getLogger("deskd.tts.edge")


def mp3_to_pcm16k(mp3: bytes, target_rate: int = 16000) -> bytes:
    import av
    import array

    container = av.open(io.BytesIO(mp3))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=target_rate)
    out = bytearray()
    for frame in container.decode(audio=0):
        for rf in resampler.resample(frame):
            arr = array.array("h")
            arr.frombytes(bytes(rf.planes[0]))
            out.extend(arr.tobytes())
    return bytes(out)


class EdgeSpeaker:
    """edge-tts engine with the Piper-compatible synthesize/send_pcm interface."""

    def __init__(self, voice: str = "en-IN-NeerjaNeural", rate: str = "+0%"):
        self.voice = voice
        self.rate = rate
        self._gen = 0
        import edge_tts  # noqa: F401

    def abort(self) -> None:
        self._gen += 1

    async def synthesize(self, text: str) -> bytes | None:
        text = text.strip()
        if not text:
            return b""
        import edge_tts

        gen = self._gen
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        buf = bytearray()
        agen = communicate.stream()
        try:
            while True:
                # a stalled Microsoft endpoint must never hang playback
                chunk = await asyncio.wait_for(agen.__anext__(), timeout=15)
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
                if gen != self._gen:
                    return None
        except StopAsyncIteration:
            pass
        except asyncio.TimeoutError:
            log.warning("edge-tts stalled >15s; discarding partial audio")
            return None
        except Exception:
            log.exception("edge-tts synthesis failed")
            return None
        if gen != self._gen or not buf:
            return None if not buf else b""
        try:
            pcm = await asyncio.to_thread(mp3_to_pcm16k, bytes(buf))
        except Exception:
            log.exception("mp3 decode failed")
            return None
        # drop leading/trailing near-silence to avoid decode-tail crackle
        import array as _array
        import math as _math

        samples = _array.array("h")
        samples.frombytes(pcm[: (len(pcm) // 2) * 2])
        n = len(samples)
        if n == 0:
            return b""
        thresh = 300
        start = 0
        while start < n and abs(samples[start]) < thresh:
            start += 1
        end = n
        while end > start and abs(samples[end - 1]) < thresh:
            end -= 1
        start = max(0, start - 320)      # keep 20 ms natural fade
        end = min(n, end + 480)
        if end - start < 800:            # too tiny → silence only
            return b""
        trimmed = samples[start:end]
        log.debug("edge pcm trimmed %d -> %d", n, len(trimmed))
        return trimmed.tobytes()

    async def send_pcm(self, pcm: bytes, conn) -> bool:
        from ..protocol import FRAME_BYTES

        gen = self._gen
        for off in range(0, len(pcm), FRAME_BYTES * 20):
            if gen != self._gen:
                return False
            await conn.send_audio(pcm[off : off + FRAME_BYTES * 20])
            await asyncio.sleep(0)
        return True

    async def say(self, text: str, conn) -> None:
        pcm = await self.synthesize(text)
        if pcm:
            await self.send_pcm(pcm, conn)

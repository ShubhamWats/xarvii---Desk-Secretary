import asyncio
import contextlib
import io
import logging
from pathlib import Path
import os
import shutil
import wave

import httpx

from ..protocol import FRAME_BYTES
from ..textsplit import SentenceSplitter

log = logging.getLogger("deskd.tts")

PIPER_VOICES_DIR = Path(os.path.expanduser("~/.local/share/piper/voices"))


def resolve_voice_path(voice: str) -> str:
    """Bare name | filename | full path -> absolute .onnx path.

    Unknown bare names are auto-downloaded via the new piper catalog API.
    """
    v = os.path.expanduser(str(voice).strip())
    if not v:
        v = "en_US-lessac-medium"
    if v.endswith(".onnx") and os.path.isfile(v):
        return v
    name = v[:-5] if v.endswith(".onnx") else v
    cand = PIPER_VOICES_DIR / f"{name}.onnx"
    if cand.is_file():
        return str(cand)
    try:
        from piper import download_voices

        log.info("downloading piper voice %s …", name)
        return str(download_voices(name))
    except Exception as e:
        log.warning("could not download voice %s: %s", name, e)
        return str(cand)


class Speaker:
    async def say(self, text: str, conn) -> None:
        raise NotImplementedError

    def abort(self) -> None:
        pass


class NullSpeaker(Speaker):
    def __init__(self, beep: bool = True):
        self.beep = beep

    async def say(self, text: str, conn) -> None:
        log.info("[tts:null] %s", text)
        if self.beep and hasattr(conn, "send_json"):
            await conn.send_json({"type": "chime", "name": "confirm"})


def _wav_bytes_to_pcm16k(data: bytes, target_rate: int = 16000) -> bytes:
    with wave.open(io.BytesIO(data), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2 or channels not in (1, 2) or rate < 8000:
        raise ValueError("unsupported piper wav format")
    if channels == 2:
        frames = audioop_stereo_to_mono(frames)
    if rate != target_rate:
        frames = _resample(frames, rate, target_rate)
    return frames


def audioop_stereo_to_mono(frames: bytes) -> bytes:
    import array

    samples = array.array("h")
    samples.frombytes(frames[: (len(frames) // 2) * 2])
    mono = array.array("h", (samples[i] for i in range(0, len(samples), 2)))
    return mono.tobytes()


def _resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    try:
        import audioop

        out, _ = audioop.ratecv(pcm, 2, 1, src_rate, dst_rate, None)
        return out
    except ImportError:
        import array

        s = array.array("h")
        s.frombytes(pcm[: (len(pcm) // 2) * 2])
        n_out = int(len(s) * dst_rate / src_rate)
        out = array.array("h", bytearray(n_out * 2))
        for i in range(n_out):
            j = min(len(s) - 1, int(i * src_rate / dst_rate))
            out[i] = s[j]
        return out.tobytes()


class PiperSpeaker(Speaker):
    """Synthesizes sentences via the piper CLI subprocess.

    Each call spawns `piper -m voice -f -` feeding text on stdin and reading a
    WAV from stdout. abort() bumps a generation counter and kills the running
    process; in-flight say() calls check the generation between chunks.
    """

    def __init__(self, voice: str, length_scale: float = 1.0):
        self.length_scale = length_scale
        self._gen = 0
        self._proc: asyncio.subprocess.Process | None = None
        if not shutil.which("piper"):
            raise RuntimeError("piper executable not found on PATH")
        self.voice = resolve_voice_path(voice)

    def abort(self) -> None:
        self._gen += 1
        proc = self._proc
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def _synthesize(self, text: str, gen: int) -> bytes | None:
        cmd = ["piper", "--model", self.voice, "--output_file", "-"]
        log.debug("piper spawn: %s", " ".join(cmd))
        if self.length_scale != 1.0:
            cmd += ["--length-scale", str(self.length_scale)]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("piper disappeared from PATH")
            return None
        out, err = await self._proc.communicate(text.encode() + b"\n")
        if gen != self._gen:
            return None
        if not out:
            log.error("piper produced no audio (rc=%s): %s",
                      self._proc.returncode, err.decode()[-300:])
        else:
            log.debug("piper done rc=%s wav=%dB", self._proc.returncode, len(out))
        return out

    async def synthesize(self, text: str) -> bytes | None:
        """Synthesize text to 16 kHz mono PCM, or None if aborted/failed."""
        text = text.strip()
        if not text:
            return b""
        gen = self._gen
        wav = await self._synthesize(text, gen)
        if wav is None or not wav:
            return None
        try:
            pcm = _wav_bytes_to_pcm16k(wav)
        except Exception:
            log.exception("failed to decode piper output")
            return None
        if gen != self._gen:
            return None
        return pcm

    async def send_pcm(self, pcm: bytes, conn) -> bool:
        gen = self._gen
        log.debug("streaming tts pcm=%dB gen=%d", len(pcm), gen)
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


class StreamedTtsPipeline:
    """Feeds LLM deltas sentence-by-sentence to a Speaker for low TTFA.

    Synthesis of the NEXT sentence overlaps playback of the current one, so
    the device never waits on a fresh piper process between sentences.
    """

    def __init__(self, speaker: Speaker, conn, min_sentence_len: int = 12):
        self.speaker = speaker
        self.conn = conn
        self.splitter = SentenceSplitter(min_sentence_len)
        self._aborted = False
        self._tid = 0
        self._pending: tuple[str, asyncio.Task] | None = None
        self._can_prefetch = hasattr(speaker, "synthesize")

    def abort(self):
        self._aborted = True
        self.speaker.abort()
        if self._pending:
            self._pending[1].cancel()
            self._pending = None

    @property
    def aborted(self) -> bool:
        return self._aborted

    async def feed(self, delta: str) -> None:
        if self._aborted:
            return
        for sentence in self.splitter.feed(delta):
            await self._say(sentence)

    async def finish(self) -> None:
        if self._aborted:
            return
        for sentence in self.splitter.flush():
            await self._enqueue(sentence)
        await self._flush_pending()

    async def _enqueue(self, sentence: str) -> None:
        if not sentence.strip() or self._aborted:
            return
        if not self._can_prefetch:
            await self._say_legacy(sentence)
            return
        if self._pending is not None:
            await self._flush_pending()
        if self._aborted:
            return
        task = asyncio.create_task(self.speaker.synthesize(sentence))
        self._pending = (sentence, task)

    async def _flush_pending(self) -> None:
        if self._pending is None:
            return
        sentence, task = self._pending
        self._pending = None
        pcm = await task
        if self._aborted or not pcm:
            return
        await self._emit(sentence, pcm)

    async def _say_legacy(self, sentence: str) -> None:
        self._tid += 1
        caption = sentence.strip()[:400]
        await self.conn.send_json({"type": "tts_start", "id": self._tid, "text": caption})
        try:
            await self.speaker.say(sentence, self.conn)
        finally:
            with contextlib.suppress(Exception):
                await self.conn.send_json({"type": "tts_stop", "id": self._tid})

    async def _emit(self, sentence: str, pcm: bytes) -> None:
        self._tid += 1
        caption = sentence.strip()[:400]
        await self.conn.send_json({"type": "tts_start", "id": self._tid, "text": caption})
        try:
            sent = True
            if hasattr(self.speaker, "send_pcm"):
                sent = await self.speaker.send_pcm(pcm, self.conn)
            else:
                await self.speaker.say(sentence, self.conn)
        finally:
            if sent:
                with contextlib.suppress(Exception):
                    await self.conn.send_json({"type": "tts_stop", "id": self._tid})

    async def _say(self, sentence: str) -> None:
        await self._enqueue(sentence)
        await self._flush_pending()


async def warm_piper_check(voice: str) -> bool:
    return bool(shutil.which("piper")) and bool(voice)


def make_speaker(cfg) -> Speaker:
    eng = cfg.tts.engine.lower()
    if eng in ("none", "null"):
        return NullSpeaker()
    if eng == "piper":
        try:
            return PiperSpeaker(cfg.tts.voice, cfg.tts.length_scale)
        except RuntimeError as e:
            log.warning("%s; using null speaker", e)
            return NullSpeaker()
    if eng == "edge":
        from .edge_tts import EdgeSpeaker

        return EdgeSpeaker(cfg.tts.voice or "en-IN-NeerjaNeural")
    if eng == "openai":
        from .openai_tts import OpenAiSpeaker

        spk_cfg = getattr(cfg.tts, "openai_base_url", None)
        return OpenAiSpeaker(
            base_url=spk_cfg or "https://api.openai.com/v1",
            api_key_env=getattr(cfg.tts, "openai_api_key_env", None) or "OPENAI_API_KEY",
            voice=getattr(cfg.tts, "openai_voice", "alloy"))
    raise ValueError(f"unknown tts engine {eng!r}")

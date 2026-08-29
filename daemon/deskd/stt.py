import asyncio
import io
import logging
import os

import httpx

log = logging.getLogger("deskd.stt")


class SttEngine:
    async def transcribe(self, pcm16k: bytes, language: str = "en") -> str:
        raise NotImplementedError


class EchoStt(SttEngine):
    """Test engine: returns a canned phrase regardless of audio."""

    def __init__(self, phrase: str = "what are my tasks for today"):
        self.phrase = phrase

    async def transcribe(self, pcm16k: bytes, language: str = "en") -> str:
        log.info("EchoStt: %d bytes -> canned phrase", len(pcm16k))
        return self.phrase


class WhisperLocalStt(SttEngine):
    def __init__(self, model: str = "small", compute_type: str = "int8"):
        self.model_name = model
        self.compute_type = compute_type
        self._model = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self):
        async with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("loading faster-whisper model %s (%s)", self.model_name, self.compute_type)
                loop = asyncio.get_running_loop()
                self._model = await loop.run_in_executor(
                    None,
                    lambda: WhisperModel(self.model_name, device="auto", compute_type=self.compute_type),
                )

    async def transcribe(self, pcm16k: bytes, language: str = "en") -> str:
        await self._ensure_model()
        import numpy as np

        audio = np.frombuffer(pcm16k, dtype=np.int16).astype("float32") / 32768.0
        loop = asyncio.get_running_loop()

        def _run():
            segments, info = self._model.transcribe(audio, language=language, beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()

        return await loop.run_in_executor(None, _run)


class OpenAiCompatStt(SttEngine):
    """Works with OpenAI and Groq /audio/transcriptions endpoints."""

    def __init__(self, base_url: str, api_key_env: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.model = model

    async def transcribe(self, pcm16k: bytes, language: str = "en") -> str:
        if not self.api_key:
            raise RuntimeError(f"missing API key env {self.model!r} provider key")
        buf = io.BytesIO()
        import wave

        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm16k)
        buf.seek(0)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": ("audio.wav", buf, "audio/wav")},
                data={"model": self.model, "language": language},
            )
            r.raise_for_status()
            return r.json().get("text", "").strip()


def make_stt(cfg) -> SttEngine:
    eng = cfg.stt.engine.lower()
    if eng == "echo":
        return EchoStt()
    if eng in ("faster-whisper", "whisper", "local-whisper"):
        try:
            import faster_whisper  # noqa: F401

            return WhisperLocalStt(cfg.stt.model, cfg.stt.compute_type)
        except ImportError:
            log.warning("faster-whisper not installed; falling back to echo STT")
            return EchoStt()
    if eng in ("openai", "groq", "openai-compat"):
        return OpenAiCompatStt(cfg.stt.base_url, cfg.stt.api_key_env, cfg.stt.api_model)
    raise ValueError(f"unknown stt engine {eng!r}")

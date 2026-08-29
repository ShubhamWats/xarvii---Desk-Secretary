"""OpenAI TTS engine — /audio/speech with response_format=pcm (16 kHz, no decode)."""

import logging
import os

import httpx

from ..protocol import FRAME_BYTES

log = logging.getLogger("deskd.tts.openai")

VALID_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")


class OpenAiSpeaker:
    def __init__(self, base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY",
                 model: str = "tts-1", voice: str = "alloy"):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.api_key_env = api_key_env
        self.model = model
        self.voice = voice if voice in VALID_VOICES else "alloy"
        self._gen = 0

    def abort(self) -> None:
        self._gen += 1

    async def synthesize(self, text: str) -> bytes | None:
        text = text.strip()
        if not text:
            return b""
        if not self.api_key:
            log.warning("openai tts skipped: %s not set", self.api_key_env)
            return b""
        gen = self._gen
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{self.base_url}/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "voice": self.voice,
                        "input": text[:4000],
                        "response_format": "pcm",
                    },
                )
                r.raise_for_status()
                pcm = r.content
        except Exception:
            log.exception("openai tts failed")
            return None
        if gen != self._gen:
            return None
        return pcm

    async def send_pcm(self, pcm: bytes, conn) -> bool:
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

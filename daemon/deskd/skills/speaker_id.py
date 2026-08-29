"""Speaker identification via resemblyzer embeddings. Owner vs guest."""

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("deskd.speakerid")


class SpeakerID:
    def __init__(self, threshold: float = 0.72,
                 state_file: str = "~/.local/state/desk-secretary/voice.json"):
        self.threshold = threshold
        self.path = Path(state_file).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._encoder = None
        self.centroid = None
        self._load()

    def _ensure_encoder(self):
        if self._encoder is None:
            from resemblyzer import VoiceEncoder

            self._encoder = VoiceEncoder()
        return self._encoder

    def _load(self):
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
                if data.get("centroid"):
                    self.centroid = np.asarray(data["centroid"], dtype=np.float32)
            except Exception:
                log.exception("speaker state load failed")

    def save_centroid(self, vec: np.ndarray):
        self.centroid = np.asarray(vec, dtype=np.float32)
        self.path.write_text(json.dumps({"centroid": self.centroid.tolist()}))

    def enrolled(self) -> bool:
        return self.centroid is not None

    def embed_pcm16k(self, pcm: bytes, rate: int = 16000) -> np.ndarray | None:
        """pcm: s16-le mono → normalized speaker embedding."""
        try:
            import librosa

            audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
            audio = audio.astype(np.float32) / 32768.0
            if rate != 16000:
                audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
            if len(audio) < 16000 * 2:
                return None
            enc = self._ensure_encoder()
            return enc.embed_utterance(audio)
        except Exception:
            log.exception("embed failed")
            return None

    def verify(self, pcm: bytes, rate: int = 16000):
        """Returns (is_owner: bool|None, score). None = cannot judge."""
        emb = self.embed_pcm16k(pcm, rate)
        if emb is None or self.centroid is None:
            return None, 0.0
        score = float(np.dot(emb, self.centroid) /
                      ((np.linalg.norm(emb) * np.linalg.norm(self.centroid)) or 1))
        return score >= self.threshold, round(score, 3)

    def reset(self):
        self.centroid = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

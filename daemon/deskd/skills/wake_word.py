"""Optional always-on wake word via openWakeWord. Default OFF; guarded import."""

import asyncio
import logging
import time

log = logging.getLogger("deskd.wakeword")


class WakeWordDetector:
    """Feed 16 kHz mono PCM frames (bytes); returns True once on detection."""

    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.5,
                 cooldown_s: float = 2.0):
        self.model_name = model
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._last_fire = 0.0
        self._model = None
        self._chunk = 1280          # openwakeword expects 80 ms chunks @16k

    def _ensure_model(self):
        if self._model is None:
            import numpy as np
            from openwakeword.model import Model

            self._np = np
            self._model = Model(wakeword_models=[self.model_name])
        return self._model

    def feed(self, pcm: bytes) -> bool:
        try:
            model = self._ensure_model()
        except Exception as e:
            log.warning("wake word unavailable: %s", e)
            self._model = None
            return False
        import numpy as np

        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
        fired = False
        step = self._chunk
        for off in range(0, len(samples), step):
            scores = model.predict(samples[off : off + step])
            for v in scores.values():
                if v >= self.threshold and time.time() - self._last_fire > self.cooldown_s:
                    self._last_fire = time.time()
                    model.reset()
                    fired = True
                    break
        return fired


async def idle_listener(device_session, detector, stop: asyncio.Event, poll_s=0.05):
    """Consume mic frames routed by DeviceSession while state == 'idle'."""
    buf = bytearray()
    while not stop.is_set():
        frame = await device_session.next_idle_audio(poll_s)
        if frame is None:
            continue
        buf.extend(frame)
        while len(buf) >= 3200:
            chunk = bytes(buf[:3200])
            del buf[:3200]
            if await asyncio.to_thread(detector.feed, chunk):
                return True
    return False

import array
import math

from ..protocol import FRAME_BYTES


def rms(pcm: bytes) -> float:
    usable = pcm[: (len(pcm) // 2) * 2]
    if not usable:
        return 0.0
    samples = array.array("h")
    samples.frombytes(usable)
    acc = 0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / len(samples))


class UtteranceTrimmer:
    def __init__(self, sample_rate: int = 16000, threshold: float = 250.0,
                 min_duration_s: float = 0.35, pad_ms: int = 120):
        self.rate = sample_rate
        self.threshold = threshold
        self.min_samples = int(min_duration_s * sample_rate)
        self.pad_bytes = int(pad_ms * sample_rate / 1000) * 2

    def trim(self, pcm: bytes) -> bytes:
        step = FRAME_BYTES
        n = len(pcm) // step
        first = last = -1
        for i in range(n):
            if rms(pcm[i * step : (i + 1) * step]) > self.threshold:
                if first < 0:
                    first = i
                last = i
        if first < 0 or (last - first + 1) * self.rate * 2 // (1000 // 20) < self.min_samples:
            return b""
        start = max(0, first * step - self.pad_bytes)
        end = min(len(pcm), (last + 1) * step + self.pad_bytes)
        return pcm[start:end]

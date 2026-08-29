import re

_BOUNDARY = re.compile(r"[.!?…]+[\"'”’)\]]*\s|\n+")
_OPEN, _CLOSE = "<think>", "</think>"


class ThinkFilter:
    """Streaming suppressor for <think>...</think> reasoning blocks."""

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, delta: str) -> str:
        self.buf += delta
        out = []
        while True:
            if self.inside:
                idx = self.buf.find(_CLOSE)
                if idx < 0:
                    keep = min(len(self.buf), len(_CLOSE) - 1)
                    self.buf = self.buf[len(self.buf) - keep:] if keep else ""
                    break
                self.buf = self.buf[idx + len(_CLOSE):]
                self.inside = False
            else:
                idx = self.buf.find(_OPEN)
                if idx < 0:
                    keep = min(len(self.buf), len(_OPEN) - 1)
                    emit_len = len(self.buf) - keep
                    if emit_len > 0:
                        out.append(self.buf[:emit_len])
                        self.buf = self.buf[emit_len:]
                    break
                out.append(self.buf[:idx])
                self.buf = self.buf[idx + len(_OPEN):]
                self.inside = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self.inside else self.buf
        self.buf = ""
        return rest


class SentenceSplitter:
    def __init__(self, min_len: int = 12):
        self.min_len = min_len
        self.buf = ""

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out: list[str] = []
        while True:
            m = _BOUNDARY.search(self.buf)
            if not m:
                break
            cand = self.buf[: m.end()].strip()
            rest = self.buf[m.end() :]
            if len(cand) >= self.min_len or "\n" in self.buf[: m.end()]:
                if cand:
                    out.append(cand)
                self.buf = rest
            else:
                break
        return out

    def flush(self) -> list[str]:
        rest = self.buf.strip()
        self.buf = ""
        return [rest] if rest else []

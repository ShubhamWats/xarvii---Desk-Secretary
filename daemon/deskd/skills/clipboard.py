"""Clipboard sense: detect new long text/URLs while idle, offer a spoken TL;DR."""

import asyncio
import logging
import re
import time

log = logging.getLogger("deskd.clipboard")


def read_clipboard() -> str:
    for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"]):
        try:
            out = subprocess_run(cmd)
            if out:
                return out
        except Exception:
            continue
    return ""


def subprocess_run(cmd) -> str:
    import subprocess

    r = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
    return r.stdout.strip()


_URL = re.compile(r"https?://\S+")


class ClipboardSense:
    def __init__(self, enabled=True, poll_s=3.0, min_len=120):
        self.enabled = enabled
        self.poll_s = poll_s
        self.min_len = min_len
        self.last_seen = ""
        self.pending: dict | None = None   # {"text":..., "ts":...}
        self._task = None

    def start(self):
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        self.last_seen = await asyncio.to_thread(read_clipboard) or ""
        while True:
            await asyncio.sleep(self.poll_s)
            try:
                current = await asyncio.to_thread(read_clipboard) or ""
            except Exception:
                continue
            if not current or current == self.last_seen or len(current) < self.min_len:
                self.last_seen = current or self.last_seen
                continue
            self.last_seen = current
            is_url = bool(_URL.fullmatch(current.split()[0] if current.split() else ""))
            self.pending = {"text": current[:4000], "url": is_url,
                            "ts": time.time()}
            log.info("clipboard: new %s payload (%d chars)",
                     "URL" if is_url else "text", len(current))

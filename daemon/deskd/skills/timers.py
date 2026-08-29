"""Kitchen timers distinct from reminders: announce, re-chime every 15s until dismissed."""

import asyncio
import logging
import re
import time
import uuid

_WORDNUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
             "twenty": 20, "thirty": 30}


def parse_timer(text: str):
    """Return (name, duration_seconds) or None."""
    t = text.lower()
    if not re.search(r"\btimer\b|\bcountdown\b", t):
        return None

    m = re.search(
        r"(?:set|start)\s*(?:a|an)?\s*(?:timer|countdown)\s*"
        r"(?:for\s+|of\s+)?(.+?)"
        r"(?:\s+(?:named|called)\s+([a-z ]{2,30}))?$",
        t)
    if not m:
        # "start an egg timer" style with implicit label
        m2 = re.search(r"(?:start|set)\s+.*?\b([a-z]{3,20})\s+timer\b", t)
        if not m2:
            return None
        body, name = "", m2.group(1)
    else:
        body, name = m.group(1) or "", (m.group(2) or "").strip()

    dm = re.search(
        r"(?:for\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|"
        r"twenty|thirty|forty ?five)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)", body)
    if not dm:
        if name and name != "Timer":
            return None
        return None
    n_raw, unit = dm.groups()
    n = int(n_raw) if n_raw.isdigit() else _WORDNUMS.get(n_raw.replace(" ", ""), 0)
    mult = 60
    for k, v in (("second", 1), ("sec", 1), ("min", 60), ("h", 3600)):
        if unit.startswith(k):
            mult = v
            break
    seconds = max(5, n * mult)

    label_m = re.search(r"\bfor\s+(?:my\s+|the\s+)?([a-z][a-z ]{2,30})$", t)
    if label_m and not re.search(r"\d", label_m.group(1)):
        name = label_m.group(1).strip()
    return (name or "Timer").strip(), seconds


class TimerManager:
    def __init__(self, on_event):
        self.on_event = on_event          # async fn(name, repeat: bool)
        self.active: dict[str, dict] = {}
        self._task = None

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def start_timer(self, name: str, seconds: float) -> str:
        tid = uuid.uuid4().hex[:6]
        self.active[tid] = {"name": name, "ends": time.time() + max(5, seconds),
                            "dismissed": False, "count": 0}
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        return tid

    def dismiss_all(self) -> int:
        n = 0
        now = time.time()
        for info in self.active.values():
            if not info["dismissed"]:
                info["dismissed"] = True
                if "ends" in info and now >= info["ends"]:
                    n += 1
        for tid in [t for t, i in list(self.active.items())
                    if i["dismissed"] and "ends" in i and now - i["ends"] > 120]:
            self.active.pop(tid, None)
        return n

    def describe(self) -> str:
        live = []
        for i in self.active.values():
            if i["dismissed"] or "ends" not in i:
                continue
            rem = max(0, int(i["ends"] - time.time()))
            live.append(f"{i['name']}: {rem // 60}:{rem % 60:02d} left")
        return "; ".join(live)

    async def _loop(self):
        while True:
            await asyncio.sleep(1)
            now = time.time()
            for tid, info in list(self.active.items()):
                if info["dismissed"]:
                    continue
                since = now - info["ends"]
                if since < 0:
                    continue
                due_announce = (info["count"] == 0) or (since >= info["count"] * 15)
                if due_announce and info["count"] < 10:
                    info["count"] += 1
                    try:
                        await self.on_event(info["name"], repeat=info["count"] > 1)
                    except Exception:
                        logging.getLogger("deskd.timers").exception(
                            "timer event failed (count=%d)", info["count"])

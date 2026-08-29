from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("deskd.reminders")

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WORD_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
              "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "forty-five": 45}
_DUR_RE = re.compile(
    r"\b(?:(in|after)\s+)?"
    r"(half an hour|an hour|\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|fifteen|twenty|thirty|forty five|forty-five)\s*"
    r"(seconds?|secs?|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\b"
    r"(?:\s*(?:later))?",
    re.IGNORECASE)
_AT_RE = re.compile(
    r"(?:\bat\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b|(?:\bat\s+)?(\d{3,4})\s*(?:hours|hrs|am|pm)?",
    re.IGNORECASE)


def _normalize_time_text(text: str) -> str:
    t = text
    t = re.sub(r"\b(\d{1,2})[.](\d{2})\b", r"\1:\2", t)
    def _compact(m):
        digits = m.group(1)
        hh, mm = digits[:-2], digits[-2:]
        if int(hh) <= 23 and int(mm) <= 59:
            return f"{int(hh)}:{mm}"
        return digits
    t = re.sub(r"\b(\d{3,4})\b(?=\s*(?:hours|hrs|am|pm|$))", _compact, t)
    return t


def _word_num(tok: str):
    tok = tok.lower().strip()
    if tok == "half an hour":
        return 30
    if tok == "an hour":
        return 60
    return _WORD_NUMS.get(tok)


def parse_when_ex(text: str, now: datetime | None = None):
    """Returns (datetime | None, matched_time_span | None)."""
    now = now or datetime.now()
    t = _normalize_time_text(text.strip().lower())

    hm = re.search(r"\b(half\s+an\s+hour|an\s+hour)\b(\s*(?:later))?", t)
    if hm:
        mins = 30 if "half" in hm.group(1) else 60
        return now + timedelta(minutes=mins), hm.span()
    m = _DUR_RE.search(t)
    if m:
        raw_n = m.group(2)
        n = _word_num(raw_n) if raw_n and not raw_n.isdigit() else int(raw_n)
        if n is None:
            return None, None
        unit = m.group(3).lower()
        for k, v in (("second", 1), ("sec", 1), ("min", 60), ("m", 60),
                     ("hour", 3600), ("hr", 3600), ("h", 3600),
                     ("day", 86400), ("d", 86400), ("week", 604800), ("w", 604800)):
            if unit.startswith(k):
                return now + timedelta(seconds=n * v), m.span()
        return now + timedelta(seconds=n * 60), m.span()

    try:
        dt = datetime.fromisoformat(t)
        return dt, (0, len(t))
    except ValueError:
        pass

    day_offset = 0
    span = None
    if "tomorrow" in t:
        day_offset = 1
        idx = t.index("tomorrow")
        span = (idx, idx + len("tomorrow"))
        t = t.replace("tomorrow", "").strip()
    for wd in _WEEKDAYS:
        if wd in t:
            delta = (now.weekday() - _WEEKDAYS.index(wd)) % 7
            day_offset = delta or 7
            idx = t.index(wd)
            span = (idx, idx + len(wd))
            t = t.replace(wd, "").strip()
            break

    m = _AT_RE.search(t)
    if m and (m.group(1) is not None or m.group(4) is not None):
        if m.group(1) is not None:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            ampm = (m.group(3) or "").lower()
        else:
            hhmm = m.group(4)
            hour, minute = int(hhmm[:-2]), int(hhmm[-2:])
            ampm = ""
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        if ampm == "" and hour <= 7 and ("evening" in t or "tonight" in t):
            hour += 12
        if span is None:
            span = m.span()
    elif day_offset == 0 and not any(k in t for k in ("today", "tonight")):
        return None, None
    else:
        hour = None
        minute = None

    target = (now + timedelta(days=day_offset)).replace(
        hour=hour if hour is not None else 9,
        minute=minute if minute is not None else 0,
        second=0,
        microsecond=0,
    )
    if day_offset == 0 and target <= now and hour is not None:
        target += timedelta(days=1)
    if target <= now:
        target = now + timedelta(minutes=1)
    return target, span


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    return parse_when_ex(text, now)[0]




class ReminderStore:
    def __init__(self, path):
        self.path = Path(os.path.expanduser(str(path)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items = {}
        self._load()

    def _load(self):
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text())
                self._items = {item["id"]: item for item in data}
            except Exception:
                log.exception("failed to load reminders; starting empty")
                self._items = {}

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self._items.values()), indent=1))
        tmp.replace(self.path)

    def add(self, title, due):
        rid = f"r{int(due.timestamp()*1000) % 10**10:010d}{len(self._items)%100:02d}"
        item = {"id": rid, "title": str(title),
                "due": due.isoformat(timespec="seconds"), "fired": False}
        self._items[rid] = item
        self._save()
        return item

    def list(self, pending_only: bool = True):
        items = sorted(self._items.values(), key=lambda i: i["due"])
        if pending_only:
            items = [i for i in items if not i.get("fired")]
        return items

    def remove(self, rid):
        if rid in self._items:
            del self._items[rid]
            self._save()
            return True
        return False

    def due_now(self, now=None):
        now = now or datetime.now()
        out = []
        for item in self._items.values():
            if item.get("fired"):
                continue
            if datetime.fromisoformat(item["due"]) <= now:
                item["fired"] = True
                out.append(item)
        if out:
            self._save()
        return out


class ReminderManager:
    def __init__(self, store, on_due=None, poll_s: float = 5.0):
        self.store = store
        self.on_due = on_due
        self.poll_s = poll_s
        self._task = None

    def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while True:
            await asyncio.sleep(self.poll_s)
            try:
                for item in self.store.due_now():
                    log.info("reminder due: %s", item["title"])
                    if self.on_due:
                        await self.on_due(item)
            except Exception:
                log.exception("reminder loop error")

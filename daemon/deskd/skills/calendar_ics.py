"""Google Calendar read-only via the secret iCal address. No OAuth needed."""

import logging
import re
from datetime import datetime, timedelta
from urllib.request import urlopen

log = logging.getLogger("deskd.calendar")

_ICS_URL_RE = re.compile(r"^https://calendar\.google\.com/calendar/ical/[^ ]+\.ics$")


def _parse_events(ics_text: str, day_start: datetime, day_end: datetime) -> list[dict]:
    events = []
    blocks = re.split(r"(?=BEGIN:VEVENT)", ics_text)
    for block in blocks:
        if not block.startswith("BEGIN:VEVENT"):
            continue
        summary = re.search(r"SUMMARY[^:]*:(.+)", block)
        dtstart = re.search(r"DTSTART(?:;[^:]*)?:(\d{8}(?:T\d{6}Z?)?)", block)
        if not (summary and dtstart):
            continue
        raw = dtstart.group(1)
        try:
            if "T" in raw:
                start = datetime.strptime(raw.rstrip("Z"), "%Y%m%dT%H%M%S")
            else:
                start = datetime.strptime(raw[:8], "%Y%m%d")
        except ValueError:
            continue
        if day_start <= start < day_end:
            events.append({"time": start, "title": summary.group(1).strip()})
    events.sort(key=lambda e: e["time"])
    return events


def events_for_day(ics_url: str, which: str = "today") -> list[dict] | None:
    """which: today | tomorrow."""
    if not ics_url or not _ICS_URL_RE.match(ics_url):
        return None
    now = datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if which == "tomorrow":
        day_start += timedelta(days=1)
    day_end = day_start + timedelta(days=1)
    try:
        with urlopen(ics_url, timeout=15) as resp:
            text = resp.read().decode(errors="replace")
    except Exception as e:
        log.warning("calendar fetch failed: %s", e)
        return None
    return _parse_events(text, day_start, day_end)


def spoken_summary(events: list[dict], which: str) -> str:
    if not events:
        return f"You have no events {which}."
    parts = []
    for e in events[:5]:
        parts.append(f"{e['time'].strftime('%I:%M %p').lstrip('0')} {e['title']}")
    more = f", and {len(events) - 5} more." if len(events) > 5 else "."
    return f"You have {len(events)} event{'s' if len(events) > 1 else ''} {which}: " + \
        "; ".join(parts) + more

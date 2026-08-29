"""Media + system control via standard Linux tools (playerctl, pactl, brightnessctl)."""

import asyncio
import logging
import re
import shutil
import subprocess

log = logging.getLogger("deskd.media")


async def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        return proc.returncode == 0, out.decode().strip() or err.decode().strip()
    except FileNotFoundError:
        return False, f"{cmd[0]} not installed"


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


# ------------------------------------------------------------------- media

_MEDIA_VERBS = {
    "pause": ["pause"], "stop": ["pause"], "resume": ["play"], "play": ["play"],
    "next": ["next"], "skip": ["next"], "previous": ["previous"],
}


def parse_media(text: str) -> str | None:
    t = text.lower().strip(" ?!")
    for verb in ("pause", "resume", "skip", "next", "previous"):
        if re.search(rf"\b(please\s+)?{verb}\b(?=[^.]*\b(music|song|track|media|video|player)\b)", t):
            return {"skip": "next", "previous": "previous"}.get(verb, verb)
    if re.fullmatch(r"(?:please\s+)?play", t):
        return "play"
    return None


async def media_action(action: str) -> str:
    if not _has("playerctl"):
        return "Media control needs playerctl. Install it with: sudo apt install playerctl."
    ok, out = await _run(["playerctl"] + _MEDIA_VERBS.get(action, [action]))
    verb_text = {"play": "Playing", "pause": "Paused", "next": "Skipped",
                 "previous": "Went back"}.get(action, action)
    return verb_text + "." if ok else f"Couldn't {action} — no active player found."


# ------------------------------------------------------------------ volume

def parse_volume(text: str):
    t = text.lower()
    m = re.search(r"\b(?:volume|sound)\b.*?\b(?:(up|down|mute|unmute)|(\d{1,3})\s*(?:percent|%)?)\b", t)
    if not m:
        if re.fullmatch(r"(?:please\s+)?(?:turn|crank)\s+(?:the\s+)?volume\s+(?:up|down)", t):
            return ("up" if "up" in t else "down"), None
        if re.search(r"\bmute\b", t) and "volume" in t:
            return "mute", None
        return None
    if m.group(1):
        return m.group(1), None
    pct = max(0, min(100, int(m.group(2))))
    return "set", pct


async def volume_action(op: str, pct=None) -> str:
    if not _has("pactl"):
        return "Volume control needs pactl (usually preinstalled)."
    if op == "up":
        ok, _ = await _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"])
    elif op == "down":
        ok, _ = await _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"])
    elif op == "mute":
        ok, _ = await _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        return "Toggled mute." if ok else "Couldn't toggle mute."
    elif op == "set":
        ok, _ = await _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@",
                            f"{pct}%"])
        return f"Volume set to {pct} percent." if ok else "Couldn't set volume."
    else:
        return "Didn't catch that volume command."
    return "Volume up." if op == "up" else "Volume down." if ok else "Couldn't change volume."


# --------------------------------------------------------------- brightness

def parse_brightness(text: str):
    t = text.lower()
    m = re.search(r"\bbrightness\b.*?(up|down|\d{1,3})?", t)
    if "brightness" not in t:
        return None
    val = m.group(1)
    if val in (None, ""):
        return ("down" if any(w in t for w in ("reduce", "lower", "dim")) else "up"), None
    if val in ("up", "down"):
        return val, None
    try:
        return "set", max(10, min(100, int(val)))
    except ValueError:
        return None


async def brightness_action(op: str, pct=None) -> str:
    if not _has("brightnessctl"):
        return "Brightness control needs brightnessctl: sudo apt install brightnessctl."
    if op == "set":
        ok, _ = await _run(["brightnessctl", "set", f"{pct}%"])
        return f"Brightness set to {pct} percent." if ok else "Couldn't set brightness."
    delta = "+10%" if op == "up" else "10%-"
    ok, _ = await _run(["brightnessctl", "set", delta])
    return "Brightness up." if op == "up" else "Brightness down." if ok else "Couldn't change brightness."


# ----------------------------------------------------------------- open app

_APP_MAP = {
    "browser": ["xdg-open", "http://google.com"], "chrome": ["chromium"],
    "vs code": ["code"], "vscode": ["code"], "editor": ["gedit"],
    "calculator": ["gnome-calculator"], "files": ["nautilus"],
    "terminal": ["gnome-terminal"], "settings": ["gnome-control-center"],
    "spotify": ["spotify"], "obsidian": ["obsidian"],
}


def parse_open(text: str) -> str | None:
    m = re.search(r"\bopen\s+([a-z][a-z0-9 ]{1,20}?)(?:\s+for me)?[\s?.!]*$", text.lower())
    if not m:
        return None
    app = m.group(1).strip()
    for k in _APP_MAP:
        if k in app:
            return k
    return app


async def open_app(app_key: str) -> str:
    cmd = _APP_MAP.get(app_key, [app_key])
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True)
        await asyncio.sleep(0.3)
        if proc.returncode is None or proc.returncode == 0:
            return f"Opening {app_key}."
        return f"Tried to open {app_key}, but it didn't launch."
    except Exception as e:
        return f"Couldn't open {app_key}: {e}"

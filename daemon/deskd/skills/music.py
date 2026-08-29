"""Music control matrix: {spotify, ytmusic} × {api, basic}.

  spotify/api    → spotipy (guarded import) + Spotify Connect play/queue
  spotify/basic  → playerctl targeting the spotify desktop player
  ytmusic/api    → ytmusicapi search → open browser deep-link (free)
  ytmusic/basic  → open YTM search URL in default browser
"""

import logging
import re
import webbrowser

log = logging.getLogger("deskd.music")


def parse_play(text: str):
    """'play lo-fi beats on youtube music' → (query, provider|None)."""
    t = text.lower().strip()
    if not re.match(r"^\s*play\b", t) or "on my" in t:
        return None
    provider = None
    m = re.search(r"\bon (spotify|youtube music|yt music|youtube)\b", t)
    if m:
        raw = m.group(1)
        provider = "spotify" if "spotify" in raw else "ytmusic"
        t = t[: m.start()] + t[m.end():]
        # don't leak the provider words into the search query
    query = re.sub(r"^\s*play\s+", "", t).strip(" ?!.")
    query = re.sub(r"\b(on|from)\s*$", "", query).strip()
    if not query:
        return None
    return query, provider


class MusicController:
    def __init__(self, provider="ytmusic", mode="basic"):
        self.provider = provider
        self.mode = mode

    async def play(self, query: str) -> str:
        if self.provider == "ytmusic":
            return await self._ytmusic(query)
        if self.provider == "spotify":
            if self.mode == "api":
                return await self._spotify_api(query)
            return await self._playerctl_play(query)
        return await self._ytmusic(query)

    # ---------------------------------------------------------------- ytmusic

    async def _ytmusic(self, query: str) -> str:
        if self.mode == "api":
            try:
                from ytmusicapi import YTMusic

                yt = YTMusic()          # public browse; no auth for search
                results = yt.search(query, filter="songs", limit=1)
                if results:
                    video_id = results[0].get("videoId", "")
                    title = results[0].get("title", query)
                    url = f"https://music.youtube.com/watch?v={video_id}"
                    webbrowser.open(url)
                    return f"Playing {title} on YouTube Music."
            except Exception as e:
                log.warning("ytmusic api failed (%s); falling back to URL", e)
        import urllib.parse

        q = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://music.youtube.com/search?q={q}")
        return f"Opening YouTube Music results for {query}."

    # ---------------------------------------------------------------- spotify

    async def _spotify_api(self, query: str) -> str:
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
        except ImportError:
            return "Spotify API mode needs the spotipy package."
        scopes = ("user-read-playback-state user-modify-playback-state "
                  "streaming user-read-currently-playing")
        try:
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scopes))
            res = sp.search(q=query, type="track", limit=1)
            track = res["tracks"]["items"][0]
            devices = sp.devices()["devices"]
            if not devices:
                return "No active Spotify device found — start playback once, then retry."
            sp.start_playback(device_id=devices[0]["id"], uris=[track["uri"]])
            artists = ", ".join(a["name"] for a in track["artists"])
            return f"Playing {track['name']} by {artists}."
        except Exception as e:
            log.warning("spotify api failed: %s", e)
            return f"Spotify API failed: {e}"

    async def _playerctl_play(self, _query: str) -> str:
        import asyncio
        from .media import _has

        if not _has("playerctl"):
            return "Basic music control needs playerctl installed."
        proc = await asyncio.create_subprocess_exec(
            "playerctl", "play", "--player=spotify",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
        return "Resuming Spotify." if proc.returncode == 0 else \
            "Spotify isn't running — start it first."


# ------------------------------------------------------------------ expenses

_EXP_RE = re.compile(
    r"\b(?:spent|i spent|add expense|expense)\s+"
    r"(?:rs\.?|₹|inr)?\s*(\d+(?:\.\d+)?)\s*(?:on|for)\s+(.+?)[.?!]*$",
    re.IGNORECASE)


def parse_expense(text: str):
    m = _EXP_RE.search(text.strip())
    if not m:
        return None
    return float(m.group(1)), m.group(2).strip()


_MONTH_TOTALS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:rs\.?|₹)?\s*[-–]\s*(.+)", re.I)


def parse_ledger_totals(ledger_text: str) -> float | None:
    total = 0.0
    found = False
    month = None
    for line in ledger_text.splitlines():
        lm = re.search(r"^#+\s*(\w+ \d{4})", line)
        if lm:
            month = lm.group(1)
        em = _MONTH_TOTALS.match(line.strip())
        if em and month == datetime_month():
            total += float(em.group(1))
            found = True
    return total if found else None


def datetime_month():
    from datetime import datetime

    return datetime.now().strftime("%B %Y")


def parse_month_query(text: str) -> bool:
    return bool(re.search(r"\b(expenses|spent this month|monthly spend)\b",
                          text.lower()))

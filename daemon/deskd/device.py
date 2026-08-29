import asyncio
import asyncio
import logging
import contextlib
from typing import Optional

from .protocol import PROTO_VERSION, chime, error, reminder_msg, state, tts_start, tts_stop, welcome

log = logging.getLogger("deskd.device")


class DeviceSession:
    """Bridges one transport connection to a Conversation."""

    def __init__(self, conn, conversation_factory, server):
        self.conn = conn
        self.conv = conversation_factory(self)
        self.server = server
        self.device = "unknown"
        self.closed = False
        self.speak_lock = asyncio.Lock()
        self.state = "boot"
        self._recv_task = None
        self.muted = False

    async def run(self):
        self._recv_task = asyncio_create_task(self._loop())
        try:
            await self._recv_task
        except Exception:
            log.exception("session crashed")
        finally:
            self.closed = True
            self.conv.cancel()
            self.server.remove_session(self)

    async def _loop(self):
        while not self.closed:
            frame = await self.conn.recv()
            if frame is None:
                log.info("device %s disconnected", self.device)
                break
            if isinstance(frame, bytes):
                if self.state == "listening":
                    self.conv.feed_audio(frame)
                rec = getattr(self.server, "meeting_rec", None)
                if rec is not None:
                    rec.feed(frame)
                continue
            await self._dispatch(frame)

    async def _dispatch(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "hello":
            self.device = str(msg.get("device", "unknown"))
            proto = int(msg.get("proto", 0))
            log.info("hello from %s (proto %d)", self.device, proto)
            await self.conn.send_json(welcome("deskd/0.1.0"))
            if proto != PROTO_VERSION:
                await self.conn.send_json(error("proto_mismatch", f"server proto {PROTO_VERSION}"))
            await self.set_state("idle")
        elif mtype == "ptt":
            event = msg.get("event")
            if event == "down" and not self.muted:
                await self.conv.on_ptt_down(self)
            elif event == "up":
                await self.conv.on_ptt_up(self)
        elif mtype == "mute":
            self.muted = bool(msg.get("on"))
            if self.muted:
                self.conv.cancel()
                if self.state in ("listening", "speaking"):
                    await self.send_json({"type": "abort", "reason": "muted"})
                    await self.set_state("idle")
        elif mtype == "heartbeat":
            await self.conn.send_json({"type": "heartbeat"})
        elif mtype == "error":
            log.warning("device error: %s %s", msg.get("code"), msg.get("message"))
        elif mtype in ("state", "welcome", "abort", "chime", "reminder", "tts_start", "tts_stop"):
            pass
        else:
            log.debug("ignoring message type %r", mtype)

    @contextlib.asynccontextmanager
    async def speech_slot(self):
        """Serialize TTS playback so concurrent announcements queue cleanly."""
        async with self.speak_lock:
            yield

    async def send_json(self, msg: dict) -> None:
        if not self.closed:
            await self.conn.send_json(msg)

    async def set_state(self, to: str) -> None:
        if to != self.state and not self.closed:
            self.state = to
            await self.conn.send_json(state(to))

    async def speak_frame_stream(self, pcm: bytes) -> None:
        self._tts_id = getattr(self, "_tts_id", 0)
        await self.conn.send_json(tts_start(self._tts_id))
        try:
            for off in range(0, len(pcm), 6400):
                await self.conn.send_audio(pcm[off : off + 6400])
        finally:
            await self.conn.send_json(tts_stop(self._tts_id))
            self._tts_id += 1

    async def chime(self, name: str) -> None:
        await self.conn.send_json(chime(name))

    async def announce_reminder(self, item: dict) -> None:
        await self.conn.send_json(reminder_msg(item["id"], item["title"], item["due"]))
        await self.chime("alert")

    async def dispatch_reminder_intent(self, title: str, due) -> None:
        await self.server.confirm_reminder(self, title, due)

    # ------------------------------------------------ skill delegations

    @property
    def timers(self):
        return self.server.timers

    async def start_timer(self, name: str, seconds: float) -> None:
        self.server.timers.start_timer(name, seconds)
        await self.chime("confirm")
        await self.conv._speak_plain(
            self, f"Timer set for {name} for {int(seconds) // 60 or ''}"
                  f"{'' if int(seconds) >= 60 else int(seconds)} "
                  f"{'minutes' if int(seconds) >= 60 else 'seconds'}.")

    async def ask_weather(self, place: str):
        from .skills.weather import weather_report

        cfg = self.server.cfg
        return await weather_report(place or cfg.owner.location,
                                    cfg.owner.latitude, cfg.owner.longitude)

    async def do_media(self, action: str) -> str:
        from .skills.media import media_action

        return await media_action(action)

    async def do_volume(self, op: str, pct=None) -> str:
        from .skills.media import volume_action

        return await volume_action(op, pct)

    async def do_brightness(self, op: str, pct=None) -> str:
        from .skills.media import brightness_action

        return await brightness_action(op, pct)

    async def do_open(self, app_key: str) -> str:
        from .skills.media import open_app

        return await open_app(app_key)

    async def ask_calendar(self, which_day: str):
        ics = self.server.cfg.calendar.ics_url
        if not ics:
            return None
        from .skills.calendar_ics import events_for_day, spoken_summary

        events = events_for_day(ics, which_day)
        return spoken_summary(events, which_day) if events is not None else None

    async def ask_gmail(self):
        g = self.server.cfg.gmail
        from .skills.gmail_imap import spoken_digest, unread_digest

        result = unread_digest(g.host, g.user, g.password_env, g.max_unread)
        if result is None:
            return "Gmail isn't configured. Add your account and app password in settings."
        return spoken_digest(result, g.max_unread)

    async def ask_briefing(self, which_day="today") -> str:
        from .skills.briefing import compose

        return await compose(self.server, which_day)

    async def read_screen(self):
        from .skills.screen_read import capture_and_describe

        return await capture_and_describe(self.server.router,
                                          self.server.context_builder, "")

    async def ask_standup(self, repos):
        from .skills.standup import generate

        repos = repos or getattr(self.server.cfg, "standup_repos", [])
        return await generate(self.server.router, self.server.vault, repos,
                              self.server.cfg.owner.name)

    def pop_clipboard_offer(self):
        return self.server.pop_clipboard_offer()

    async def verify_speaker(self, pcm):
        return await asyncio.to_thread(self.server.verify_speaker, pcm)

    async def start_meeting(self) -> str:
        return self.server.meetings_start()

    async def stop_meeting(self) -> str:
        return await self.server.meetings_stop()

    async def log_expense(self, amount: float, what: str) -> str:
        return self.server.expense_add(amount, what)

    async def expenses_total(self):
        return await asyncio.to_thread(self.server.expense_total)

    async def do_music(self, query: str) -> str:
        from .skills.music import MusicController

        m = self.server.cfg.music
        ctl = MusicController(provider=m.provider, mode=m.mode)
        return await ctl.play(query)

    async def begin_journal(self) -> None:
        js = self.server.begin_journal()
        await self.chime("confirm")
        await self.conv._speak_plain(self, js.next_prompt())

    async def do_ha(self, kind, entity_or_scene, on: bool) -> str:
        return await self.server.ha_action(kind, entity_or_scene, on)

    async def ask_rag(self, query: str):
        return await self.server.ask_rag(query)

    async def summarize_clipboard(self, payload) -> str | None:
        text = payload.get("text", "")
        tier = self.server.router.tier_for(approx_tokens=len(text) // 4)
        provider = self.server.router.resolve(self.server.cfg.llm.tiers[tier])
        parts = []
        prefix = ("Summarize this web page content in 3 short spoken sentences."
                  if payload.get("url") else
                  "Summarize this clipboard content in 3 short spoken sentences.")
        async for delta in provider.stream([
                {"role": "system", "content": prefix},
                {"role": "user", "content": text}]):
            parts.append(delta)
        return "".join(parts).strip() or None

    # ------------------------------------------------ follow-up window

    async def offer_followup(self, seconds: int) -> None:
        self.conv._followup = True
        try:
            if not self.closed:
                await self.conn.send_json({"type": "listen_window", "seconds": seconds})
        except Exception:
            pass
        finally:
            await self.set_state("idle")

    async def summarize_reminders(self) -> Optional[str]:
        return await self.server.summarize_reminders()


def asyncio_create_task(coro):
    import asyncio

    return asyncio.create_task(coro)

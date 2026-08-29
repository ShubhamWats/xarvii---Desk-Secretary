import asyncio
import contextlib
import logging
import os
import signal
import threading
from datetime import datetime
from pathlib import Path

from .config import Cfg, apply_demo_overrides, load_config
from .context import build_context
from .conversation import Conversation, _try_reminder_intent
from .device import DeviceSession
from .integrations.notify import desktop_notify
from .skills.timers import TimerManager
from .skills.clipboard import ClipboardSense
from .skills.rules_engine import RulesEngine
from .skills.home_assistant import HomeAssistant
from .skills.meetings import MeetingRecorder
from .integrations.obsidian import make_vault
from .llm.router import Router
from .scheduler.reminders import ReminderManager, ReminderStore, parse_when
from .stt import make_stt
from .transports.usb_serial import find_esp32_port, open_serial_connection
from .transports.ws_server import DeviceWsServer
from .tts.piper_tts import make_speaker

log = logging.getLogger("deskd.server")


class DeskServer:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.vault = make_vault(cfg)
        self.reminder_store = ReminderStore(cfg.resolved_reminders_path())
        self.reminders = ReminderManager(self.reminder_store, on_due=self._on_reminder_due)
        self.timers = TimerManager(on_event=self._on_timer_event)
        self.rules = RulesEngine(
            Path("~/.config/desk-secretary/rules.json").expanduser(),
            on_alert=self._on_rule_alert,
            interval_minutes=cfg.rules.interval_minutes)
        self.clipboard = ClipboardSense(enabled=cfg.clipboard.enabled)

        from .skills.rag import RagIndex
        from .skills.speaker_id import SpeakerID

        vault_path = getattr(self.vault, "vault", None)
        self.rag = RagIndex(vault_path,
                            Path("~/.local/state/desk-secretary/rag.sqlite").expanduser(),
                            model=cfg.rag.model, top_k=cfg.rag.top_k) \
            if vault_path else None
        self.speaker_id = SpeakerID(threshold=cfg.speaker_id.threshold)
        self.ha = HomeAssistant(cfg.homeassistant.enabled,
                                cfg.homeassistant.url, cfg.homeassistant.token_env,
                                webhook_url=cfg.webhook.url)
        self.meeting_rec = MeetingRecorder(cfg.meetings.dir)
        self._journal = None
        if self.rag:
            asyncio.create_task(self._rag_loop())
        self.clipboard_offer: dict | None = None

        from .skills.persona import Persona

        self.persona = Persona(
            owner_name=getattr(cfg.owner, "name", ""),
            quirks=getattr(cfg.persona, "quirks", True))
        self.stt = make_stt(cfg)
        self.router = Router(cfg)

        state = {"current": None}

        def speaker_factory():
            if state["current"] is not None:
                return state["current"]
            return make_speaker(cfg)

        self._set_live_speaker_ref = state
        self.speaker_factory = speaker_factory

        from .tools.registry import build_native_registry

        self.registry = build_native_registry(cfg, self.vault, self.reminder_store)
        context = lambda: build_context(cfg, self.vault, self.reminder_store)  # noqa: E731

        def conversation_factory(dev):
            return Conversation(cfg, self.stt, self.router, speaker_factory,
                                context, tools=self.registry, vault=self.vault)

        self.conversation_factory = conversation_factory
        self.sessions: list[DeviceSession] = []
        self.ws_server = DeviceWsServer(cfg.server.ws_host, cfg.server.ws_port, self._on_client)
        self._serial_conn = None
        self._ctl_server = None
        self._stop = asyncio.Event()

    async def start(self):
        await self.ws_server.start()
        if self.cfg.server.serial_enabled:
            port = self.cfg.server.serial_path or find_esp32_port()
            if port:
                conn = await open_serial_connection(port, self.cfg.server.serial_baud)
                if conn:
                    log.info("serial device on %s", port)
                    self._spawn_session(conn)
        from .ctl import ControlApi

        api = ControlApi(self)
        self._ctl_server = await api.start()
        self.reminders.start()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass
        asyncio.create_task(self._warm_llm())
        asyncio.create_task(self._inbox_sweep_loop())
        self.timers.start()
        if self.cfg.rules.enabled:
            self.rules.start()

        from .dashboard import Dashboard

        self.dashboard = Dashboard(self, self.cfg)
        self.dashboard.start()

        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
            import socket

            self._zeroconf = Zeroconf()
            ip = socket.inet_aton(self._lan_ip())
            inst = f"xarvii-{socket.gethostname()}" \
                .replace(" ", "-").lower()
            self._zc_info = ServiceInfo(
                "_xarvii._tcp.local.",
                f"{inst}._xarvii._tcp.local.",
                server=f"{inst}.local.",
                addresses=[ip], port=int(self.cfg.server.ws_port),
                properties={"proto": "1"})
            def _register():
                threading.current_thread().name = "mdns-reg"
                self._zeroconf.register_service(self._zc_info)
                log.info("mDNS: xarvii service registered")

            threading.Thread(target=_register, daemon=True,
                             name="mdns-reg").start()
            log.info("mDNS: advertising xarvii service on LAN")
        except Exception as e:
            log.warning("mDNS advertisement failed: %s: %s",
                        type(e).__name__, e)
        from .plugins import load_plugins

        n_plug = load_plugins(self.registry,
                              getattr(self.cfg.plugins, "dir", ""),
                              ctx=self)
        if n_plug:
            log.info("%d plugin(s) loaded (%d tools total)",
                     n_plug, len(self.registry.names()))
        asyncio.create_task(self.timers_watchdog())
        if self.cfg.telegram.enabled:
            from .skills.telegram_bot import run_bot

            asyncio.create_task(run_bot(self.cfg.telegram.token_env,
                                        self.cfg.telegram.allowed_user_ids))
        if self.cfg.briefing.enabled:
            asyncio.create_task(self._briefing_loop())
        self.clipboard.start()
        log.info(
            "deskd ready | ws=%s:%d ctl=%s:%d stt=%s tts=%s demo=%s",
            self.cfg.server.ws_host, self.cfg.server.ws_port,
            self.cfg.server.ctl_host, self.cfg.server.ctl_port,
            type(self.stt).__name__, type(self.speaker_factory()).__name__, self.cfg.demo,
        )

    def _lan_ip(self) -> str:
        import socket as _s

        s_ = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        try:
            s_.connect(("8.8.8.8", 80))
            return s_.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s_.close()

    def verify_speaker(self, pcm: bytes):
        return self.speaker_id.verify(pcm)

    async def ask_rag(self, query: str) -> str | None:
        if not self.rag:
            return None
        hits = await asyncio.to_thread(self.rag.search_sync, query)
        if not hits:
            return None
        ctx = "\n\n".join(f"[{h['file']} · {h['heading']}]\n{h['body'][:600]}"
                           for h in hits)
        tier = self.router.tier_for(has_images=False, approx_tokens=len(ctx) // 4 + len(query) // 4)
        provider = self.router.resolve(self.cfg.llm.tiers[tier])
        parts = []
        system = ("You answer strictly from the user's Obsidian notes below. "
                  "Cite filenames like (from file.md). Spoken-word friendly.")
        async for delta in provider.stream(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"Notes:\n{ctx}\n\nQuestion: {query}"}]):
            parts.append(delta)
        return "".join(parts).strip()

    async def _rag_loop(self):
        while True:
            try:
                n = await self.rag.rebuild_if_stale(self.cfg.rag.rebuild_minutes * 60)
                if n is not None and self.vault:
                    log.info("rag ready (%s chunks)", n)
            except Exception:
                log.exception("rag build failed")
            await asyncio.sleep(300)

    async def _inbox_sweep_loop(self):
        while True:
            try:
                if self.vault is not None:
                    n = self.vault.sweep_expired_inbox(max_age_days=7)
                    if n:
                        log.info("swept %d expired inbox tasks", n)
            except Exception:
                log.exception("inbox sweep failed")
            await asyncio.sleep(3600)

    async def _warm_llm(self):
        """Preload the default LLM into RAM so the first voice reply is fast."""
        try:
            provider_str = self.cfg.llm.tiers.get("fast", "")
            if not provider_str.startswith("ollama/"):
                return
            model = provider_str.split("/", 1)[1]
            import httpx

            async with httpx.AsyncClient(timeout=300) as client:
                await client.post(
                    f"{self.cfg.llm.providers['ollama']['base_url']}/api/generate",
                    json={"model": model, "keep_alive": "30m"},
                )
            log.info("llm warmup done (%s)", model)
        except Exception:
            log.warning("llm warmup failed (will load on first use)")

    async def run_until_stopped(self):
        await self._stop.wait()

    def meetings_start(self) -> str:
        label = self.meeting_rec.start()
        return f"Meeting mode on. I'm recording; say 'stop recording' when done. ({label})"

    async def meetings_stop(self) -> str:
        wav = self.meeting_rec.stop()
        if wav is None:
            return "No meeting recording was active."
        await asyncio.sleep(0)
        from .skills.meetings import transcribe_and_extract

        spoken = await transcribe_and_extract(
            wav, self.stt, self.router, self.vault, self.cfg.meetings.dir)
        return spoken or "Meeting processed."

    def expense_add(self, amount: float, what: str) -> str:
        if self.vault is None:
            return "No vault configured for the ledger."
        from .skills.journal import append_expense

        append_expense(self.vault, self.cfg.expenses.ledger_note, amount, what)
        self.persona.note_task_done()
        return f"Logged {amount:g} rupees for {what}."

    def expense_total(self):
        from .skills.journal import month_total

        p = Path(self.cfg.expenses.ledger_note).expanduser()
        if not p.is_absolute():
            vault = getattr(self.vault, "vault", None)
            p = (vault / self.cfg.expenses.ledger_note) if vault else p
        return month_total(p)

    def begin_journal(self):
        from .skills.journal import JournalSession

        self._journal = JournalSession(
            self.vault, self.cfg.journal.dir, owner_name=self.cfg.owner.name)
        return self._journal

    async def ha_action(self, kind, entity_or_scene, on: bool) -> str:
        if self.ha.mode is None:
            return ("Home Assistant isn't configured. Add its URL and a "
                    "long-lived token via xarvii setup.")
        try:
            if kind == "scene":
                ok = await self.ha.scene(entity_or_scene)
                return "Scene activated." if ok else "Scene failed."
            ok = await self.ha.switch(entity_or_scene, on)
            state_word = "on" if on else "off"
            return f"{entity_or_scene.split('.')[0].capitalize()} turned {state_word}." \
                if ok else "Command sent to Home Assistant."
        except Exception as e:
            return f"Home Assistant call failed: {e}"

    async def _on_rule_alert(self, rule: dict):
        spoken = f"Watch trigger: {rule.get('message')}"
        val = rule.get("last_value")
        if val:
            spoken += f" Current value: {val}."
        log.info("rule alert: %s", spoken)
        first = next(iter(self.sessions), None)
        if first:
            with contextlib.suppress(Exception):
                await first.chime("alert")
                await first.conv._speak_plain(first, spoken)
        else:
            desktop_notify("Xarvii rule", spoken)

    async def _on_timer_event(self, name: str, repeat: bool):
        spoken = (f"Timer for {name} is done!" if not repeat
                  else f"Still waiting on the {name} timer.")
        await self.broadcast(lambda s: s.chime("alert"))
        first = next(iter(self.sessions), None)
        if first:
            with contextlib.suppress(Exception):
                await first.conv._speak_plain(first, spoken)
        else:
            desktop_notify("Xarvii timer", spoken)

    async def timers_watchdog(self):
        """Dismiss expired timers once the user presses PTT or speaks."""
        while True:
            await asyncio.sleep(2)
            if not self.sessions:
                continue
            sess = next(iter(self.sessions))
            if sess.state == "listening":
                if self.timers.dismiss_all():
                    log.info("timers dismissed by user activity")

    def pop_clipboard_offer(self):
        offer, self.clipboard_offer = self.clipboard_offer, None
        return offer

    async def answer_text(self, question: str) -> str:
        """Text-in/text-out brain for telegram & friends."""
        approx = len(question) // 4
        tier = self.router.tier_for(has_images=False, approx_tokens=approx)
        provider = self.router.resolve(self.cfg.llm.tiers[tier])
        messages = [{"role": "system",
                     "content": build_context(self.cfg, self.vault,
                                              self.reminder_store)}]
        parts = []
        async for delta in provider.stream(messages +
                                           [{"role": "user", "content": question}]):
            parts.append(delta)
        return "".join(parts).strip()

    async def _briefing_loop(self):
        import datetime as dt

        target_hm = getattr(self.cfg, "briefing").time
        done_day = ""
        while True:
            try:
                now = dt.datetime.now()
                hh, mm = (int(x) for x in target_hm.split(":")[:2])
                today = now.strftime("%Y-%m-%d")
                window_start = now.replace(hour=hh, minute=mm, second=0)
                if done_day != today and window_start <= now < window_start + dt.timedelta(minutes=10):
                    done_day = today
                    spoken = await self.ask_briefing_text("today")
                    first = next(iter(self.sessions), None)
                    if first:
                        with contextlib.suppress(Exception):
                            await first.conv._speak_plain(first, spoken)
                    else:
                        desktop_notify("Morning briefing", spoken[:200])
            except Exception:
                log.exception("briefing loop failed")
            await asyncio.sleep(60)

    async def ask_briefing_text(self, which="today"):
        from .skills.briefing import compose

        return await compose(self, which)

    async def shutdown(self):
        self.reminders.on_due = None
        await self.reminders.stop()
        for s in list(self.sessions):
            s.conv.cancel()
            try:
                await s.conn.close()
            except Exception:
                pass
        if getattr(self, "_zeroconf", None):
            with contextlib.suppress(Exception):
                self._zeroconf.unregister_service(self._zc_info)
                self._zeroconf.close()
        if getattr(self, "dashboard", None):
            with contextlib.suppress(Exception):
                self.dashboard.stop()
        await self.ws_server.stop()
        if self._ctl_server:
            self._ctl_server.close()
            await self._ctl_server.wait_closed()

    async def _on_client(self, conn):
        session = DeviceSession(conn, self.conversation_factory, self)
        self.sessions.append(session)
        await session.run()

    def _spawn_session(self, conn):
        session = DeviceSession(conn, self.conversation_factory, self)
        self.sessions.append(session)
        asyncio.create_task(session.run())

    def remove_session(self, session: DeviceSession):
        if session in self.sessions:
            self.sessions.remove(session)

    async def broadcast(self, fn) -> None:
        for s in list(self.sessions):
            try:
                await fn(s)
            except Exception:
                log.exception("broadcast to %s failed", s.device)

    async def _on_reminder_due(self, item: dict):
        spoken = f"Reminder: {item['title']}"
        await self.broadcast(lambda s: s.announce_reminder(item))
        if not self.sessions:
            desktop_notify("Xarvii reminder", spoken)
        else:
            first = next(iter(self.sessions), None)
            with contextlib.suppress(Exception):
                await first.conv._speak_plain(first, spoken)

    async def confirm_reminder(self, dev: DeviceSession, title: str, due) -> None:
        item = self.reminder_store.add(title, due)
        log.info("reminder added via voice: %s @ %s", title, due.isoformat())
        await dev.chime("confirm")
        when = due.strftime("%I:%M %p").lstrip("0")
        if title.strip().lower() == "reminder":
            await dev.conv._speak_plain(dev, f"Reminder set for {when}.")
        else:
            await dev.conv._speak_plain(dev, f"Reminder set for {title} at {when}.")

    async def summarize_reminders(self) -> str:
        items = self.reminder_store.list(pending_only=True)
        if not items:
            return "You have no upcoming reminders."
        now = datetime.now()
        lines = []
        for i in items[:6]:
            due = datetime.fromisoformat(i["due"])
            delta = due - now
            hours = delta.total_seconds() / 3600
            when = f"in {delta.seconds // 60} minutes" if hours < 1 else (
                f"in {int(hours)} hours" if hours < 24 else due.strftime("%A at %H:%M")
            )
            lines.append(f"{i['title']} {when}")
        return "You have " + "; ".join(lines) + "."

    async def ctl_add_reminder(self, title: str, due: datetime) -> dict:
        return self.reminder_store.add(title, due)

    def apply_brain(self, dotted: str, value: str) -> dict:
        """Hot-swap; also auto-correct engine/voice mismatches."""
        result = self._apply_brain_inner(dotted, value)
        # auto-fix: ensure voice matches engine
        eng = self.cfg.tts.engine
        voice = self.cfg.tts.voice
        if eng == "edge" and voice.startswith("en_US") or voice.startswith("hi_IN-pratham"):
            pass  # piper name on edge engine is fine (edge accepts any string)
        elif eng == "piper" and not os.path.isfile(
                os.path.expanduser(voice)) and not voice.endswith(".onnx"):
            # voice doesn't exist as a piper file → likely an edge voice name
            log.warning("voice %r doesn't look like a piper model; "
                        "switching engine to edge", voice)
            self.cfg.tts.engine = "edge"
            from .config import set_config_values
            set_config_values(None, {"tts.engine": "edge"})
            from .tts.piper_tts import make_speaker
            try:
                new_spk = make_speaker(self.cfg)
                self._set_live_speaker_ref["current"] = new_spk
                for sess in self.sessions:
                    sess.conv.speaker = new_spk
            except Exception:
                pass
        return result

    def _apply_brain_inner(self, dotted: str, value: str) -> dict:
        """Hot-swap an engine choice: mutate cfg, persist, rebuild components."""
        from .config import BRAIN_KEYS, set_config_values
        from .stt import make_stt

        if dotted not in BRAIN_KEYS:
            return {"ok": False, "error": f"unknown brain key {dotted!r}"}
        if dotted.startswith("llm.tiers."):
            self.cfg.llm.tiers[dotted.rsplit(".", 1)[1]] = value
        elif BRAIN_KEYS[dotted] == "bool":
            section, key = dotted.rsplit(".", 1)
            setattr(getattr(self.cfg, section), key, value.lower() in ("true", "1", "yes", "on"))
        else:
            section, key = dotted.rsplit(".", 1)
            setattr(getattr(self.cfg, section), key, value)
        from .setup import _write_bools

        if BRAIN_KEYS.get(dotted) == "bool":
            _write_bools(Path("~/.config/desk-secretary/config.toml").expanduser(),
                         {dotted: value.lower() in ("true", "1", "yes", "on")})
        else:
            set_config_values(None, {dotted: value})
        rebuilt = []
        if dotted == "stt.engine":
            try:
                self.stt = make_stt(self.cfg)
                rebuilt.append("stt")
            except Exception as e:
                return {"ok": False, "error": f"stt rebuild failed: {e}"}
        if dotted.startswith("tts."):
            from .tts.piper_tts import make_speaker

            try:
                new_spk = make_speaker(self.cfg)
            except Exception as e:
                return {"ok": False, "error": f"tts rebuild failed: {e}"}
            if isinstance(new_spk, type(None)):
                return {"ok": False, "error": "speaker build returned none"}
            self._set_live_speaker_ref["current"] = new_spk
            for sess in self.sessions:
                sess.conv.speaker = new_spk
            rebuilt.append(f"tts({type(new_spk).__name__})")
        log.info("brain updated: %s = %s", dotted, value)
        return {"ok": True, "applied": dotted, "rebuilt": rebuilt}

    def brain_status(self) -> dict:
        return {
            "ok": True,
            "tiers": dict(self.cfg.llm.tiers),
            "stt_engine": self.cfg.stt.engine,
            "tts_engine": self.cfg.tts.engine,
            "tts_voice": self.cfg.tts.voice
            or ("en_US-lessac-medium" if self.cfg.tts.engine == "piper" else ""),
            "openai_voice": self.cfg.tts.openai_voice,
            "demo": self.cfg.demo,
        }

    async def speak_on_device(self, text: str) -> bool:
        target = next(iter(self.sessions), None)
        if target is None:
            return False
        await target.conv.ask_text(target, text)
        return True


def load_env_file(path: Path) -> int:
    """Load KEY=VALUE pairs into os.environ (does not override existing)."""
    import os

    loaded = 0
    if not path.is_file():
        return 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


async def serve(cfg: Cfg | None = None, config_path: str | None = None):
    env_path = Path("~/.config/desk-secretary/env").expanduser()
    n = load_env_file(env_path)
    logging.getLogger("deskd.server").info("env file: %d vars from %s", n, env_path)
    cfg = cfg or load_config(config_path)
    server = DeskServer(cfg)
    await server.start()
    try:
        await server.run_until_stopped()
    finally:
        await server.shutdown()

import asyncio
import contextlib
import json
import logging
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from .audio.vad import UtteranceTrimmer

log = logging.getLogger("deskd.conv")


_TIMER_HINT_RE = re.compile(r"\b(timer|countdown)\b", re.I)
_WEATHER_HINT_RE = re.compile(r"\b(weather|rain|umbrella|temperature|hot outside|cold outside|forecast)\b", re.I)
_CAL_HINT_RE = re.compile(r"\b(calendar|my day|meetings?|events?|schedule[ds]?|agenda)\b", re.I)
_MAIL_HINT_RE = re.compile(r"\b(mail|gmail|inbox|unread|emails?)\b", re.I)
_LANG_DEV = None


def _try_timer_intent(text: str):
    if not _TIMER_HINT_RE.search(text):
        return None
    if not re.search(r"\b(set|start|create)\b", text, re.I):
        return None
    from .skills.timers import parse_timer

    return parse_timer(text)


def _try_weather(text: str):
    m = re.search(r"(?:weather|forecast|temperature)\s*(?:in|at|for)\s+([a-z\s]{2,30})", text, re.I)
    if not m:
        if _WEATHER_HINT_RE.search(text):
            return ""
        return None
    place = m.group(1).strip()
    if not place or place in ("today", "now", "right now"):
        return ""
    return place


def _try_media(text: str):
    from .skills.media import parse_media

    return parse_media(text)


def _try_volume(text: str):
    from .skills.media import parse_volume

    return parse_volume(text)


def _try_brightness(text: str):
    from .skills.media import parse_brightness

    return parse_brightness(text)


def _try_open_app(text: str):
    from .skills.media import parse_open

    return parse_open(text)


def _try_calendar_query(text: str):
    t = text.lower()
    if not _CAL_HINT_RE.search(t):
        return None
    return "tomorrow" if "tomorrow" in t else "today"


def _try_mail_query(text: str) -> bool:
    return bool(re.search(r"\b(check|any|how many|read)\b.*\b(mail|gmail|inbox|emails?)\b"
                          r"|\bunread\b", text, re.I))


class LlmStreamFailed(Exception):
    pass


# ---------------------------------------------------------------- text helpers

def _fix_transcription(text: str) -> str:
    text = re.sub(r"\b2\s*-?\s*d\s+list\b", "to-do list", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:dualists?|dual\s*lists?|duelist?s?)\b", "to-do list",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"\btoday'?s\b", "today", text, flags=re.IGNORECASE)
    text = re.sub(r"\ba\s+m\b", "am", text, flags=re.IGNORECASE)
    text = re.sub(r"\bp\s+m\b", "pm", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:Mads|meds)\b", "maths", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*'?s\s+", "", text)
    text = re.sub(r"\b(\d{1,2})\.(\d{2})(?=\s*(?:am|pm)\b)", r"\1:\2", text,
                  flags=re.IGNORECASE)

    def _compact(m):
        digits = m.group(1)
        if len(digits) >= 3:
            hh, mm = digits[:-2], digits[-2:]
            if int(hh) <= 23 and int(mm) <= 59:
                return f"{int(hh)}:{mm}"
        return digits

    text = re.sub(r"\b(\d{3,4})\b(?=\s*(?:am|pm)\b)", _compact, text,
                  flags=re.IGNORECASE)
    return text


_REMIND_WORD_RE = re.compile(r"\bremind(?:er)?s?\b|\breminder\b", re.IGNORECASE)
_TIME_HINT_RE = re.compile(
    r"(?:\bat|in|after|by)\s*\d|tomorrow|tonight|\d+\s*(?:am|pm)|o'?clock"
    r"|minutes?|hours?|seconds?|\d{3,4}\b",
    re.IGNORECASE)
_SCAFFOLD_RE = re.compile(
    r"^\s*(?:okay[,.]?\s*)?(?:then[,.]?\s*)?(?:please\s+)?"
    r"(?:you\s+(?:have|need)\s+to\s+|can\s+you\s+|kindly\s+)?"
    r"remind(?:ers?)?(?:\s+me)?\s*(?:(?:about|of|for|that|to)\s+)?",
    re.IGNORECASE)
_TRAILING_JUNK_RE = re.compile(
    r"[,.;]?\s*(?:that\s+is|which\s+is|i\s+think|please|thanks(?:\s+you)?)[.,!?]?\s*$",
    re.IGNORECASE)
_LIST_HINT_RE = re.compile(
    r"\b(to[- ]?do\s*list|todo\s*list|remember\s+these|note\s+these|"
    r"make\s+a\s+list\s+of|jot\s+down|write\s+down\s+these)\b",
    re.IGNORECASE)


def _try_reminder_intent(text: str):
    """Return (title, due_datetime | None, needs_clarification) or None."""
    from .scheduler.reminders import parse_when_ex

    t = _fix_transcription(text)
    if not _REMIND_WORD_RE.search(t):
        return None
    if not _TIME_HINT_RE.search(t):
        return None
    due, span = parse_when_ex(t)
    if span is not None:
        s0, s1 = span
        while s1 < len(t) and (t[s1].isalnum() or t[s1] == "'"):
            s1 += 1
        while s0 > 0 and t[s0 - 1] in ",.":
            s0 -= 1
        title_part = (t[:s0] + " " + t[s1:]).strip()
    else:
        title_part = t
    title_part = _SCAFFOLD_RE.sub("", title_part)
    for pat in (
        r"\b(?:at\s+)?\d{1,2}:\d{2}\s*(?:am|pm)?\b\.?,?",
        r"\b\d{3,4}\b(?:\s*(?:am|pm))?\.?,?",
        r"\bo'?clock\b",
        r"\btonight\b",
    ):
        title_part = re.sub(pat, " ", title_part, flags=re.IGNORECASE)
    title_part = re.sub(r"\s{2,}", " ", title_part)
    title_part = _TRAILING_JUNK_RE.sub("", title_part).strip(" \t-,.")

    # wake-word mishears ("Jharvi remind me…", "Jarvi remind…") leak into the
    # title; strip anything up to and including the remind verb near the start
    lead = re.match(
        r"^[\w'\s]{0,16}?\bremind(?:er)?s?\b(?:\s+me)?\s*"
        r"(?:to\s+|that\s+(?:i\s+have\s+to\s+)?|of\s+|about\s+|for\s+)?",
        title_part, re.IGNORECASE)
    if lead:
        rest = title_part[lead.end():].strip(" ,.-")
        if len(rest) >= 3:
            title_part = rest

    if not title_part:
        return "Reminder", due, False
    return title_part, due, due is None


def _split_list_items(text: str) -> list[str]:
    cleaned = _fix_transcription(text)
    cleaned = re.sub(
        r"^.*?(?:to[- ]?do\s*list|todo\s*list|remember\s+these(\s+things)?|"
        r"note\s+these|make\s+a\s+list\s+of|jot\s+down|write\s+down\s+these)"
        r"\s*(?:for\s+today\s*)?(?:[:]|-)?\s*",
        "", cleaned, flags=re.IGNORECASE)
    parts = re.split(r",|\band\b|;|\n", cleaned)
    items = []
    for p_ in parts:
        p_ = re.sub(
            r"^\s*(?:'?s\s+|for\s+today\s+)?(?:i\s+(?:want\s+to|need\s+to|have\s+to|will)\s+)?"
            r"(?:study\s+|complete\s+|finish\s+|revise\s+|do\s+|read\s+)?",
            "", p_.strip(), flags=re.IGNORECASE).strip(" .")
        p_ = p_[0].upper() + p_[1:] if p_ else p_
        if len(p_) > 1:
            items.append(p_)
    seen, uniq = set(), []
    for it in items:
        if it.lower() not in seen:
            seen.add(it.lower())
            uniq.append(it)
    return uniq[:10]


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


_FACTUAL_RE = re.compile(
    r"\b(calculate|compute|how many|how much|sum of|average of|percent|%|"
    r"convert|square root|power of|search( the)? web|look up|latest news)\b",
    re.IGNORECASE)


_LOOKUP_RE = re.compile(
    r"\b(when (?:is|does|will|did)|next (?:match|game|episode|release)|"
    r"who won|latest|price of|remind me when|as soon as)\b",
    re.IGNORECASE)


def _looks_factual(text: str) -> bool:
    return bool(_FACTUAL_RE.search(text))


_MUSIC_RE = re.compile(r"^\s*play\b[^\n]*")
_HA_RE = re.compile(r"\b(turn (?:on|off)|switch (?:on|off)|dim|brighten|"
                    r"movie time|good ?night scene|set (?:the )?(?:lights?|temperature|ac))\b",
                    re.IGNORECASE)


def _try_music(text: str):
    m = re.match(r"\s*play\s+(.{2,60})$", text.strip(), re.IGNORECASE)
    if not m or re.search(r"\b(remind|timer|alarm)\b", text, re.I):
        return None
    return m.group(1).strip(" ?.!")


def _try_homeassistant(text: str):
    if not _HA_RE.search(text):
        return None
    low = text.lower()
    on = not any(w in low for w in ("off", "kill"))
    entity = "light.all_lights"
    if "movie" in low:
        return ("scene", "scene.movie_time", on)
    if "ac" in low or "temperature" in low or "thermostat" in low:
        entity = "climate.main"
    elif "fan" in low:
        entity = "fan.bedroom_fan"
    elif "light" in low or "lights" in low or "lamp" in low:
        entity = "light.all_lights"
    return ("service", entity, on)


def _needs_agent(text: str) -> bool:
    return _looks_factual(text) or bool(_LOOKUP_RE.search(text))


def _is_reminders_query(text: str) -> bool:
    t = _fix_transcription(text).lower().strip(" ?!")
    return (
        t.startswith(("what are my reminders", "any reminders",
                      "list my reminders", "my reminders"))
        and "add" not in t
    )


# ---------------------------------------------------------------- conversation

class Conversation:
    """One turn-based voice conversation bound to a device session."""

    def __init__(self, cfg, stt, llm_router, speaker_factory, context_builder=None,
                 tools=None, vault=None):
        self.cfg = cfg
        self.stt = stt
        self.router = llm_router
        self.make_speaker = speaker_factory
        self.speaker = speaker_factory()
        self.context_builder = context_builder or (lambda: "")
        self.tools = tools
        self.vault = vault
        from .skills.persona import Persona
        from .config import OwnerCfg

        owner = getattr(cfg, "owner", OwnerCfg())
        persona_cfg = getattr(cfg, "persona", None)
        self.persona = Persona(
            owner_name=owner.name,
            quirks=persona_cfg.quirks if persona_cfg else True)
        self._consent: dict | None = None      # pending screen-read permission
        self._consent_ts = 0.0
        self.guest = False
        self._followup = False
        self._interim_task: Optional[asyncio.Task] | None = None
        self._interim_last = ""
        self._interim_len = -1
        vad = getattr(cfg, "vad", None)
        self.trimmer = UtteranceTrimmer(
            threshold=vad.threshold if vad else 250.0,
            min_duration_s=vad.min_duration_s if vad else 0.35,
            pad_ms=vad.pad_ms if vad else 120)
        self.history = deque(maxlen=cfg.llm.max_history_turns * 2)
        self.max_utterance_bytes = 16000 * 2 * 60

        self._buf = bytearray()
        self._turn_task: Optional[asyncio.Task] = None
        self._tts_id = 0

    def start_interim(self, dev) -> None:
        """Emit partial transcripts while the user is speaking."""
        if not getattr(self.cfg.stt, "live_partial", True):
            return
        if self._interim_task and not self._interim_task.done():
            return
        self._interim_last = ""
        self._interim_len = -1
        self._interim_task = asyncio.create_task(self._guarded(
            self._interim_loop(dev), dev))

    def stop_interim(self) -> None:
        if self._interim_task and not self._interim_task.done():
            self._interim_task.cancel()
        self._interim_task = None
        self._interim_last = ""
        self._interim_len = -1

    async def _interim_loop(self, dev) -> None:
        last_sent = ""
        while True:
            await asyncio.sleep(0.9)
            buf = bytes(self._buf)
            if len(buf) < 16000 or len(buf) == self._interim_len:
                continue
            self._interim_len = len(buf)
            trimmed = self.trimmer.trim(buf)
            if not trimmed:
                continue
            try:
                text = await asyncio.wait_for(
                    self.stt.transcribe(trimmed, self.cfg.stt.language), 8)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
            text = text.strip()
            if text and text.lower() != last_sent.lower():
                last_sent = text
                with contextlib.suppress(Exception):
                    await dev.send_json({"type": "transcript_interim",
                                         "text": text})

    async def on_ptt_down(self, dev) -> None:
        if self._turn_task and not self._turn_task.done():
            log.info("barge-in: cancelling active turn")
            self.speaker.abort()
            self._turn_task.cancel()
            await dev.send_json({"type": "abort", "reason": "barge-in"})
        self.stop_interim()
        self._buf.clear()
        self._followup = False
        self._interim_task: Optional[asyncio.Task] | None = None
        self._interim_last = ""
        self._interim_len = -1
        await dev.set_state("listening")

    async def on_ptt_up(self, dev) -> None:
        log.info("utterance captured: %d bytes in %d frames",
                 len(self._buf), getattr(self, "_frames_seen", 0))
        self._frames_seen = 0
        if not self._buf:
            await dev.set_state("idle")
            return
        pcm = bytes(self._buf)
        self._buf.clear()
        self.stop_interim()
        pcm = self.trimmer.trim(pcm)
        if not pcm or len(pcm) < 3200:
            log.info("utterance too short; ignoring")
            if self._followup:
                self._followup = False
                with contextlib.suppress(Exception):
                    await dev.chime("error")
                    await self._speak_now(
                        dev,
                        "Sorry, I didn't catch that. Try holding ENTER longer.")
            await dev.set_state("idle")
            return
        self._turn_task = asyncio.create_task(self._guarded(self._turn(pcm, dev), dev))

    async def _guarded(self, coro, dev) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
            with contextlib.suppress(Exception):
                await dev.chime("error")
                await dev.set_state("idle")

    def feed_audio(self, chunk: bytes) -> None:
        room = self.max_utterance_bytes - len(self._buf)
        self._buf.extend(chunk[:room])
        self._frames_seen = getattr(self, "_frames_seen", 0) + 1

    def cancel(self) -> None:
        self.speaker.abort()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()

    async def ask_text(self, dev, text: str) -> None:
        self.cancel()
        self._turn_task = asyncio.create_task(self._guarded(self._respond(text, dev), dev))

    # ------------------------------------------------------------------ turn

    async def _turn(self, pcm: bytes, dev) -> None:
        try:
            text = await self.stt.transcribe(pcm, self.cfg.stt.language)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stt failed")
            await dev.chime("error")
            await dev.set_state("idle")
            return
        text = text.strip()
        log.info("user said: %r", text)
        await dev.send_json({"type": "transcript", "text": text})
        if not text:
            self.stop_interim()
            if self._followup:
                self._followup = False
                with contextlib.suppress(Exception):
                    await self._speak_now(dev,
                                          "I heard noise but no words there.")
                await dev.set_state("idle")
                return
            await dev.set_state("idle")
            return

        self.guest = False
        sid = getattr(self.cfg, "speaker_id", None)
        if sid and sid.enabled and len(pcm) > 16000 * 2 * 3:
            verify = getattr(dev, "verify_speaker", None)
            if verify:
                is_owner, score = await dev.verify_speaker(pcm)
                if is_owner is False:
                    self.guest = True
                    log.info("guest voice (score=%s) — restricted mode", score)

        fixed = _fix_transcription(text)

        if _is_reminders_query(fixed) and hasattr(dev, "summarize_reminders"):
            summary = await dev.summarize_reminders()
            await self.history_and_speak(
                dev, text, summary or "You have no upcoming reminders.")
            return

        rem = _try_reminder_intent(fixed)
        if rem is not None:
            title, due, unclear = rem
            if unclear or due is None:
                await self._speak_plain(
                    dev, "I caught a reminder but couldn't parse the exact time. "
                         "Say it like: remind me at 12 45 am.")
                return
            await dev.dispatch_reminder_intent(title, due)
            return

        if self.guest:
            from .skills.facts import try_datetime as _td, try_math as _tm

            ans = _tm(fixed) or _td(fixed, datetime.now())
            if ans:
                await self.history_and_speak(dev, text, ans)
                return
            if _is_reminders_query(fixed):
                await self._speak_plain(
                    dev, "I can't share personal reminders in guest mode.")
                return
            await self._respond(fixed, dev, guest=True)
            return

        # ---------------- Obsidian deep recall (RAG)
        m_rag = re.search(
            r"\b(?:what did i (?:write|note|say)|search my notes|in my notes|"
            r"my notes (?:about|on)|according to my notes)\b(.*)$",
            fixed, re.IGNORECASE)
        if m_rag is not None and not self.guest:
            qtail = m_rag.group(1).strip() or fixed
            answer = await dev.ask_rag(qtail or fixed)
            if answer is None:
                await self._speak_plain(dev, "My memory index isn't built yet.")
            else:
                await self.history_and_speak(dev, text, answer)
            return

        # ---------------- timers
        timer_parse = _try_timer_intent(fixed)
        if timer_parse is not None:
            name, seconds = timer_parse
            await dev.start_timer(name, seconds)
            return

        if re.search(r"\b(stop|cancel|dismiss)\b", fixed) and \
                hasattr(dev, "timers") and dev.timers.active_count():
            n = dev.timers.dismiss_all()
            await self._speak_plain(dev, "Timer stopped." if n else "No active timers.")
            return
        if hasattr(dev, "timers") and re.search(r"\b(my )?timers\b", fixed.lower()) \
                and dev.timers.describe():
            await self._speak_plain(dev, "Active timers: " + dev.timers.describe() + ".")
            return

        # ---------------- weather
        w = _try_weather(fixed)
        if w is not None:
            answer = await dev.ask_weather(w)
            if answer:
                await self.history_and_speak(dev, text, answer)
                return

        # ---------------- media / volume / brightness / open app
        m_action = _try_media(fixed)
        if m_action is not None:
            await self.history_and_speak(dev, text, await dev.do_media(m_action))
            return
        vol = _try_volume(fixed)
        if vol is not None:
            op, pct = vol
            await self.history_and_speak(dev, text, await dev.do_volume(op, pct))
            return
        bri = _try_brightness(fixed)
        if bri is not None:
            op, pct = bri
            await self.history_and_speak(dev, text, await dev.do_brightness(op, pct))
            return
        app = _try_open_app(fixed)
        if app is not None:
            await self.history_and_speak(dev, text, await dev.do_open(app))
            return

        # ---------------- calendar / gmail queries
        day_q = _try_calendar_query(fixed)
        if day_q is not None:
            answer = await dev.ask_calendar(day_q)
            if answer is not None:
                await self.history_and_speak(dev, text, answer)
                return
        mail_q = _try_mail_query(fixed)
        if mail_q and hasattr(dev, "ask_gmail"):
            answer = await dev.ask_gmail()
            if answer is not None:
                await self.history_and_speak(dev, text, answer)
                return

        # ---------------- briefing on demand
        if re.search(r"\b(briefing|brief me|morning summary|daily summary|my day)\b",
                     fixed, re.IGNORECASE):
            which_day = "tomorrow" if "tomorrow" in fixed.lower() else "today"
            answer = await dev.ask_briefing(which_day)
            await self.history_and_speak(dev, text, answer or "Briefing unavailable right now.")
            return

        # ---------------- screen read with spoken consent (privacy gate)
        if re.search(r"\b(what'?s? on (my|the) screen|read (my|the) screen|describe my screen)\b",
                     fixed, re.IGNORECASE):
            import time as _time

            fresh = self._consent and (_time.time() - self._consent_ts < 600)
            if not fresh:
                self._consent = {"awaiting": True}
                self._consent_ts = _time.time()
                await self._speak_plain(
                    dev, "I'll need to capture your screen and send it to the cloud brain "
                         "for that. Say yes to allow, or no to cancel.")
                return
            self._consent = None
            answer = await dev.read_screen()
            await self.history_and_speak(dev, text, answer or "Screen capture failed.")
            return
        if self._consent and self._consent.get("awaiting"):
            self._consent = None
            if re.match(r"^\s*(yes|yeah|yep|sure|go ahead|allow|haan|haan ji)", fixed, re.I):
                answer = await dev.read_screen()
                await self.history_and_speak(dev, "(screen read approved)",
                                             answer or "Screen capture failed.")
            else:
                await self._speak_plain(dev, "Cancelled. Nothing was captured.")
            return

        # ---------------- standup generator
        if re.search(r"\bstandup\b|stand up update|daily update for work", fixed, re.IGNORECASE):
            repos = [str(x) for x in getattr(self.cfg, "standup_repos", [])] or []
            answer = await dev.ask_standup(repos)
            await self.history_and_speak(dev, text, answer or "Couldn't build a standup.")
            return

        # ---------------- meeting mode
        if re.search(r"\b(start|begin)\b.*\bmeeting (mode|notes)\b|"
                     r"\bstart recording\b", fixed, re.I):
            msg = await dev.start_meeting()
            await self.history_and_speak(dev, text, msg)
            return
        if re.search(r"\b(stop|end)\b.*\b(meeting (mode|notes)|recording)\b", fixed, re.I):
            await self._speak_plain(
                dev, "Processing the meeting — give me a moment.")
            answer = await dev.stop_meeting()
            self._turn_task_done = True
            await self.history_and_speak(dev, text, answer)
            return

        # ---------------- expenses
        from .skills.music import parse_expense, parse_month_query

        exp = parse_expense(fixed)
        if exp is not None and not self.guest:
            amount, what = exp
            spoken = await dev.log_expense(amount, what)
            await self.history_and_speak(dev, text, spoken)
            return
        if parse_month_query(fixed) and not self.guest and \
                hasattr(dev, "expenses_total"):
            total, count = await dev.expenses_total()
            if count:
                await self.history_and_speak(
                    dev, text,
                    f"This month you've logged {count} expenses totalling "
                    f"{total:g} rupees.")
            else:
                await self.history_and_speak(
                    dev, text, "No expenses logged yet this month.")
            return

        # ---------------- music
        music = _try_music(fixed)
        if music is not None:
            query = music
            spoken = await dev.do_music(query)
            await self.history_and_speak(dev, text, spoken)
            return

        # ---------------- home assistant / webhook
        ha = _try_homeassistant(fixed)
        if ha is not None:
            spoken = await dev.do_ha(*ha)
            await self.history_and_speak(dev, text, spoken)
            return

        # ---------------- journaling session FSM
        if re.search(r"\blet'?s journal|journal time|evening journal\b", fixed, re.I):
            await dev.begin_journal()
            return
        live_js = getattr(getattr(dev, "server", None), "_journal", None)
        if live_js is not None and not live_js.done:
            live_js.answer(text)
            if live_js.done:
                path = live_js.write()
                setattr(dev.server, "_journal", None)
                where = f" Saved as {path}." if path else ""
                await self.history_and_speak(dev, text, "Journal saved." + where)
            else:
                await self._speak_plain(dev, live_js.next_prompt())
            return

        # ---------------- clipboard suggestion consumed here
        pend = getattr(dev, "pop_clipboard_offer", lambda: None)()
        if pend is not None and re.search(r"^(yes|yeah|sure|summar(y|ise|ize)|go ahead)", fixed, re.I):
            answer = await dev.summarize_clipboard(pend)
            await self.history_and_speak(dev, text, answer or "Couldn't summarize it.")
            return

        # ---------------- dictated list capture

        if self.vault is not None and _LIST_HINT_RE.search(fixed):
            items = _split_list_items(fixed)
            if items:
                for it in items:
                    self.vault.append_inbox(it, as_task=True)
                    self.vault.sweep_expired_inbox(max_age_days=7)
                plural = "s" if len(items) > 1 else ""
                listing = ", ".join(items[:4])
                await self._speak_plain(
                    dev, f"Noted {len(items)} item{plural} in your inbox: {listing}.")
                return

        await self._respond(fixed, dev)

    # -------------------------------------------------------------- respond

    async def _maybe_tool_round(self, provider, text: str, messages: list[dict]) -> None:
        """Agentic loop: model may chain tools across multiple rounds."""
        agent_cfg = getattr(self.cfg, "agent", None)
        if not self.tools or not agent_cfg or not agent_cfg.enabled:
            return
        if not _needs_agent(text):
            return
        max_rounds = max(1, int(agent_cfg.max_rounds))
        spec = [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["parameters"]}}
            for t in self.tools.spec_for_llm()
        ]
        for rnd in range(max_rounds):
            try:
                msg = await provider.complete(messages, tools=spec)
            except Exception:
                log.exception("agent round %d failed; continuing with context so far", rnd)
                return
            calls = msg.get("tool_calls") or []
            if not calls:
                messages.append({"role": "assistant", "content": msg.get("content") or ""})
                return
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": calls})
            for tc in calls[:4]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments")
                if isinstance(args, str):
                    with contextlib.suppress(Exception):
                        args = json.loads(args)
                result = await self.tools.call(name, args if isinstance(args, dict) else {})
                log.info("agent tool[%d] %s(%r) -> %r", rnd, name, args,
                         str(result)[:200])
                messages.append({"role": "tool",
                                 "content": json.dumps(result, default=str)[:2000]})
            messages.append({"role": "system",
                             "content": "Tool results above are ground truth. "
                                        "Call more tools if needed, otherwise state the final answer."})

    async def _respond(self, text: str, dev, guest: bool = False) -> None:
        from .textsplit import ThinkFilter
        from .tts.piper_tts import StreamedTtsPipeline

        await dev.set_state("thinking")
        approx_tokens = sum(len(m.get("content", "")) for m in self.history) // 4 + len(text) // 4
        tier = self.router.tier_for(has_images=False, approx_tokens=approx_tokens)
        from .skills.langdetect import detect_lang, reply_language_directive

        lang = detect_lang(text)
        system = self.context_builder()
        if lang != "en":
            system += "\n" + reply_language_directive(lang)
        messages: list[dict] = [{"role": "system", "content": system}] + list(self.history)
        messages.append({"role": "user", "content": text})
        provider = self.router.resolve(self.cfg.llm.tiers[tier])
        fallback = None
        if not self.cfg.llm.tiers[tier].startswith("ollama/") and not self.cfg.demo:
            with contextlib.suppress(Exception):
                fb = self.router.resolve("ollama/llama3.2:3b")
                if type(fb) is not type(provider):
                    fallback = fb

        tool_note = await self._maybe_tool_round(provider, text, messages)

        pipeline = StreamedTtsPipeline(self.speaker, dev.conn, self.cfg.tts.sentence_min_len)
        reply_parts: list[str] = []
        think = ThinkFilter()
        started = False
        ok = False
        attempts = [provider] + ([fallback] if fallback else [])
        last_err: Exception | None = None
        try:
          async with dev.speech_slot():
            for attempt_idx, prov in enumerate(attempts):
                try:
                    async for delta in prov.stream(messages):
                        visible = think.feed(delta)
                        reply_parts.append(delta)
                        if not visible:
                            continue
                        if not started:
                            await dev.set_state("speaking")
                            started = True
                        await pipeline.feed(visible)
                        if pipeline.aborted:
                            break
                    if not pipeline.aborted:
                        tail = think.flush()
                        if tail:
                            await pipeline.feed(tail)
                        await pipeline.finish()
                    ok = True
                    break
                except asyncio.CancelledError:
                    raise
                except LlmStreamFailed:
                    raise
                except Exception as e:
                    last_err = e
                    if pipeline.aborted or started or attempt_idx == len(attempts) - 1:
                        break
                    log.warning("llm %s failed (%s); falling back to next brain",
                                type(prov).__name__, e)
                    think = ThinkFilter()
                    reply_parts.clear()
                    await asyncio.sleep(0.2)
            if not ok and not pipeline.aborted:
                if last_err:
                    log.error("all llm brains failed; last error: %s", last_err)
                await dev.chime("error")
                with contextlib.suppress(Exception):
                    await self._speak_now(dev,
                                          "Sorry, my brain is unreachable right now.")
        except asyncio.CancelledError:
            pipeline.abort()
            raise
        finally:
            self._followup = False
            self.stop_interim()
            if ok:
                full_reply = _strip_think("".join(reply_parts)).strip()
                if full_reply:
                    self.history.append({"role": "user", "content": text})
                    self.history.append({"role": "assistant", "content": full_reply})
            if not dev.closed:
                quip = self.persona.quip_after_answer() if ok else None
                if quip:
                    with contextlib.suppress(Exception):
                        await self._speak_plain(dev, quip)
                with contextlib.suppress(Exception):
                    secs = getattr(self.cfg, "followup").seconds
                    if secs > 0 and ok:
                        await dev.offer_followup(secs)
                    else:
                        await dev.set_state("idle")

    async def history_and_speak(self, dev, user_text: str, answer: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": answer})
        await self._speak_plain(dev, answer)
        quip = self.persona.quip_after_answer()
        if quip:
            await asyncio.sleep(0.4)
            await self._speak_plain(dev, quip)
        secs = getattr(getattr(self.cfg, "followup", None), "seconds", 0)
        if secs > 0 and not dev.closed:
            with contextlib.suppress(Exception):
                await dev.offer_followup(secs)

    async def _speak_plain(self, dev, text: str) -> None:
        async with dev.speech_slot():
            await self._speak_now(dev, text)

    async def _speak_now(self, dev, text: str) -> None:
        await dev.set_state("speaking")
        self._tts_id += 1
        await dev.send_json({"type": "tts_start", "id": self._tts_id, "text": text})
        try:
            await self.speaker.say(text, dev.conn)
        finally:
            with contextlib.suppress(Exception):
                await dev.send_json({"type": "tts_stop", "id": self._tts_id})
        await dev.set_state("idle")

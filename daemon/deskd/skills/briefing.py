"""Morning/on-demand briefing: weather + reminders + inbox + calendar + gmail + fact."""

import logging
import random

from . import calendar_ics
from .gmail_imap import spoken_digest, unread_digest
from .weather import weather_report

log = logging.getLogger("deskd.briefing")

_FACTS = [
    "Octopuses have three hearts.",
    "Honey never spoils — edible honey was found in ancient tombs.",
    "Bananas are berries, but strawberries are not.",
    "A day on Venus is longer than its year.",
    "Your brain uses about twenty percent of your body's energy.",
    "The Eiffel Tower grows about fifteen centimetres taller in summer.",
]


async def compose(server, which_day: str = "today", include_mail=True) -> str:
    cfg = server.cfg
    parts = []

    persona_line = server.persona.greeting_if_new_day()
    if persona_line:
        parts.append(persona_line)

    if cfg.owner.location:
        w = await weather_report(cfg.owner.location,
                                 cfg.owner.latitude, cfg.owner.longitude)
        parts.append(w or "")

    items = server.reminder_store.list(pending_only=True)
    today = [i for i in items if i["due"][:10] == __import__("datetime").datetime.now().strftime("%Y-%m-%d")]
    if today:
        listing = "; ".join(f"{i['title']} at {i['due'][11:16]}" for i in today[:5])
        parts.append(f"You have {len(today)} reminder{'s' if len(today) > 1 else ''} today: {listing}.")
    elif items:
        parts.append(f"Nothing due today; next up is {items[0]['title']} on {items[0]['due'][5:16]}.")
    else:
        parts.append("No pending reminders.")

    if vault_tasks(server) is not None:
        tasks = vault_tasks(server)[:6]
        if tasks:
            parts.append(f"{len(tasks)} open notes-tasks, top ones: " +
                         "; ".join(t["text"][:40] for t in tasks[:3]) + ".")

    if cfg.calendar.ics_url:
        events = calendar_ics.events_for_day(cfg.calendar.ics_url, which_day)
        if events is not None:
            parts.append(calendar_ics.spoken_summary(events, which_day))

    if include_mail and cfg.gmail.user:
        result = unread_digest(cfg.gmail.host, cfg.gmail.user,
                               cfg.gmail.password_env, cfg.gmail.max_unread)
        if result:
            parts.append(spoken_digest(result, cfg.gmail.max_unread))

    timer_status = server.timers.describe()
    if timer_status:
        parts.append(f"Active timers: {timer_status}.")

    parts.append("Fun fact: " + random.choice(_FACTS))
    return " ".join(p for p in parts if p).strip()


def vault_tasks(server):
    vault = getattr(server, "vault", None)
    if vault is None:
        return None
    try:
        return vault.tasks(limit=8)
    except Exception:
        log.exception("vault tasks failed")
        return None

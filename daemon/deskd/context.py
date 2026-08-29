import logging
from datetime import datetime, timedelta

log = logging.getLogger("deskd.server")


def build_context(cfg, vault, reminders) -> str:
    now = datetime.now()
    parts = [
        "You are the user's desk secretary: concise, proactive, spoken-word friendly.",
        "Answers are read aloud by TTS, so prefer short plain sentences, no markdown,",
        "no lists longer than 5 items, spell out numbers when natural.",
        "Reply with ONLY the spoken answer. Never narrate your reasoning, never say",
        "'Okay', 'Sure', 'the user', or describe what you are about to do.",
        "NEVER claim you performed an action (saved, set, reminded, created)",
        "unless the conversation shows a tool or system already did it.",
        f"Current time: {now.strftime('%A %Y-%m-%d %H:%M')}.",
        f"Tomorrow is {(now + timedelta(days=1)).strftime('%A, %B %-d')}.",
    ]
    if reminders is not None:
        items = reminders.list(pending_only=True)[:5]
        if items:
            lines = [f"- {i['title']} at {i['due']}" for i in items]
            parts.append("Upcoming reminders:\n" + "\n".join(lines))
        else:
            parts.append("No upcoming reminders.")
    if vault is not None:
        try:
            digest = vault.digest(limit=4)
            tasks = vault.tasks(limit=8)
            if digest:
                lines = [f"- {d['title'] if 'title' in d else d['file']}: {d['summary']}" for d in digest]
                parts.append("Recently edited notes:\n" + "\n".join(lines))
            pending = [t for t in tasks][:6]
            if pending:
                lines = [f"- {t['text']}" + (f" (due {t['due']})" if t["due"] else "") for t in pending]
                parts.append("Open tasks from notes:\n" + "\n".join(lines))
        except Exception:
            log.exception("context build: obsidian failed")
    return "\n".join(parts)

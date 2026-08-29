"""Persona layer: time-aware greetings, occasional quirks, task streaks."""

import json
import random
from datetime import datetime
from pathlib import Path


class Persona:
    def __init__(self, name: str = "Xarvii", owner_name: str = "",
                 state_file: str = "~/.local/state/desk-secretary/persona.json",
                 quirks: bool = True):
        self.name = name
        self.owner_name = owner_name
        self.quirks = quirks
        self.path = Path(state_file).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {"days_active": [], "tasks_done": 0, "last_greet": ""}
        try:
            if self.path.is_file():
                self.state.update(json.loads(self.path.read_text()))
        except Exception:
            pass

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.state))
        except OSError:
            pass

    def greeting_if_new_day(self, now: datetime | None = None) -> str | None:
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self.state.get("last_greet") == today:
            return None
        self.state["last_greet"] = today
        days = self.state.setdefault("days_active", [])
        if today not in days:
            days.append(today)
            self.state["days_active"] = days[-90:]
        streak = 1
        from datetime import timedelta

        d = now.date() - timedelta(days=1)
        while d.strftime("%Y-%m-%d") in days:
            streak += 1
            d -= timedelta(days=1)
        self._save()
        hour = now.hour
        part = "morning" if hour < 12 else ("afternoon" if hour < 17 else "evening")
        base = f"Good {part}"
        if self.owner_name:
            base += f", {self.owner_name}"
        line = f"{base}! {self.name} here, ready."
        if streak >= 2:
            line += f" Day {streak} of using me — nice."
        return line

    def quip_after_answer(self) -> str | None:
        if not self.quirks or random.random() > 0.12:
            return None
        hour = datetime.now().hour
        pool = [
            "Anything else on your mind?",
            "I'm here if you need me.",
            "By the way, hydration check!",
        ]
        if 22 <= hour or hour < 5:
            pool.append("It's getting late, just saying.")
        if 12 <= hour < 14:
            pool.append("Lunch time, maybe?")
        return random.choice(pool)

    def note_task_done(self):
        self.state["tasks_done"] = self.state.get("tasks_done", 0) + 1
        self._save()

"""Interactive browsable UI for xarvii: `xarvii ui` (or `xarvii help`)."""

import asyncio
import json
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ------------------------------------------------------------------ plumbing

def _ctl(payload, timeout=15):
    from .cli import _request

    return asyncio.run(_request(8766, payload, timeout))


def _ok(resp):
    return isinstance(resp, dict) and resp.get("ok")


def _daemon_alive() -> bool:
    try:
        return _ok(_ctl({"id": 1, "cmd": "status"}, 4))
    except Exception:
        return False


class KeyNav:
    """Single-key / arrow menu. Returns chosen index or None on esc/q."""

    def __init__(self, title: str, items: list[str]):
        self.title = title
        self.items = items
        self.sel = 0

    def _render(self, hint: str = ""):
        console.clear()
        console.print(Panel(f"[bold cyan]{self.title}[/]", subtitle="↑↓/j/k move · enter select · q back"))
        for i, item in enumerate(self.items):
            marker = "[bold reverse cyan] ▶ " if i == self.sel else "   "
            style = "bold" if i == self.sel else "dim"
            console.print(f"{marker}[{style}] {i + 1:>2}. {item} [/]")
        if hint:
            console.print(f"\n[dim]{hint}[/]")

    def run(self, hint: str = "") -> int | None:
        import select
        import termios
        import tty

        def _read_arrow():
            """Return 'up'/'down'/'' after consuming an ESC-[ sequence."""
            r, _, _ = select.select([fd], [], [], 0.06)
            if not r:
                return ""
            nxt = os.read(fd, 1).decode(errors="replace")
            if nxt != "[":
                return ""
            if not select.select([fd], [], [], 0.05)[0]:
                return ""
            d = os.read(fd, 1).decode(errors="replace")
            return {"A": "up", "B": "down"}.get(d, "")

        if not sys.stdin.isatty():
            self._render(hint)
            try:
                raw = input("select number (blank=cancel): ").strip()
                return int(raw) - 1 if raw.isdigit() and 0 < int(raw) <= len(self.items) else None
            except EOFError:
                return None
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                self._render(hint)
                ch = os.read(fd, 1).decode(errors="replace")
                if ch == "q":
                    return None
                if ch == "\x1b":
                    direction = _read_arrow()
                    if not direction:
                        return None
                    if direction == "up":
                        self.sel = max(0, self.sel - 1)
                    elif direction == "down":
                        self.sel = min(len(self.items) - 1, self.sel + 1)
                    continue
                if ch in ("\r", "\n", " "):
                    return self.sel
                if ch == "k" or ch == "A":
                    self.sel = max(0, self.sel - 1)
                elif ch == "j" or ch == "B":
                    self.sel = min(len(self.items) - 1, self.sel + 1)
                elif ch.isdigit():
                    n = int(ch)
                    if 1 <= n <= len(self.items):
                        self.sel = n - 1
                        self._render(hint)
                        return self.sel
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def pick(title: str, items: list[str], hint: str = "") -> int | None:
    return KeyNav(title, items).run(hint)


def pause():
    console.print("\n[dim]press enter to continue…[/]")
    try:
        input()
    except EOFError:
        pass


# ------------------------------------------------------------------ sections

def section_status():
    console.clear()
    alive = _daemon_alive()
    color = "green" if alive else "red"
    state = "running" if alive else "NOT RUNNING"
    table = Table.grid(padding=(0, 2))
    table.add_row("[bold]daemon[/]", f"[{color}]● {state}[/]")
    if alive:
        st = _ctl({"id": 1, "cmd": "status"})
        brains = _ctl({"id": 21, "cmd": "brain_status"})
        devs = st.get("devices", [])
        table.add_row("devices", ", ".join(f"{d['device']} ({d['state']})" for d in devs) or "[dim]none connected[/]")
        table.add_row("reminders pending", str(st.get("reminders_pending", 0)))
        tiers = brains.get("tiers", {})
        table.add_row("llm fast", tiers.get("fast", "?"))
        table.add_row("llm reasoning", tiers.get("reasoning", "?"))
        table.add_row("stt / tts", f"{brains.get('stt_engine')} / {brains.get('tts_engine')}")
        table.add_row("tts voice", brains.get("tts_voice") or "-")
    console.print(Panel(table, title="[bold]XARVII STATUS[/]", expand=False))
    pause()


def section_brains():
    while True:
        try:
            brains = _ctl({"id": 21, "cmd": "brain_status"})
        except Exception:
            console.print("[red]daemon unreachable[/]")
            pause()
            return
        tiers = brains.get("tiers", {})
        idx = pick("BRAINS — choose a slot to change",
                   [f"fast      = {tiers.get('fast')}",
                    f"reasoning = {tiers.get('reasoning')}",
                    f"vision    = {tiers.get('vision')}",
                    "back"])
        if idx is None or idx == 3:
            return
        tier = ["fast", "reasoning", "vision"][idx]
        opts = _probe_models()
        choice = pick(f"model for [{tier}] — current: {tiers.get(tier)}",
                      opts, "cloud options need their API keys exported")
        if choice is not None:
            val = opts[choice]
            res = _ctl({"id": 22, "cmd": "brain_set", "key": f"llm.tiers.{tier}", "value": val})
            console.print("[green]applied[/]" if _ok(res) else f"[red]{res}[/]" if isinstance(res, dict) else res)
            pause()


def _probe_models() -> list[str]:
    from .cli import _probe_options

    grouped = _probe_options()
    out = []
    for prov in ("gemini", "ollama", "anthropic", "openai", "groq", "echo"):
        for model in grouped.get(prov, []):
            out.append(f"{prov}/{model}")
    return list(dict.fromkeys(out))


def section_voices():
    from .cli import _installed_piper, cmd_voice_preview
    from .tts.catalog import PIPER_CURATED

    while True:
        current = ""
        try:
            brains = _ctl({"id": 21, "cmd": "brain_status"})
            engine = brains.get("tts_engine")
            voice = brains.get("tts_voice")
            current = f"{engine}: {voice}" if engine != "openai" else f"openai: {voice}"
        except Exception:
            pass
        installed = _installed_piper()
        edge_top = ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-US-AndrewNeural",
                    "en-US-AriaNeural", "en-GB-SoniaNeural", "hi-IN-SwaraNeural"]
        items = ([f"current: {current}"] if current else []) + \
                [f"edge/{v}" for v in edge_top] + \
                [f"piper/{n}" + (" ✓installed" if n in installed else "") for n in sorted(PIPER_CURATED)] + \
                [f"openai/{v}" for v in ("alloy", "nova", "shimmer")] + ["back"]
        idx = pick("VOICES — preview before you commit", items,
                   "selecting a piper voice that isn't installed will offer to download it")
        if idx is None or idx >= len(items) - 1:
            return
        sel = items[idx]
        if sel.startswith("current:"):
            continue
        engine, _, voice = sel.removeprefix("edge/").removeprefix("piper/").partition("/")
        engine = sel.split("/", 1)[0]
        if engine == "piper" and voice not in installed:
            console.print("[yellow]not installed yet — downloading…[/]")
            from .cli import cmd_voice_install

            cmd_voice_install(voice)
        act = pick(f"{sel}", ["preview 🔊", "make this my voice", "back"])
        if act is None or act == 2:
            continue
        try:
            if act == 0:
                console.print("[dim]playing…[/]")
                cmd_voice_preview(engine, voice)
            else:
                key = "tts.openai_voice" if engine == "openai" else "tts.voice"
                _ctl({"id": 23, "cmd": "brain_set", "key": "tts.engine", "value": engine})
                res = _ctl({"id": 24, "cmd": "brain_set", "key": key, "value": voice})
                console.print("[green]voice applied — next sentence uses it[/]"
                              if _ok(res) else f"[red]{res}[/]")
                pause()
        except Exception as e:
            console.print(f"[red]{e}[/]")
            pause()


def section_reminders():
    while True:
        try:
            resp = _ctl({"id": 30, "cmd": "reminders_list"})
        except Exception:
            console.print("[red]daemon unreachable[/]")
            pause()
            return
        items = resp.get("items", [])
        lines = [f"{i['id'][:9]}…  {i['due'][11:16]}  {i['title']}" for i in items] or ["[dim]no pending reminders[/]"]
        lines += ["＋ add one", "back"]
        idx = pick("REMINDERS", lines)
        if idx is None or idx == len(lines) - 1:
            return
        if idx == len(lines) - 2:
            console.print("title: ", end="")
            title = input().strip()
            console.print("when (in 30m | at 17:30 | tomorrow 9am): ", end="")
            when = input().strip()
            if title and when:
                from .scheduler.reminders import parse_when

                due = parse_when(when)
                if due:
                    _ctl({"id": 31, "cmd": "add_reminder", "title": title,
                          "due": due.isoformat(timespec="seconds")})
                    console.print("[green]scheduled ✓[/]")
            pause()
            continue
        item = items[idx]
        act = pick(item["title"], ["remove", "back"])
        if act == 0:
            _ctl({"id": 32, "cmd": "reminder_remove", "id": item["id"]})
            console.print("[green]removed ✓[/]")
            pause()


def section_device():
    console.clear()
    console.print(Panel(
        "[bold]Start the satellite[/]\n\n"
        "In another terminal (or after quitting this UI):\n\n"
        "    [cyan]xarvii device[/]\n\n"
        "ENTER toggles talk · m mute · q quit.\n"
        "Wave-file test mode:\n"
        "    [cyan]xarvii device --wave file.wav --no-audio[/]",
        title="[bold]DEVICE[/]", expand=False))
    pause()


def section_logs():
    console.clear()
    os.system("journalctl --user -u deskd-dev -n 40 --no-pager | less +G 2>/dev/null "
              "|| journalctl --user -u deskd-dev -n 40 --no-pager")
    pause()


# ------------------------------------------------------------------ main loop

MAIN_ITEMS = [
    "📊 Status",
    "🧠 Brains (LLM models)",
    "🎙 Voices (TTS)",
    "⏰ Reminders",
    "📡 Device satellite",
    "📜 Live logs",
    "❓ About",
    "🚪 Exit",
]


def about():
    console.clear()
    console.print(Panel(
        "[bold cyan]xarvii[/] — your desk secretary\n\n"
        "[bold]quick CLI cheatsheet[/]\n"
        "  xarvii              start the voice satellite\n"
        "  xarvii status       one-shot status\n"
        "  xarvii remind TITLE WHEN\n"
        "  xarvii ask \"text\"   speak text via the device\n"
        "  xarvii voices       full catalogs\n"
        "  xarvii reset        restore defaults\n\n"
        "[bold]architecture[/]\n"
        "  satellite (ESP32/Pi/laptop mic)\n"
        "    → whisper STT → gemini/local brain → piper|edge|openai voice\n"
        "  skills: reminders · obsidian · web search · screen capture · MCP",
        title="ABOUT", expand=False))
    pause()


def run_ui():
    while True:
        idx = pick("XARVII CONTROL CENTER", MAIN_ITEMS)
        if idx is None or idx == len(MAIN_ITEMS) - 1:
            console.clear()
            return
        action = {
            0: section_status, 1: section_brains, 2: section_voices,
            3: section_reminders, 4: section_device, 5: section_logs,
            6: about,
        }.get(idx)
        if action:
            action()


if __name__ == "__main__":
    run_ui()

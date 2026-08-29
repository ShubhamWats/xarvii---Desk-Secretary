"""The complete capability map of xarvii — rendered beautifully."""

import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ---------------------------------------------------------------- live probes

def _probe() -> dict:
    info = {
        "ollama": [], "keys": set(), "vault": False, "ha": False,
        "telegram": False, "gmail": False, "search": False,
        "rules": 0, "reminders": 0, "plugins": 0, "rag": False,
        "speaker_id": False, "wake_word": False, "dashboard": False,
        "devices": [],
    }
    try:
        from .cli import _request

        st = asyncio_run(_request(8766, {"id": 1, "cmd": "status"}, 5))
        brains = asyncio_run(_request(8766, {"id": 2, "cmd": "brain_status"}, 5))
        tools = asyncio_run(_request(8766, {"id": 3, "cmd": "tool_list"}, 5))
        rem = asyncio_run(_request(8766, {"id": 4, "cmd": "reminders_list"}, 5))
        info["daemon"] = True
        info["tiers"] = brains.get("tiers", {})
        info["tts"] = f"{brains.get('tts_engine')} · {brains.get('tts_voice', '')}"
        info["stt"] = brains.get("stt_engine")
        info["rules"] = len(asyncio_run(_request(8766, {"id": 5, "cmd": "rule_list"}, 5)).get("items", []))
        info["reminders"] = len(rem.get("items", []))
        info["plugins"] = len(tools.get("names", []))
        info["devices"] = st.get("devices", [])
    except Exception:
        info["daemon"] = False

    from .cli import _probe_options

    info["ollama"] = _probe_options().get("ollama", [])

    env = os.environ
    if Path("~/.config/desk-secretary/env").expanduser().exists():
        for line in Path("~/.config/desk-secretary/env").expanduser().read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k = line.split("=")[0].strip()
                if k and "KEY" in k or "TOKEN" in k or "PASSWORD" in k:
                    env.setdefault(k, "<set-in-env>")

    checks = {
        "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
        "brave search": "BRAVE_SEARCH_API_KEY", "tavily": "TAVILY_API_KEY",
        "telegram": "TELEGRAM_BOT_TOKEN",
    }
    for name, var in checks.items():
        if env.get(var):
            info["keys"].add(name)

    try:
        import tomllib

        cfg_path = Path("~/.config/desk-secretary/config.toml").expanduser()
        if cfg_path.exists():
            data = tomllib.loads(cfg_path.read_text())
            vault = data.get("obsidian", {}).get("vault", "")
            if vault and Path(vault.replace("~", str(Path.home()))).is_dir():
                info["vault"] = True
            ha = data.get("homeassistant", {})
            if ha.get("enabled") and ha.get("url"):
                info["ha"] = True
            g = data.get("gmail", {})
            if g.get("user"):
                info["gmail"] = True
            ww = data.get("wake_word", {})
            info["wake_word"] = bool(ww.get("enabled"))
            db = data.get("dashboard", {})
            info["dashboard"] = bool(db.get("enabled", True))
            if env.get("TELEGRAM_BOT_TOKEN"):
                info["telegram"] = bool(data.get("telegram", {}).get("enabled"))
            ws_ = data.get("websearch", {}).get("provider")
            if ws_ in ("tavily", "brave") and (
                env.get("TAVILY_API_KEY") or env.get("BRAVE_SEARCH_API_KEY")):
                info["search"] = True
            sid = data.get("speaker_id", {})
            info["speaker_id"] = bool(sid.get("enabled"))
    except Exception:
        pass

    state = Path("~/.local/state/desk-secretary/rag.sqlite").expanduser()
    info["rag"] = state.exists() and state.stat().st_size > 10000
    return info


def asyncio_run(coro):
    import asyncio

    return asyncio.run(_wrap(coro))


async def _wrap(coro):
    try:
        return await coro
    except Exception:
        return {}


# ------------------------------------------------------------------ rendering

def _mark(ok: bool, yes="✓", no="—"):
    return f"[green]{yes}[/]" if ok else f"[dim]{no}[/]"


def render(info: dict | None = None):
    info = info or {}
    have = info.get("keys", set())
    console = Console()

    console.print(Panel(Text(
        "xarvii — voice-first desk secretary\n"
        "speak naturally · it handles the rest",
        justify="center"), style="bold cyan", expand=False))

    # ---- conversation
    t = Table.grid(padding=(0, 2))
    t.add_row("🎙", "Push-to-talk + hands-free follow-up window (just keep talking)")
    t.add_row("", "Barge-in: interrupt mid-answer, it stops instantly")
    t.add_row("🌐", "Multilingual — English & Hindi (auto-detected)")
    t.add_row("🔑", f"Wake word: {_mark(info.get('wake_word'))} (enable in config)")
    console.print(Panel(t, title="[bold]🗣 Voice & Conversation[/]", expand=False))

    # ---- brains
    t = Table.grid(padding=(0, 2))
    tiers = info.get("tiers", {})
    fast = tiers.get("fast", "?")
    t.add_row("⚡", f"Fast brain: [bold]{fast}[/]")
    t.add_row("🧠", f"Reasoning: {tiers.get('reasoning', '?')} · Vision: {tiers.get('vision', '?')}")
    t.add_row("🔁", "Cloud fails → local Ollama takes over automatically")
    oll = info.get("ollama", [])
    if oll:
        t.add_row("📦", f"Local models installed: {', '.join(oll[:4])}")
    t.add_row("🧩", f"Agentic tool loops · plugins loaded: {info.get('plugins', 0)}")
    console.print(Panel(t, title="[bold]🧠 Brains[/]", expand=False))

    # ---- voices
    t = Table.grid(padding=(0, 2))
    t.add_row("🔊", f"Current: {info.get('tts', 'piper · lessac')}")
    t.add_row("🎚", "350+ neural voices (edge) · Piper catalog · OpenAI option")
    t.add_row("⬇", "xarvii voices · xarvii voice set <engine/voice>")
    console.print(Panel(t, title="[bold]🔊 Voices[/]", expand=False))

    # ---- secretary skills
    t = Table.grid(padding=(0, 2))
    t.add_row("⏰", f"Reminders ({info.get('reminders', 0)} pending) — messy human times OK:")
    t.add_row("", "[dim]'at 12.38 am' · 'in two minutes' · 'tomorrow 9am'[/]")
    t.add_row("⏱", "Kitchen timers — re-chime until dismissed")
    t.add_row("🌅", "Morning briefing — weather + schedule + tasks + fun fact")
    t.add_row("📓", f"Obsidian: {_mark(info.get('vault'))} read · search · tasks · inbox")
    t.add_row("🗂", f"RAG memory: {_mark(info.get('rag'))} 'what did I write about X?'")
    t.add_row("💸", "Expense ledger — 'spent 250 on groceries'")
    t.add_row("📔", "Evening journaling companion → dated diary note")
    t.add_row("📈", "Standup generator — git commits + tasks → spoken update")
    console.print(Panel(t, title="[bold]📋 Secretary Skills[/]", expand=False))

    # ---- internet & home
    t = Table.grid(padding=(0, 2))
    t.add_row("🌤", "Weather — any city, live (Open-Meteo)")
    t.add_row("🔎", f"Web search: {_mark('search' in info and info['search'])} (add Tavily/Brave key)")
    t.add_row("👁", "Screen-read: {_} — asks permission aloud first".replace("{_}",
              _mark(True)) if False else "👁 Screen-read — with spoken consent gate")
    t.add_row("🏠", f"Home Assistant: {_mark(info.get('ha'))} lights · scenes · climate")
    t.add_row("🪝", "Generic webhooks when HA isn't around")
    console.print(Panel(t, title="[bold]🌐 Internet & Home[/]", expand=False))

    # ---- system
    t = Table.grid(padding=(0, 2))
    t.add_row("🎵", "Media play/pause/skip (any player) · Spotify/YT-Music ready")
    t.add_row("🔊", "Volume up/down/set · brightness · open apps")
    console.print(Panel(t, title="[bold]💻 Device Control[/]", expand=False))

    # ---- integrations & privacy
    tg = info.get("telegram")
    t = Table.grid(padding=(0, 2))
    t.add_row("📱", f"Telegram twin: {_mark(tg)} text your secretary from anywhere")
    t.add_row("🪪", f"Speaker ID: {_mark(info.get('speaker_id'))} guests get chat-only")
    t.add_row("🔌", "MCP servers · drop-in Python plugins")
    t.add_row("🖥", f"Dashboard: {_mark(info.get('dashboard'))} http://localhost:8767")
    console.print(Panel(t, title="[bold]🤖 Integrations[/]", expand=False))

    # ---- privacy
    t = Table.grid(padding=(0, 2))
    t.add_row("🏠", "STT, TTS, notes-memory can run 100% local")
    t.add_row("🗝", "Secrets in chmod-600 env file · never logged")
    t.add_row("🙋", "Every cloud action gated by spoken consent")
    console.print(Panel(t, title="[bold]🔒 Privacy[/]", expand=False))

    # ---- cheat sheet
    console.print(Panel(
        "[bold]cheatsheet[/]\n"
        "  [cyan]xarvii[/]               control center UI\n"
        "  [cyan]xarvii device[/]       voice satellite (ENTER talk · m mute · q quit)\n"
        "  [cyan]xarvii setup[/]        guided credential wizard\n"
        "  [cyan]xarvii ask \"…\"[/]      quick question\n"
        "  [cyan]xarvii remind T W[/]   set reminder\n"
        "  [cyan]xarvii brains/voices[/] browse options\n"
        "  [cyan]xarvii reset[/]        restore defaults",
        title="[bold]⌨ commands[/]", expand=False))


def run_capabilities():
    info = {}
    try:
        info = _probe()
    except Exception:
        pass
    render(info)
    return 0


def about_text() -> Panel:
    return Panel(Text(
        "xarvii — voice-first desk secretary\n"
        "run 'xarvii capabilities' for the full map",
        justify="center"), style="bold cyan", expand=False)


import asyncio  # noqa: E402


def skills_log():  # pragma: no cover
    pass

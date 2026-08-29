"""Guided credential & settings wizard: xarvii setup."""

import getpass
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

ENV_PATH = Path("~/.config/desk-secretary/env").expanduser()
CONFIG_PATH = Path("~/.config/desk-secretary/config.toml").expanduser()


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return val or default


def _ask_yes(prompt: str, default=False) -> bool:
    d = "Y/n" if default else "y/n"
    try:
        val = input(f"{prompt} [{d}]: ").strip().lower()
    except EOFError:
        return default
    if not val:
        return default
    return val in ("y", "yes", "1", "true")


def _ask_secret(prompt: str) -> str:
    try:
        return getpass.getpass(f"{prompt}: ").strip()
    except EOFError:
        return ""


# ------------------------------------------------------------------ validators

def validate_gmail(user: str, password: str):
    import imaplib

    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(user, password)
        conn.select("inbox", readonly=True)
        _, data = conn.search(None, "UNSEEN")
        count = len(data[0].split()) if data and data[0] else 0
        conn.logout()
        return True, f"login OK — {count} unread found"
    except imaplib.IMAP4.error as e:
        return False, f"login failed: {e}"
    except Exception as e:
        return False, f"connection problem: {e}"


def validate_telegram(token: str):
    import httpx

    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            bot = data["result"]
            return True, f"bot '@{bot.get('username')}' confirmed"
        return False, data.get("description", "rejected")
    except Exception as e:
        return False, f"connection problem: {e}"


def validate_ics(url: str):
    from .skills.calendar_ics import events_for_day

    if not url.startswith("https://calendar.google.com/calendar/ical/"):
        return False, "URL should look like https://calendar.google.com/calendar/ical/…"
    events = events_for_day(url, "today")
    if events is None:
        return False, "couldn't fetch/parse that calendar"
    return True, f"parsed OK — {len(events)} events today"


# ------------------------------------------------------------------ flow steps

def _credential_step(title: str, enable: bool) -> tuple[bool, dict, dict]:
    """Returns (enabled?, secrets{}, config{})."""
    console.print(Panel(title, expand=False))
    if not _ask_yes("Enable this integration?", default=enable):
        return False, {}, {}

    secrets, config = {}, {}
    return True, secrets, config


def run_setup(config_path: str | None = None) -> int:
    from .config import set_config_values, upsert_env_file

    console.print(Panel(
        "[bold cyan]xarvii setup[/]\nGuided credentials & integrations.\n"
        "Secrets are stored in ~/.config/desk-secretary/env (chmod 600).\n"
        "Everything is validated live before it's saved.",
        expand=False))

    env_updates: dict = {}
    config_updates: dict = {}
    summary: list[tuple[str, str]] = []

    # ---- owner / persona / weather location
    name = _ask("Your name (for greetings)")
    if name:
        config_updates["owner.name"] = name
        summary.append(("owner.name", name))
    loc = _ask("City for weather", "Mumbai")
    if loc:
        config_updates["owner.location"] = loc
        summary.append(("owner.location", loc))

    # ---- gemini key check
    has_gemini = bool(os.environ.get("GEMINI_API_KEY")) or \
        "GEMINI_API_KEY=" in ENV_PATH.read_text() if ENV_PATH.exists() else False
    console.print(f"\n[bold]Gemini API key[/]: "
                  f"[green]present ✓[/]" if has_gemini else "[yellow]missing[/]")
    if not has_gemini and _ask_yes("Add a Gemini key now? (free at aistudio.google.com/apikey)"):
        while True:
            key = _ask_secret("GEMINI_API_KEY")
            if not key:
                break
            env_updates["GEMINI_API_KEY"] = key
            summary.append(("GEMINI_API_KEY", "***"))
            console.print("[green]saved (unverified)[/]")
            break

    # ---- gmail
    if _ask_yes("\nSet up Gmail unread digests?", default=False):
        user = _ask("Gmail address")
        ok = False
        while not ok:
            pw = _ask_secret("App password (16 chars, from myaccount.google.com/apppasswords)")
            if not pw:
                break
            console.print("[dim]validating…[/]")
            ok, msg = validate_gmail(user, pw.replace(" ", ""))
            console.print(("[green]✓ [/]" if ok else "[red]✗ ") + msg)
            if not ok and not _ask_yes("Retry?"):
                break
        if user:
            config_updates["gmail.user"] = user
            summary.append(("gmail.user", user))
            if pw:
                env_updates["GMAIL_APP_PASSWORD"] = pw.replace(" ", "")
                summary.append(("GMAIL_APP_PASSWORD", "***"))
            config_updates["gmail.enabled"] = None  # placeholder removed below
            config_updates.pop("gmail.enabled")
        else:
            summary.append(("gmail", "skipped"))

    # ---- telegram
    if _ask_yes("\nSet up the Telegram bot twin?", default=False):
        token = _ask_secret("Bot token (from @BotFather)")
        uid = _ask("Your numeric Telegram user id (from @userinfobot)")
        ok = False
        if token:
            console.print("[dim]validating…[/]")
            ok, msg = validate_telegram(token)
            console.print(("[green]✓ [/]" if ok else "[red]✗ ") + msg)
        if token:
            env_updates["TELEGRAM_BOT_TOKEN"] = token
            summary.append(("TELEGRAM_BOT_TOKEN", "***"))
            config_updates["telegram.enabled"] = None
            config_updates.pop("telegram.enabled")
            config_updates["_telegram_enabled"] = True
            if uid.isdigit():
                config_updates["telegram.allowed_user_ids"] = uid
            summary.append(("telegram", f"enabled ({'verified' if ok else 'unverified'})"))

    # ---- calendar
    if _ask_yes("\nSet up Google Calendar (read-only)?", default=False):
        while True:
            url = _ask("Paste secret iCal URL (basic.ics)")
            if not url:
                break
            console.print("[dim]validating…[/]")
            ok, msg = validate_ics(url)
            console.print(("[green]✓ [/]" if ok else "[red]✗ ") + msg)
            if ok or not _ask_yes("Retry?"):
                if url:
                    config_updates["calendar.ics_url"] = url
                    summary.append(("calendar.ics_url", url[:60] + "…"))
                break

    # ---- wake word + briefing time
    ww = _ask_yes("\nEnable wake word ('always listening')? Costs some CPU.", default=False)
    config_updates["wake_word.enabled"] = None
    config_updates.pop("wake_word.enabled")
    config_updates["_ww"] = ww
    bt = _ask("\nMorning briefing time", "08:00")
    if bt:
        config_updates["briefing.time"] = bt
        summary.append(("briefing.time", bt))

    # drop internal marker keys from TOML writes; convert booleans separately
    ww_val = config_updates.pop("_ww", None)
    tg_enable = config_updates.pop("_telegram_enabled", None)

    # ---- write everything
    if env_updates:
        upsert_env_file(ENV_PATH, env_updates)

    toml_bools = {}
    if ww_val is not None:
        toml_bools["wake_word.enabled"] = ww_val
    if tg_enable is not None:
        toml_bools["telegram.enabled"] = tg_enable

    real_updates = {k: v for k, v in config_updates.items()
                    if v is not None and not k.startswith("_")}
    if toml_bools:
        target = Path(config_path) if config_path else CONFIG_PATH
        _write_bools(target, toml_bools)
    if real_updates:
        set_config_values(config_path, real_updates)

    # ---- summary
    console.print(Panel("\n".join(f"[bold]{k}[/] = {v}" for k, v in summary)
                        or "[dim]nothing changed[/]",
                        title="[bold]SUMMARY[/]", expand=False))
    if env_updates:
        console.print(f"[green]✓ {len(env_updates)} secret(s)[/] → {ENV_PATH}")
    if real_updates or toml_bools:
        console.print(f"[green]✓ {len(real_updates) + len(toml_bools)} setting(s)[/] → {CONFIG_PATH}")

    if _ask_yes("\nRestart deskd now to apply?", default=_daemon_running()):
        import subprocess

        r = subprocess.run(["systemctl", "--user", "restart", "deskd-dev"],
                           capture_output=True)
        print("restarted ✓" if r.returncode == 0 else
              "daemon isn't running as a service — start with: systemd-run … or just deskd")
    return 0


def _write_bools(target: Path, bools: dict):
    """TOML needs bare true/false for booleans; line-edit them in."""
    target = Path(target).expanduser()
    lines = target.read_text().splitlines() if target.exists() else []
    for dotted, value in bools.items():
        section, key = dotted.rsplit(".", 1)
        header = f"[{section}]"
        formatted = f"{key} = {'true' if value else 'false'}"
        if header not in [l.strip() for l in lines]:
            if lines:
                lines.append("")
            lines.append(header)
            lines.append(formatted)
            continue
        si = next(i for i, l in enumerate(lines) if l.strip() == header)
        end = len(lines)
        for j in range(si + 1, len(lines)):
            if lines[j].strip().startswith("["):
                end = j
                break
        replaced = False
        for j in range(si + 1, end):
            if lines[j].strip().startswith(key + "=") or lines[j].strip().startswith(key + " "):
                lines[j] = formatted
                replaced = True
                break
        if not replaced:
            lines.insert(end, formatted)
    target.write_text("\n".join(lines) + "\n")


def _daemon_running() -> bool:
    import subprocess

    r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "deskd-dev"])
    return r.returncode == 0

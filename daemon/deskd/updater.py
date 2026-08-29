"""xarvii update — pull latest code, sync deps, restart service."""

import subprocess
from pathlib import Path

from rich.console import Console

console = Console()
ROOT = Path(__file__).resolve().parent.parent


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


def run_update() -> int:
    if not (ROOT / ".git").exists():
        console.print("[red]not a git repo — update via your install method[/]")
        return 1

    console.print("[bold]1/4 · pulling latest code…[/]")
    dirty = _git("status", "--porcelain")
    if dirty.stdout.strip():
        console.print("[yellow]local changes present; stashing…[/]")
        _git("stash")
    r = _git("pull", "--ff-only")
    console.print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        if dirty.stdout.strip():
            _git("stash", "pop")
        return 1
    new_head = _git("rev-parse", "--short", "HEAD").stdout.strip()
    old_head = _git("rev-parse", "--short", "HEAD@{1}") if not dirty.stdout.strip() else "?"
    console.print(f"[dim]{old_head} → {new_head}[/]")

    if dirty.stdout.strip():
        console.print("[yellow]restoring your local changes…[/]")
        _git("stash", "pop")

    console.print("\n[bold]2/4 · syncing python deps…[/]")
    venv_pip = ROOT / ".venv" / "bin" / "pip"
    r = subprocess.run([str(venv_pip), "install", "-q",
                        "-e", "./daemon[audio,stt-local,serial,dev]",
                        "edge-tts", "av", "rich", "fastembed",
                        "feedparser", "resemblyzer", "zeroconf",
                        '"setuptools<81"'])
    if r.returncode != 0:
        console.print("[red]pip sync failed[/]")
        return 1
    console.print("[green]✓ deps synced[/]")

    console.print("\n[bold]3/4 · restarting daemon…[/]")
    import shutil as sh

    if sh.which("systemctl"):
        subprocess.run(["systemctl", "--user", "restart", "deskd-dev"],
                       capture_output=True)
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet",
                                 "deskd-dev"]).returncode == 0
        console.print("[green]✓ daemon restarted[/]" if active else "[red]daemon failed to start[/]")
        if not active:
            return 1
    else:
        console.print("[yellow]start deskd manually to apply[/]")

    console.print("\n[bold]4/4 · doctor quick pass…[/]")
    from .doctor import run_doctor

    run_doctor(play_audio=False)
    console.print("\n[bold green]update complete ✓[/]")
    return 0

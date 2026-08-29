"""xarvii doctor — full diagnostic sweep with ✓/✗/warn board."""

import os
import shutil
import socket
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

ROOT = Path(__file__).resolve().parent.parent


def _check(name, fn):
    try:
        ok, note = fn()
    except Exception as e:
        ok, note = False, f"exception: {e}"
    return (name, ok, note)


def _deps():
    missing = []
    for mod in ("websockets", "httpx", "rich"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return (not missing, "missing: " + ",".join(missing) if missing else "core deps present")


def _daemon():
    import subprocess as sp

    r = sp.run(["systemctl", "--user", "is-active", "deskd-dev"],
               capture_output=True, text=True)
    active = r.stdout.strip() == "active"
    return active, r.stdout.strip()


def _mic_level():
    try:
        import queue
        import time

        import numpy as np
        import sounddevice as sd

        q = queue.Queue()

        def cb(indata, frames, t, status):
            q.put(bytes(indata))

        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=800, callback=cb):
            time.sleep(1.2)
            data = b""
            while not q.empty():
                data += q.get()
        import array as arr

        s = arr.array("h")
        s.frombytes(data[: (len(data) // 2) * 2])
        rms = (sum(x * x for x in s) / max(1, len(s))) ** 0.5
        level = "loud" if rms > 2000 else ("ok" if rms > 100 else "quiet/silent")
        return rms > 30, f"rms={rms:.0f} ({level})"
    except Exception as e:
        return None, f"no audio device: {e}"


def _gemini_key():
    k = os.environ.get("GEMINI_API_KEY", "")
    envf = Path("~/.config/desk-secretary/env").expanduser()
    if not k and envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                k = line.split("=", 1)[1]
    return bool(k), "present" if k else "not set (local-only brains still work)"


def _vault():
    try:
        from .config import load_config

        v = load_config().resolved_vault()
        return v is not None and v.is_dir(), str(v) if v else "not configured"
    except Exception:
        return False, "config error"


def _ollama():
    import httpx

    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=4)
        models = [m["name"] for m in r.json().get("models", [])]
        return True, f"{len(models)} models: {', '.join(models[:3])}"
    except Exception:
        return None, "not running (cloud brains still work)"


def _network():
    import httpx

    try:
        httpx.head("https://www.google.com", timeout=6)
        return True, "online"
    except Exception:
        return None, "offline (local mode)"


def _piper_voice():
    p = Path("~/.local/share/piper/voices").expanduser()
    voices = list(p.glob("*.onnx")) if p.is_dir() else []
    return len(voices) > 0, f"{len(voices)} voice(s) installed"


def _disk():
    usage = shutil.disk_usage(Path.home())
    free_gb = usage.free / 1e9
    return free_gb > 2, f"{free_gb:.1f} GB free"


def _port_open(port):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def run_doctor(play_audio: bool = False) -> int:
    checks = [
        _check("python core deps", _deps),
        _check("daemon service", _daemon),
        _check("device ports 8765/8766/8767",
               lambda: (_port_open(8765) or _port_open(8767), "")),
        _check("microphone input", _mic_level),
        _check("Gemini key", _gemini_key),
        _check("Ollama (optional)", _ollama),
        _check("Network (optional)", _network),
        _check("Obsidian vault", _vault),
        _check("Piper voices", _piper_voice),
        _check("Disk space", _disk),
    ]

    t = Table(title="xarvii doctor", expand=False)
    t.add_column("", width=3)
    t.add_column("check", style="bold")
    t.add_column("result")

    score = 0
    for name, ok, note in checks:
        icon = "[green]✓[/]" if ok is True else (
            "[yellow]![/]" if ok is None else "[red]✗[/]")
        t.add_row(icon, name, str(note))
        if ok is True:
            score += 1
    console.print(t)

    total = len(checks)
    verdict = "healthy" if score >= total - 1 else "needs attention"
    console.print(f"\n[bold]{score}/{total} checks passed[/] — {verdict}")

    if play_audio:
        try:
            import sounddevice as sd

            sd.play(__import__("numpy").frombuffer(
                b"".join(bytes([0, i % 100 + 40]) for i in range(8000)),
                dtype=np.int16), samplerate=16000)
            sd.wait()
            console.print("[dim]played test tone on default output[/]")
        except Exception as e:
            console.print(f"[red]speaker test failed: {e}[/]")
    return 0


import shutil  # noqa: E402

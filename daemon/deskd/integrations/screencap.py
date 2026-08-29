"""Screen capture — Wayland/X11 aware with multiple backend fallbacks."""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger("deskd.screencap")


async def _run(cmd: list[str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    ok = proc.returncode == 0
    if not ok and err:
        log.debug("capture cmd failed: %s", err.decode()[:200])
    return ok


def _file_ok(path: str) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size > 500


async def capture_screen() -> bytes:
    """Capture screen → PNG bytes. Tries Wayland/GNOME first, then X11."""
    import time as _t

    stamp = str(int(_t.time() * 1000))
    tmp = f"/tmp/xarvii_screen_{stamp}.png"

    # ---- Wayland / GNOME ----
    if shutil.which("gnome-screenshot"):
        if await _run(["gnome-screenshot", "-f", tmp]):
            if _file_ok(tmp):
                data = Path(tmp).read_bytes()
                Path(tmp).unlink(missing_ok=True)
                log.info("screen captured via gnome-screenshot (%d bytes)", len(data))
                return data

    # GNOME Shell built-in (D-Bus)
    if "WAYLAND_DISPLAY" in __import__("os").environ or        shutil.which("gdbus"):
        proc = await asyncio.create_subprocess_exec(
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell.Screenshot",
            "--object-path", "/org/gnome/Shell/Screenshot",
            "--method", "org.gnome.Shell.Screenshot.Screenshot",
            "true", "false", tmp,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        if _file_ok(tmp):
            data = Path(tmp).read_bytes()
            Path(tmp).unlink(missing_ok=True)
            log.info("screen captured via gnome-shell dbus (%d bytes)", len(data))
            return data

    # ---- X11 fallbacks ----
    if shutil.which("scrot"):
        if await _run(["scrot", "-o", tmp]):
            if _file_ok(tmp):
                data = Path(tmp).read_bytes()
                Path(tmp).unlink(missing_ok=True)
                return data

    if shutil.which("import"):
        if await _run(["import", "-window", "root", tmp]):
            if _file_ok(tmp):
                data = Path(tmp).read_bytes()
                Path(tmp).unlink(missing_ok=True)
                return data

    raise RuntimeError(
        "no working screen capture backend. "
        "Install: sudo apt install gnome-screenshot")

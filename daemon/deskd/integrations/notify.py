import logging
import shutil
import subprocess

log = logging.getLogger("deskd.notify")


def desktop_notify(title: str, body: str = "") -> bool:
    if not shutil.which("notify-send"):
        log.info("[notify] %s: %s", title, body)
        return False
    try:
        subprocess.run(
            ["notify-send", "-a", "deskd", title, body],
            timeout=5,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        log.exception("notify-send failed")
        return False

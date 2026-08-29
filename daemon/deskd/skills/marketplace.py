"""Skill marketplace: install one-file skills from an index URL or direct link."""

import json
import logging
import os
import urllib.request
from pathlib import Path

log = logging.getLogger("deskd.market")

DEFAULT_INDEX = os.environ.get(
    "XARVII_SKILL_INDEX",
    "https://raw.githubusercontent.com/xarvii/skills/main/index.json")


def _fetch(url: str, timeout: int = 20) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def fetch_index(index_url: str | None = None) -> list[dict]:
    url = index_url or DEFAULT_INDEX
    try:
        data = json.loads(_fetch(url))
        return data.get("skills", [])
    except Exception as e:
        log.warning("skill index unreachable (%s): %s", url, e)
        return []


def install(source: str, plugins_dir: str) -> Path:
    """source = marketplace name (resolved via index), direct .py URL, or local path."""
    d = Path(plugins_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)

    src = Path(source).expanduser()
    if src.suffix == ".py" and src.is_file():
        code = src.read_text(errors="replace")
        name = src.stem
    elif source.startswith(("http://", "https://")) and source.endswith(".py"):
        code = _fetch(source).decode(errors="replace")
        name = Path(source).stem
    else:
        entry = next((s for s in fetch_index() if s["name"] == source), None)
        if entry is None:
            raise ValueError(f"skill {source!r} not in index")
        url, name = entry["file"], entry["name"]
        code = _fetch(url).decode(errors="replace")

    if "def register(" not in code:
        raise ValueError("not a valid xarvii skill (missing register())")

    out = d / f"{name}.py"
    if out.exists():
        raise ValueError(f"skill {name!r} already installed — remove it first")
    out.write_text(code)
    log.info("skill installed: %s -> %s", name, out)
    return out


def installed(plugins_dir: str) -> list[str]:
    d = Path(plugins_dir).expanduser()
    return sorted(p.stem for p in d.glob("*.py")) if d.is_dir() else []


def remove(name: str, plugins_dir: str) -> bool:
    p = Path(plugins_dir).expanduser() / f"{name}.py"
    if p.exists():
        p.unlink()
        return True
    return False

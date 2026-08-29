"""Drop-in plugin system: *.py files in the plugins dir register extra tools.

A plugin is any Python file defining:

    def register(registry, ctx):
        registry.register("my_tool", "description", {...schema...}, handler)

`ctx` exposes: cfg, vault, reminders, rules, speaker_id, log.
Broken plugins are logged and skipped — never fatal.
"""

import importlib.util
import logging
from pathlib import Path

log = logging.getLogger("deskd.plugins")


def load_plugins(registry, plugins_dir: str | Path, ctx) -> int:
    d = Path(plugins_dir).expanduser()
    if not d.is_dir():
        return 0
    loaded = 0
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"xarvii_plugin_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                mod.register(registry, ctx)
                loaded += 1
                log.info("plugin loaded: %s", path.name)
            else:
                log.warning("plugin %s has no register(); skipped", path.name)
        except Exception:
            log.exception("plugin %s failed to load; skipping", path.name)
    return loaded

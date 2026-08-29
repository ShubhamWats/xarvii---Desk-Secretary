import asyncio
import json
import threading
import urllib.request

import pytest

from deskd.dashboard import Dashboard


class FakeStore:
    def list(self, pending_only=True):
        return [{"id": "r1", "title": "tea", "due": "2026-08-25T10:00:00"}]

    def add(self, title, due):
        return {"id": "r9", "title": title, "due": due.isoformat(timespec="seconds")}

    def remove(self, rid):
        return rid == "r1"


class FakeTimers:
    def describe(self):
        return "chai: 0:30 left"


class FakeCfg:
    class dashboard:
        enabled = True
        host = "127.0.0.1"
        port = 8799
        token = ""
    class tts:
        voice = ""
    def __init__(self):
        self.reminders = None


@pytest.mark.asyncio
async def test_dashboard_endpoints(tmp_path, monkeypatch):
    from deskd.config import DashboardCfg

    srv = type("S", (), {})()
    srv.sessions = []
    srv.reminder_store = FakeStore()
    srv.timers = FakeTimers()
    srv.rules = type("R", (), {"list": lambda s: []})()
    srv.cfg = type("C", (), {"demo": False})()
    srv.cfg.dashboard = DashboardCfg(enabled=True, host="127.0.0.1",
                                     port=8799, token="")
    srv.cfg.tts = type("T", (), {"voice": "en-IN-NeerjaNeural"})
    srv.cfg.owner = type("O", (), {"name": "Subham"})()
    srv.brain_status = lambda: {"tiers": {"fast": "gemini/gemini-3.6-flash"},
                                "stt_engine": "whisper", "tts_engine": "piper"}
    srv.apply_brain = lambda k, v: {"ok": True}
    srv.registry = type("RG", (), {"names": lambda s: ["demo_tool"]})()

    dash = Dashboard(srv, srv.cfg)
    dash.start()
    try:
        base = "http://127.0.0.1:8799"

        def get(path):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                body = r.read().decode()
                ctype = r.headers.get("Content-Type", "")
                return json.loads(body) if "json" in ctype else body

        page = get("/")
        assert "<h1>◈ xarvii" in page
        st = get("/api/status")
        assert st["daemon"] is True and st["reminders_pending"] == 1
        b = get("/api/brains")
        assert b["tiers"]["fast"].startswith("gemini/")
        t = get("/api/timers")
        assert "chai" in t["describe"]
    finally:
        dash.stop()


def test_plugin_loader(tmp_path):
    import asyncio

    from deskd.plugins import load_plugins
    from deskd.tools.registry import ToolRegistry

    plug = tmp_path / "hello_plugin.py"
    plug.write_text(
        "def register(registry, ctx):\n"
        "    registry.register('hello_tool', 'says hi', {}, lambda: {'hi': 1})\n")
    bad = tmp_path / "_skipme.py"
    bad.write_text("raise RuntimeError('never loaded')\n")

    reg = ToolRegistry()
    n = load_plugins(reg, tmp_path, ctx=None)
    assert n == 1
    assert "hello_tool" in reg.names()
    result = asyncio.run(reg.call("hello_tool"))
    assert result == {"hi": 1}


def test_plugin_broken_is_skipped(tmp_path):
    from deskd.plugins import load_plugins
    from deskd.tools.registry import ToolRegistry

    bad = tmp_path / "broken.py"
    bad.write_text("1/0\n\ndef register(r, c): pass\n")
    good = tmp_path / "good.py"
    good.write_text("def register(r, c):\n    r.register('ok_tool','',{},lambda:1)\n")

    reg = ToolRegistry()
    n = load_plugins(reg, tmp_path, ctx=None)
    assert n == 1 and "ok_tool" in reg.names()

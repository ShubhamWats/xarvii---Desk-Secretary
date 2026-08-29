import pytest

import deskd.skills.rules_engine as re_mod
from deskd.skills.rules_engine import RulesEngine, _dig


def test_dig_paths():
    obj = {"a": {"b": [10, 20]}}
    assert _dig(obj, "a.b.1") == 20
    assert _dig(obj, "a.x") is None


class FakeResp:
    def __init__(self, payload=None, text=""):
        self._p = payload
        self.text = text

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


def patch_client(monkeypatch, payloads=None, texts=None):
    payloads = list(payloads or [])
    texts = list(texts or [])

    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url):
            return FakeResp(payloads.pop(0) if payloads else {},
                            texts.pop(0) if texts else "")

    monkeypatch.setattr(re_mod.httpx, "AsyncClient", C)


@pytest.mark.asyncio
async def test_github_stars_trigger_and_rearm(tmp_path, monkeypatch):
    alerts = []
    eng = RulesEngine(tmp_path / "rules.json",
                      on_alert=lambda r: alerts.append(r), interval_minutes=1)
    eng.add("github_stars", {"repo": "x/y", "op": ">=", "value": 100},
            message="stars hit")

    patch_client(monkeypatch, payloads=[{"stargazers_count": 2000}])
    await eng.check_all()
    assert eng._rules[0]["fired_at_state"] is True
    assert len(alerts) == 1

    patch_client(monkeypatch, payloads=[{"stargazers_count": 5}])
    eng._rules[0]["last_check"] = 0          # simulate interval elapsed
    await eng.check_all()
    assert eng._rules[0]["fired_at_state"] is False   # re-armed


@pytest.mark.asyncio
async def test_rss_keyword(tmp_path, monkeypatch):
    fired = []
    eng = RulesEngine(tmp_path / "r.json", on_alert=lambda r: fired.append(r))
    eng.add("rss_keyword", {"url": "https://e.example/rss", "keyword": "launch"},
            message="news!")
    sample = "<?xml version='1.0'?><rss version='2.0'><channel><item>" \
             "<title>Rocket launch today</title></item></channel></rss>"
    patch_client(monkeypatch, texts=[sample])
    await eng.check_all()
    assert fired and fired[0]["last_value"].startswith("Rocket")


def test_remove(tmp_path):
    eng = RulesEngine(tmp_path / "r.json", on_alert=None)
    r = eng.add("github_stars", {"repo": "a/b", "op": ">=", "value": 1}, "m")
    assert eng.remove(r["id"][:4]) is True

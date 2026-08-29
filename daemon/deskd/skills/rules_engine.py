"""Proactive rules engine: watchers that speak when conditions are met.

Rules live in ~/.config/desk-secretary/rules.json:
  {"id": "...", "type": "github_stars|rss_keyword|json_num",
   "params": {...}, "message": "spoken alert", "armed": true}

Types:
  github_stars {repo, op:">"|">=", value:int}
  rss_keyword  {url, keyword}
  json_num     {url, path:"a.b.c", op, value}   (generic JSON API watcher)
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("deskd.rules")

_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def _dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


class RulesEngine:
    def __init__(self, path, on_alert, interval_minutes: int = 5):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.on_alert = on_alert              # async fn(rule) -> None
        self.interval_s = max(60, interval_minutes * 60)
        self._task = None
        self._rules: list[dict] = []
        self._load()

    def _load(self):
        if self.path.is_file():
            try:
                self._rules = json.loads(self.path.read_text())
            except Exception:
                log.exception("rules load failed")
                self._rules = []

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._rules, indent=1))
        tmp.replace(self.path)

    def add(self, rtype: str, params: dict, message: str = "") -> dict:
        rule = {"id": uuid.uuid4().hex[:8], "type": rtype, "params": params,
                "message": message or f"Rule {rtype} triggered.",
                "armed": True, "last_value": None,
                "last_check": 0.0}
        self._rules.append(rule)
        self._save()
        return rule

    def remove(self, rid_or_prefix: str) -> bool:
        for i, r in enumerate(self._rules):
            if r["id"].startswith(rid_or_prefix):
                self._rules.pop(i)
                self._save()
                return True
        return False

    def list(self) -> list[dict]:
        return [dict(r) for r in self._rules]

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        log.info("rules loop running (%d rules, every %ds)",
                 len(self._rules), self.interval_s)
        while True:
            await self.check_all()
            await asyncio.sleep(self.interval_s)

    async def check_all(self):
        now = time.time()
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for rule in self._rules:
                if not rule.get("armed", True):
                    continue
                if now - rule.get("last_check", 0) < self.interval_s:
                    continue
                rule["last_check"] = now
                try:
                    triggered, value = await self._eval(client, rule)
                    log.info("rule %s evaluated: triggered=%s value=%r",
                             rule["id"], triggered, value)
                except Exception as e:
                    log.warning("rule %s eval failed: %s", rule["id"], e)
                    continue
                rule["last_value"] = value
                if triggered and not rule.get("fired_at_state"):
                    rule["fired_at_state"] = True
                    log.info("RULE TRIGGERED %s (%s)", rule["id"], rule["type"])
                    if self.on_alert:
                        res = self.on_alert(rule)
                        if hasattr(res, "__await__"):
                            await res
                elif not triggered and rule.get("fired_at_state"):
                    rule["fired_at_state"] = False      # re-arm on reset
            self._save()

    async def _eval(self, client, rule):
        rt, p = rule["type"], rule["params"]
        op_name, threshold = p.get("op", ">="), float(p.get("value", 0))
        op = _OPS.get(op_name, _OPS[">="])
        if rt == "github_stars":
            r = await client.get(f"https://api.github.com/repos/{p['repo']}")
            r.raise_for_status()
            val = float(r.json().get("stargazers_count", 0))
            return op(val, threshold), f"{val:.0f}"
        if rt == "json_num":
            r = await client.get(p["url"])
            r.raise_for_status()
            val = float(_dig(r.json(), p.get("path", "")))
            return op(val, threshold), str(val)
        if rt == "rss_keyword":
            import feedparser

            r = await client.get(p["url"])
            feed = feedparser.parse(r.text)
            kw = p["keyword"].lower()
            for entry in feed.entries[:20]:
                blob = (entry.get("title", "") + " " +
                        entry.get("summary", "")[:400]).lower()
                if kw in blob:
                    return True, entry.get("title", "")[:120]
            return False, ""
        raise ValueError(f"unknown rule type {rt!r}")

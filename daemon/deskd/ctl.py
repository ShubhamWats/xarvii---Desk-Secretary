import asyncio
import json
import logging
from datetime import datetime

from websockets.asyncio.server import serve as ws_serve

log = logging.getLogger("deskd.ctl")


class ControlApi:
    """Local control plane for deskctl and integrations."""

    def __init__(self, server):
        self.server = server

    async def start(self):
        return await ws_serve(self._handler, self.server.cfg.server.ctl_host, self.server.cfg.server.ctl_port)

    async def _handler(self, ws):
        log.info("ctl client connected")
        try:
            async for raw in ws:
                try:
                    req = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({"ok": False, "error": "bad json"}))
                    continue
                try:
                    resp = await self._handle(req)
                except Exception as e:
                    log.exception("ctl command failed")
                    resp = {"ok": False, "error": str(e)}
                resp.setdefault("id", req.get("id"))
                await ws.send(json.dumps(resp))
        finally:
            log.info("ctl client disconnected")

    async def _handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        srv = self.server
        if cmd == "status":
            return {
                "ok": True,
                "devices": [{"device": s.device, "state": s.state, "muted": s.muted} for s in srv.sessions],
                "reminders_pending": len(srv.reminder_store.list()),
                "demo": srv.cfg.demo,
            }
        if cmd == "add_reminder":
            title = str(req["title"])
            due_raw = req.get("due")
            due = (
                datetime.fromisoformat(due_raw)
                if due_raw
                else None
            ) or datetime.now()
            item = await srv.ctl_add_reminder(title, due)
            await srv.broadcast(lambda s: s.announce_reminder(item))
            return {"ok": True, "reminder": item}
        if cmd == "reminders_list":
            return {"ok": True, "items": srv.reminder_store.list()}
        if cmd == "reminder_remove":
            ok = srv.reminder_store.remove(str(req["id"]))
            return {"ok": ok}
        if cmd == "brain_status":
            return srv.brain_status()
        if cmd == "brain_set":
            res = srv.apply_brain(str(req["key"]), str(req["value"]))
            return res
        if cmd == "tool_list":
            return {"ok": True, "names": srv.registry.names()}
        if cmd == "rule_list":
            return {"ok": True, "items": srv.rules.list()}
        if cmd == "rule_add":
            rule = srv.rules.add(str(req["type"]), dict(req.get("params") or {}),
                                 str(req.get("message", "")))
            resp = {"ok": True}
            resp.update(rule)
            resp.pop("id", None)
            return resp
        if cmd == "rule_remove":
            return {"ok": bool(srv.rules.remove(str(req["id_prefix"])))}
        if cmd == "rag_rebuild":
            n = await srv.rag.rebuild_if_stale(0) if srv.rag else 0
            return {"ok": True, "chunks": n or 0}
        if cmd == "ask":
            delivered = await srv.speak_on_device(str(req["text"]))
            return {"ok": True, "delivered_to_device": delivered}
        if cmd == "stop":
            srv._stop.set()
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}

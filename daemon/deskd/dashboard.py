"""LAN web dashboard served by the daemon (stdlib only, no extra deps)."""

import asyncio
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("deskd.dashboard")

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>xarvii dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b1020;--card:#141a2e;--fg:#e8ecf8;--dim:#8b93ad;--acc:#5eead4;--warn:#fbbf24}
*{box-sizing:border-box}body{background:var(--bg);color:var(--fg);
 font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px;max-width:980px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--dim);font-size:13px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border-radius:14px;padding:16px 18px;border:1px solid #232b45}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--acc);margin:0 0 10px}
.row{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px dashed #232b45}
.row:last-child{border:none}.k{color:var(--dim)}.v{text-align:right;word-break:break-word}
input,select,button{font:inherit;background:#0e1430;color:var(--fg);
 border:1px solid #2c3560;border-radius:8px;padding:7px 10px;width:100%;margin:4px 0}
button{background:#173055;cursor:pointer}button:hover{background:#1d3d70}
button.mini{width:auto;padding:4px 10px;font-size:12px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}
.on{background:#34d399}.off{background:#ef4444}
ul{margin:4px 0;padding-left:18px}li{padding:2px 0}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);
 background:#173055;padding:8px 18px;border-radius:20px;display:none}
</style></head><body>
<h1>◈ xarvii <span id="dot" class="dot off"></span></h1>
<div class="sub">desk secretary control center — auto-refreshes</div>
<div class="grid">
<div class="card"><h2>Status</h2><div id="status">…</div></div>
<div class="card"><h2>Brains</h2><div id="brains"></div>
 <select id="tierSel"><option value="fast">fast</option><option value="reasoning">reasoning</option><option value="vision">vision</option></select>
 <select id="modelSel"></select>
 <button onclick="setBrain()">apply brain</button>
 <div id="models" style="margin-top:8px;color:var(--dim);font-size:12px"></div></div>
<div class="card"><h2>Voice (TTS)</h2><div id="tts"></div>
 <select id="voiceSel">
  <option value="">— choose —</option>
  <optgroup label="edge neural"><option>edge/en-IN-NeerjaNeural</option><option>edge/en-IN-PrabhatNeural</option><option>edge/en-US-AndrewNeural</option><option>edge/hi-IN-SwaraNeural</option><option>edge/en-GB-SoniaNeural</option></optgroup>
 </select>
 <button onclick="setVoice()">apply voice</button>
 <div class="sub" style="margin-top:6px">piper voices: install via CLI then restart</div></div>
<div class="card"><h2>Reminders</h2><div id="rems"></div>
 <input id="rTitle" placeholder="title"><input id="rWhen" placeholder="in 30m | at 17:30 | tomorrow 9am">
 <button onclick="addReminder()">add reminder</button></div>
<div class="card"><h2>Timers</h2><div id="timers">none</div></div>
<div class="card"><h2>Rules</h2><div id="rules"></div></div>
<div class="card"><h2>Say something</h2>
 <input id="sayText" placeholder="text to speak on device">
 <button onclick="say()">🔊 speak</button></div>

<div class="card"><h2>⚙ Setup</h2>
 <details open><summary>Brain key (Gemini)</summary>
  <input id="suGemini" placeholder="GEMINI_API_KEY">
  <button onclick="setupSave('gemini')">save + switch tiers</button></details>
 <details><summary>Owner</summary>
  <input id="suName" placeholder="your name"><input id="suLoc" placeholder="city (weather)">
  <button onclick="setupSave('owner')">save</button></details>
 <details><summary>Gmail digest</summary>
  <input id="suGmailU" placeholder="you@gmail.com">
  <input id="suGmailP" type="password" placeholder="app password">
  <button onclick="setupTest('gmail')">test</button>
  <button onclick="setupSave('gmail')">save</button></details>
 <details><summary>Telegram twin</summary>
  <input id="suTgT" placeholder="bot token"><input id="suTgU" placeholder="your numeric id">
  <button onclick="setupTest('telegram')">test</button>
  <button onclick="setupSave('telegram')">save+enable</button></details>
 <details><summary>Calendar (read-only ICS)</summary>
  <input id="suCal" placeholder="secret iCal URL">
  <button onclick="setupTest('calendar')">test</button>
  <button onclick="setupSave('calendar')">save</button></details>
 <div class="row" style="margin-top:8px"><span class="k">wake word</span>
  <button class="mini" onclick="setupSave('misc',{wake_word:true})">on</button>
  <button class="mini" onclick="setupSave('misc',{wake_word:false})">off</button></div>
 <div style="color:var(--dim);font-size:12px;margin-top:6px">daemon restart applies some fields: systemctl --user restart deskd-dev</div>
</div>
</div><div id="toast"></div>
<script>
const QS = location.search;
async function api(path, opts){ const r = await fetch(path+QS, opts); return r.json(); }
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2500)}
async function refresh(){
 try{
  const st = await api('/api/status');
  document.getElementById('dot').className = 'dot '+(st.daemon?'on':'off');
  let s='';
  s+=row('devices', (st.devices||[]).map(d=>`${d.device} (${d.state})`).join(', ')||'none');
  s+=row('reminders pending', st.reminders_pending);
  s+=row('demo', st.demo);
  document.getElementById('status').innerHTML=s;
  const b=await api('/api/brains');
  document.getElementById('brains').innerHTML =
    row('fast',b.tiers.fast)+row('reasoning',b.tiers.reasoning)+row('vision',b.tiers.vision)+
    row('stt',b.stt_engine)+row('tts',b.tts_engine+' · '+(b.tts_voice||'default'));
  document.getElementById('tts').innerHTML = row('engine',b.tts_engine)+row('voice',b.tts_voice||'default');
  const r=await api('/api/reminders');
  document.getElementById('rems').innerHTML = r.items.length? r.items.map(i=>
    `<div class="row"><span>${esc(i.title)}</span><span>${i.due.slice(11,16)} <button class="mini" onclick="rm('${i.id}')">✕</button></span></div>`).join('')
    : '<span class="k">none</span>';
  const t=await api('/api/timers');
  document.getElementById('timers').textContent = t.describe || 'none';
  const ru=await api('/api/rules');
  document.getElementById('rules').innerHTML = ru.items.length? ru.items.map(i=>
    `<div class="row"><span>${esc(i.type)}</span><span class="k">${esc(String(i.last_value??''))}</span></div>`).join('')
    : '<span class="k">no rules</span>';
 }catch(e){document.getElementById('status').textContent='daemon unreachable';}
}
function row(k,v){return `<div class="row"><span class="k">${k}</span><span class="v">${esc(String(v))}</span></div>`}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function addReminder(){
 const title=document.getElementById('rTitle').value.trim();
 const when=document.getElementById('rWhen').value.trim();
 if(!title||!when) return toast('title + when required');
 const r=await fetch('/api/reminders/add'+QS,{method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify({title,when})});
 const j=await r.json(); toast(j.ok? 'scheduled ✓':'error: '+j.error); refresh();
}
async function rm(id){
 await fetch('/api/reminders/remove'+QS,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
 refresh();}
async function say(){
 const text=document.getElementById('sayText').value.trim(); if(!text) return;
 await fetch('/api/say'+QS,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
 toast('sent to device');}
async function setBrain(){
 const tier=document.getElementById('tierSel').value;
 const model=document.getElementById('modelSel').value || document.getElementById('modelSel').dataset.free;
 if(!model) return toast('type a provider/model first');
 const r=await fetch('/api/brain_set'+QS,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({key:'llm.tiers.'+tier,value:model})});
 const j=await r.json(); toast(j.ok? `${tier} → ${model}` : j.error); refresh();}
async function setupTest(kind){
 let payload={kind};
 for(const [id,key] of [['suGmailU','user'],['suGmailP','password'],
   ['suTgT','token'],['suTgU','user_id'],['suCal','url']]){
  const el=document.getElementById(id); if(el&&el.value) payload[key]=el.value;}
 const r=await fetch('/api/setup/test'+QS,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const j=await r.json(); toast((j.ok?'✓ ':'✗ ')+j.message);}
async function setupSave(kind, extra){
 let payload={kind,...(extra||{})};
 const map={gemini:['suGemini','key'], owner:['suName','name'], gmail:['suGmailU','user']};
 if(map[kind]){const el=document.getElementById(map[kind][0]);
  if(el&&el.value.trim()) payload[map[kind][1]]=el.value.trim();}
 if(kind==='gmail'){const p=document.getElementById('suGmailP');
  if(p&&p.value.trim()) payload.password=p.value.trim();}
 if(kind==='telegram'){const t=document.getElementById('suTgT');
  if(t&&t.value.trim()) payload.token=t.value.trim();
  const u=document.getElementById('suTgU');
  if(u&&u.value.trim()) payload.user_id=u.value.trim();}
 if(kind==='calendar'){const c=document.getElementById('suCal');
  if(c&&c.value.trim()) payload.url=c.value.trim();}
 if(kind==='owner'){const n=document.getElementById('suName');
  if(n&&n.value.trim()) payload.name=n.value.trim();
  const l=document.getElementById('suLoc'); if(l&&l.value.trim()) payload.location=l.value.trim();}
 if(kind==='gemini'&&!payload.key) return toast('enter the key first');
 const r=await fetch('/api/setup/save'+QS,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const j=await r.json(); toast(j.ok? 'saved ✓ '+j.saved : 'error: '+j.error);}

async function setVoice(){
 const ev=document.getElementById('voiceSel').value.split('/');
 const r=await fetch('/api/brain_set'+QS,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({key:'tts.engine',value:ev[0]})});
 await fetch('/api/brain_set'+QS,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({key:'tts.voice',value:ev[1]||''})});
 toast(r.ok? 'voice applied':'failed'); refresh();}
(async function loadModels(){
 const m=await api('/api/models');
 const sel=document.getElementById('modelSel'); sel.innerHTML='';
 for(const [prov,list] of Object.entries(m)){
  list.forEach(model=>{const o=document.createElement('option');o.value=`${prov}/${model}`;o.textContent=`${prov}/${model}`;sel.appendChild(o);});}
 sel.dataset.free='gemini/gemini-3.6-flash';
 const custom=document.createElement('option');custom.textContent='(type custom below ↓)';sel.appendChild(custom);
})();
setInterval(refresh,5000);refresh();
</script></body></html>"""


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, default=str).encode()


class Dashboard:
    def __init__(self, server, cfg):
        self.server = server
        self.cfg = cfg.dashboard
        self.loop = asyncio.get_running_loop()
        self._http = None
        self._thread = None
        self._model_cache = {"data": {}, "ts": 0.0}

    # ------------------------------------------------------------- handlers

    def _authed(self, handler) -> bool:
        token = self.cfg.token
        if not token:
            return True
        q = "token=" in (handler.path or "")
        hdr = handler.headers.get("X-Token") == token
        return hdr or q and token in handler.path

    def _snapshot(self) -> dict:
        srv = self.server
        return {
            "ok": True,
            "daemon": True,
            "devices": [{"device": s.device, "state": s.state, "muted": s.muted}
                        for s in srv.sessions],
            "reminders_pending": len(srv.reminder_store.list()),
            "timers": srv.timers.describe(),
            "demo": bool(getattr(srv.cfg, "demo", False)),
            "owner": getattr(getattr(srv.cfg, "owner", None), "name", ""),
        }

    def handle(self, method: str, path: str, body: dict):
        srv = self.server
        route = (method, path.split("?")[0])

        if route[1] != "/" and not path.startswith("/api"):
            pass
        if route == ("GET", "/api/status"):
            snap = self._snapshot()
            brains = srv.brain_status()
            snap.update({"tiers": brains["tiers"],
                         "stt_engine": brains["stt_engine"],
                         "tts_engine": brains["tts_engine"],
                         "tts_voice": brains.get("tts_voice", "")})
            return snap
        if route == ("GET", "/api/brains"):
            return srv.brain_status()
        if route == ("GET", "/api/reminders"):
            return {"ok": True, "items": srv.reminder_store.list()}
        if route == ("POST", "/api/reminders/add"):
            from .scheduler.reminders import parse_when

            due = parse_when(str(body.get("when", "")))
            if due is None:
                return {"ok": False, "error": "unparseable time"}
            item = srv.reminder_store.add(str(body.get("title")), due)
            asyncio.run_coroutine_threadsafe(
                srv.broadcast(lambda s: s.announce_reminder(item)), self.loop)
            return {"ok": True, "reminder": item}
        if route == ("POST", "/api/reminders/remove"):
            ok = srv.reminder_store.remove(str(body.get("id", "")))
            return {"ok": ok}
        if route == ("GET", "/api/timers"):
            return {"describe": srv.timers.describe() or ""}
        if route == ("GET", "/api/rules"):
            return {"items": srv.rules.list()}
        if route == ("POST", "/api/brain_set"):
            res = srv.apply_brain(str(body.get("key")), str(body.get("value")))
            return res
        if route == ("POST", "/api/say"):
            text = str(body.get("text", "")).strip()
            if not text:
                return {"ok": False, "error": "empty"}
            fut = asyncio.run_coroutine_threadsafe(
                srv.speak_on_device(text), self.loop)
            delivered = fut.result(timeout=30)
            return {"ok": delivered,
                    "note": "" if delivered else "no device connected"}
        if route == ("GET", "/api/models"):
            import time as _t

            now = _t.time()
            if now - self._model_cache["ts"] > 60:
                from .cli import _probe_options

                self._model_cache = {"data": _probe_options(), "ts": now}
            return self._model_cache["data"]
        if route == ("GET", "/api/setup"):
            return self._setup_snapshot()
        if route == ("POST", "/api/setup/test"):
            kind = str(body.get("kind"))
            from .setup import validate_gmail, validate_telegram, validate_ics

            if kind == "gmail":
                ok, msg = validate_gmail(str(body.get("user", "")),
                                         str(body.get("password", "")).replace(" ", ""))
            elif kind == "telegram":
                ok, msg = validate_telegram(str(body.get("token", "")))
            elif kind == "calendar":
                ok, msg = validate_ics(str(body.get("url", "")))
            else:
                return {"ok": False, "error": f"unknown test kind {kind!r}"}
            return {"ok": ok, "message": msg}
        if route == ("POST", "/api/setup/save"):
            return self._setup_save(body)
        if route == ("GET", "/api/tools"):
            return {"names": srv.registry.names()}
        return None

    # ---------------------------------------------------------------- server

    def _make_handler(self):
        dash = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):     # quiet
                pass

            def _reply(self, code, payload=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path in ("/", "/index.html"):
                    if not dash._authed(self):
                        return self._reply(401, b'"unauthorized"', "application/json")
                    return self._reply(200, _PAGE.encode(), "text/html; charset=utf-8")
                if u.path.startswith("/api"):
                    if not dash._authed(self):
                        return self._reply(401, b'"unauthorized"', "application/json")
                    try:
                        result = dash.handle("GET", u.path, {})
                        if result is None:
                            return self._reply(404, b'"not found"',
                                               "application/json")
                        return self._reply(200, _json_bytes(result))
                    except Exception as e:
                        log.exception("dashboard GET %s failed", u.path)
                        return self._reply(500, _json_bytes({"error": str(e)}),
                                           "application/json")
                self._reply(404)

            def do_POST(self):
                u = urlparse(self.path)
                if not u.path.startswith("/api"):
                    return self._reply(404)
                if not dash._authed(self):
                    return self._reply(401, b'"unauthorized"', "application/json")
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    body = {}
                try:
                    result = dash.handle("POST", u.path, body)
                    if result is None:
                        return self._reply(404, b'"not found"',
                                           "application/json")
                    return self._reply(200, _json_bytes(result))
                except Exception as e:
                    log.exception("dashboard POST %s failed", u.path)
                    return self._reply(500, _json_bytes({"error": str(e)}),
                                       "application/json")

        return H

    def _setup_snapshot(self) -> dict:
        cfg = self.server.cfg
        envf = Path("~/.config/desk-secretary/env").expanduser()
        env_keys = {}
        if envf.exists():
            for line in envf.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k = line.split("=", 1)[0].strip()
                    env_keys[k] = True
        return {
            "owner_name": getattr(cfg.owner, "name", ""),
            "location": getattr(cfg.owner, "location", ""),
            "gemini_set": bool(env_keys.get("GEMINI_API_KEY")),
            "gmail_user": cfg.gmail.user,
            "telegram_enabled": cfg.telegram.enabled,
            "calendar_url": bool(cfg.calendar.ics_url),
            "wake_word": cfg.wake_word.enabled,
            "briefing_time": cfg.briefing.time,
            "websearch_provider": cfg.websearch.provider,
        }

    def _setup_save(self, body: dict) -> dict:
        from .config import set_config_values, upsert_env_file

        kind = str(body.get("kind"))
        results = []
        env_updates: dict = {}
        config_updates: dict = {}

        if kind == "owner":
            for key in ("name", "location"):
                v = str(body.get(key, "")).strip()
                if v:
                    config_updates[f"owner.{key}"] = v

        elif kind == "gemini":
            key = str(body.get("key", "")).strip()
            if key:
                env_updates["GEMINI_API_KEY"] = key
                for tier in ("fast", "reasoning", "vision"):
                    config_updates[f"llm.tiers.{tier}"] = "gemini/gemini-3.6-flash"

        elif kind == "gmail":
            user = str(body.get("user", "")).strip()
            pw = str(body.get("password", "")).replace(" ", "")
            if user:
                config_updates["gmail.user"] = user
            if pw:
                env_updates["GMAIL_APP_PASSWORD"] = pw

        elif kind == "telegram":
            token = str(body.get("token", "")).strip()
            uid = str(body.get("user_id", "")).strip()
            enable = body.get("enabled")
            if token:
                env_updates["TELEGRAM_BOT_TOKEN"] = token
            if uid.isdigit():
                config_updates["telegram.allowed_user_ids"] = uid
            if enable is not None or token:
                config_updates["telegram.enabled"] = None  # marker
                toml_bool = True if (enable is True or token) else False
                self._write_bool("telegram.enabled", toml_bool)
                config_updates.pop("telegram.enabled", None)
                results.append(f"telegram {'enabled' if toml_bool else 'disabled'}")

        elif kind == "calendar":
            url = str(body.get("url", "")).strip()
            if url:
                config_updates["calendar.ics_url"] = url

        elif kind == "misc":
            ww = body.get("wake_word")
            if ww is not None:
                self._write_bool("wake_word.enabled", bool(ww))
                results.append(f"wake word {'on' if ww else 'off'}")
            bt = str(body.get("briefing_time", "")).strip()
            if bt:
                config_updates["briefing.time"] = bt

        else:
            return {"ok": False, "error": f"unknown setup kind {kind!r}"}

        if env_updates:
            upsert_env_file(Path("~/.config/desk-secretary/env").expanduser(),
                            env_updates)
        real = {k: v for k, v in config_updates.items() if v is not None}
        if real:
            set_config_values(None, real)

        for dotted, val in {**real}.items():
            if dotted.startswith(("llm.tiers.", "stt.engine", "tts.")):
                continue
        # hot-apply stt/tts engine changes like apply_brain does
        for dotted in ("stt.engine", "tts.engine", "tts.voice"):
            if dotted in {k.rsplit(".", 1)[0] + "." + k.rsplit(".", 1)[1] for k in ()}:
                pass
        applied_note = ", ".join(results) if results else ""
        try:
            if any(k.startswith("tts.") for k in config_updates) or \
               any(k.startswith("stt.") for k in config_updates):
                pass
        except Exception:
            pass
        summary = "; ".join([f"{k}={v}" for k, v in real.items()] +
                            [f"env:{k}" for k in env_updates] + results)
        log.info("setup save [%s]: %s", kind, summary)
        return {"ok": True, "saved": summary, "note": applied_note}

    def _write_bool(self, dotted: str, value: bool):
        from .setup import _write_bools as wb

        wb(Path("~/.config/desk-secretary/config.toml").expanduser(),
           {dotted: value})

    def start(self):
        if not self.cfg.enabled:
            log.info("dashboard disabled")
            return
        self._http = ThreadingHTTPServer((self.cfg.host, int(self.cfg.port)),
                                         self._make_handler())
        self._thread = threading.Thread(target=self._http.serve_forever,
                                        name="xarvii-dashboard", daemon=True)
        self._thread.start()
        log.info("dashboard on http://%s:%d%s",
                 self.cfg.host, self.cfg.port,
                 " (token required)" if self.cfg.token else "")

    def stop(self):
        if self._http:
            self._http.shutdown()
            self._http.server_close()

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


def _parse_when(s: str):
    from .scheduler.reminders import parse_when
    from datetime import datetime

    dt = parse_when(s, datetime.now())
    if dt is None:
        raise SystemExit(f"cannot parse time: {s!r} (try 'in 30m', 'at 17:30', ISO)")
    return dt.isoformat(timespec="seconds")


async def _request(port: int, payload: dict, timeout: float = 10) -> dict:
    import websockets

    uri = f"ws://127.0.0.1:{port}"
    async with websockets.connect(uri, open_timeout=5) as ws:
        await ws.send(json.dumps(payload))
        while True:
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if resp.get("id") == payload.get("id"):
                return resp


def _probe_options() -> dict:
    import asyncio
    import os

    opts = {"ollama": [], "anthropic": [], "openai": [], "groq": [], "echo": ["echo/test"],
            "local-whisper": [], "faster-whisper": [], "whisper-cloud": []}
    try:
        async def tags():
            import httpx

            async with httpx.AsyncClient(timeout=4) as client:
                r = await client.get("http://127.0.0.1:11434/api/tags")
                return [m["name"] for m in r.json().get("models", [])]
        opts["ollama"] = asyncio.run(tags())
    except Exception:
        pass
    for prov, env in (("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"),
                      ("groq", "GROQ_API_KEY")):
        if os.environ.get(env):
            known = {"anthropic": ["claude-haiku-4-5", "claude-sonnet-5"],
                     "openai": ["gpt-5-mini", "gpt-5"],
                     "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]}
            opts[prov] = known.get(prov, [])
    try:
        import faster_whisper  # noqa: F401

        opts["faster-whisper"] = ["base", "small", "medium"]
    except ImportError:
        pass
    if os.environ.get("GROQ_API_KEY"):
        opts["whisper-cloud"] = ["whisper-large-v3-turbo"]
    return {k: v for k, v in opts.items() if v}


def cmd_brains(port: int) -> int:
    resp = asyncio.run(_request(port, {"id": 10, "cmd": "brain_status"}))
    print("current:")
    for tier, val in sorted(resp.get("tiers", {}).items()):
        print(f"  llm.{tier:<9} = {val}")
    print(f"  stt.engine   = {resp.get('stt_engine')}")
    print(f"  tts.engine   = {resp.get('tts_engine')}")
    if resp.get("demo"):
        print("  (demo overrides active)")
    print("\navailable now:")
    for group, items in sorted(_probe_options().items()):
        print(f"  {group}: {', '.join(items)}")
    return 0


def cmd_brain_set(port: int, key: str, value: str) -> int:
    resp = asyncio.run(_request(port, {"id": 11, "cmd": "brain_set", "key": key, "value": value}))
    if resp.get("ok"):
        print(f"applied {key} = {value}" + (f" (rebuilt: {','.join(resp['rebuilt'])})" if resp.get('rebuilt') else ""))
        return 0
    print(f"error: {resp.get('error')}", file=sys.stderr)
    return 1


def cmd_brain_wizard(port: int) -> int:
    status = asyncio.run(_request(port, {"id": 12, "cmd": "brain_status"}))
    opts = _probe_options()
    pool = []
    for prov in ("ollama", "anthropic", "openai", "groq", "echo"):
        for model in opts.get(prov, []):
            pool.append(f"{prov}/{model}")
    pool = list(dict.fromkeys(pool + [f"{status['tiers'][t]}" for t in ("fast", "reasoning", "vision")]))
    print("Choose LLM brains:")
    tiers = ["fast", "reasoning", "vision"]
    chosen = {}
    for tier in tiers:
        cur = status["tiers"].get(tier)
        print(f"\n[{tier}] current: {cur}")
        for i, opt in enumerate(pool, 1):
            mark = "*" if opt == cur else " "
            print(f"  {i:>2}{mark} {opt}")
        pick = input(f"number for {tier} [Enter=keep]: ").strip()
        if pick.isdigit() and 1 <= int(pick) <= len(pool):
            chosen[f"llm.tiers.{tier}"] = pool[int(pick) - 1]
    stts = ["faster-whisper", "echo"] + (["whisper-cloud"] if opts.get("whisper-cloud") else [])
    print(f"\n[stt] current: {status['stt_engine']}")
    for i, sname in enumerate(stts, 1):
        print(f"  {i:>2}  {sname}")
    pick = input("number for stt [Enter=keep]: ").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(stts):
        chosen["stt.engine"] = stts[int(pick) - 1]
    ttss = ["piper", "none"]
    print(f"\n[tts] current: {status['tts_engine']}")
    for i, tname in enumerate(ttss, 1):
        print(f"  {i:>2}  {tname}")
    pick = input("number for tts [Enter=keep]: ").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(ttss):
        chosen["tts.engine"] = ttss[int(pick) - 1]
    if not chosen:
        print("nothing changed")
        return 0
    rc = 0
    for k, v in chosen.items():
        rc |= cmd_brain_set(port, k, v)
    return rc


DEVICE_TOKENS = ("device", "talk")


def _installed_piper() -> list[str]:
    from pathlib import Path

    d = Path("~/.local/share/piper/voices").expanduser()
    return sorted(x.stem for x in d.glob("*.onnx"))


async def cmd_enroll(seconds: int = 20) -> int:
    """Record from laptop mic and enroll owner voice embedding."""
    import numpy as np
    import sounddevice as sd

    print(f"Speak naturally for {seconds}s…")
    frames = []
    loop = asyncio.get_running_loop()

    def cb(indata, frames_, t_, status):
        frames.append(bytes(indata))

    stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=800, callback=cb)
    with stream:
        end = loop.time() + seconds
        while loop.time() < end:
            await asyncio.sleep(0.2)
    pcm = b"".join(frames)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from deskd.skills.speaker_id import SpeakerID

    sid = SpeakerID(threshold=0.72)
    emb = sid.embed_pcm16k(pcm)
    if emb is None:
        print("enrollment failed — too little audio?", file=sys.stderr)
        return 1
    sid.save_centroid(emb)
    print(f"owner voice enrolled ({seconds}s). Speaker ID active.")
    return 0


def _cfg():
    from .config import load_config

    return load_config()


def cmd_voices(port: int) -> int:
    resp = asyncio.run(_request(port, {"id": 20, "cmd": "brain_status"}))
    print(f"current: engine={resp.get('tts_engine')} voice={resp.get('tts_voice', '?')}")
    print("\ninstalled (piper):")
    for n in _installed_piper():
        print(f"  {n}")
    print("\npiper downloadable:")
    from .tts.catalog import PIPER_CURATED

    for n in PIPER_CURATED:
        mark = "(installed)" if n in _installed_piper() else ""
        print(f"  {n} {mark}")
    print("\nedge neural (sample; 'edge/<name>'):")
    try:
        from .tts.catalog import edge_voices

        allv = edge_voices()
        for v in [x for x in allv if x.startswith(("en-IN", "hi-IN", "en-US-A", "en-GB-S"))][:10]:
            print(f"  edge/{v}")
        print(f"  … +{len(allv) - 10} more (edge-tts list-voices)")
    except Exception as e:
        print(f"  probe failed: {e}")
    print("\nopenai voices:", ", ".join(
        "openai/" + v for v in ("alloy", "echo", "fable", "onyx", "nova", "shimmer")))
    return 0


def cmd_voice_install(name: str) -> int:
    from .tts.catalog import download_piper_voice

    path = download_piper_voice(name, "~/.local/share/piper/voices")
    print(f"installed: {path}")
    print(f'enable with: xarvii voice set piper/{name}')
    return 0


def cmd_voice_preview(engine: str, voice: str = "", text: str = "") -> int:
    import asyncio
    import sys

    import numpy as np
    import sounddevice as sd

    async def synth():
        from .config import load_config
        from .tts.piper_tts import PiperSpeaker
        from .tts.edge_tts import EdgeSpeaker
        from .tts.openai_tts import OpenAiSpeaker

        cfg = load_config()
        if engine == "piper":
            name = voice or "en_US-lessac-medium"
            model = f"~/.local/share/piper/voices/{name}.onnx"
            spk = PiperSpeaker(model)
        elif engine == "edge":
            spk = EdgeSpeaker(voice or "en-IN-NeerjaNeural")
        elif engine == "openai":
            spk = OpenAiSpeaker(voice=voice or "alloy",
                                api_key_env=cfg.tts.openai_api_key_env)
        else:
            raise SystemExit(f"unknown engine {engine!r}")
        return await asyncio.wait_for(spk.synthesize(text), 45)

    pcm = asyncio.run(synth())
    if not pcm:
        print("synthesis produced nothing", file=sys.stderr)
        return 1
    sd.play(np.frombuffer(pcm, dtype=np.int16), samplerate=16000)
    sd.wait()
    print(f"played {len(pcm)/32000:.1f}s via {engine}/{voice}")
    return 0


def main(argv=None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] in DEVICE_TOKENS:
        from . import satellite

        sys.argv = [sys.argv[0] + " device"] + args_list[1:]
        return satellite.main() or 0
    if not args_list or args_list[0] in ("ui", "help"):
        from .ui import run_ui

        run_ui()
        return 0
    if args_list and args_list[0] in ("caps", "skills"):
        args_list = ["capabilities"] + args_list[1:]

    ap = argparse.ArgumentParser(
        prog="xarvii",
        description="Desk secretary control. Bare 'xarvii' opens the control center; 'xarvii device' starts the voice satellite.")
    ap.add_argument("--port", type=int, default=8766, help="daemon control port")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status")
    p = sub.add_parser("remind")
    p.add_argument("title")
    p.add_argument("when", help="e.g. 'in 30m', 'at 17:30', 'tomorrow 9am', ISO datetime")
    p = sub.add_parser("reminders")
    p = sub.add_parser("rm")
    p.add_argument("id")
    p = sub.add_parser("ask")
    p.add_argument("text")
    sub.add_parser("brains", help="show current + available brains")
    p = sub.add_parser("brain")
    p.add_argument("tier", help="fast | reasoning | vision")
    p.add_argument("provider_model", help='e.g. ollama/qwen3:4b, anthropic/claude-haiku-4-5')
    sub.add_parser("wizard", help="interactive brain picker")
    sub.add_parser("reset", help="restore known-good default brains")
    sub.add_parser("voices", help="list installed + available voices")
    sub.add_parser("ui", help="interactive control center")
    sub.add_parser("setup", help="guided credentials & integrations wizard")
    sub.add_parser("capabilities", help="everything xarvii can do")
    sub.add_parser("doctor", help="diagnostic health sweep")
    pd = sub.add_parser("doctor-play", help="doctor + speaker tone test")
    sub.add_parser("update", help="pull latest code, sync deps, restart")
    p = sub.add_parser("skill")
    sksub = p.add_subparsers(dest="skcmd", required=True)
    ski = sksub.add_parser("install")
    ski.add_argument("source", help="marketplace name or direct .py URL/path")
    skl = sksub.add_parser("list")
    skr = sksub.add_parser("remove")
    skr.add_argument("name")
    p = sub.add_parser("rule")
    rsub = p.add_subparsers(dest="rcmd", required=True)
    ra = rsub.add_parser("add")
    ra.add_argument("type", choices=["github_stars", "rss_keyword", "json_num"])
    ra.add_argument("message", help="spoken alert text")
    ra.add_argument("--repo", default="")
    ra.add_argument("--url", default="")
    ra.add_argument("--keyword", default="")
    ra.add_argument("--path", default="", help="dotted json path for json_num")
    ra.add_argument("--op", default=">=", choices=[">", ">=", "<", "<=", "=="])
    ra.add_argument("--value", type=float, default=0)
    rl = rsub.add_parser("list")
    rr = rsub.add_parser("remove")
    rr.add_argument("id_prefix")
    sub.add_parser("enroll", help="enroll owner voice for speaker ID")
    sub.add_parser("rag-rebuild", help="force Obsidian memory index rebuild")
    sub.add_parser("help", help="same as ui")
    p = sub.add_parser("voice")
    vsub = p.add_subparsers(dest="vcmd", required=True)
    vi = vsub.add_parser("install")
    vi.add_argument("name", help="piper voice name, e.g. en_US-ryan-high")
    vs = vsub.add_parser("set")
    vs.add_argument("engine_voice", help='engine/voice, e.g. edge/en-IN-NeerjaNeural or piper/en_US-lessac-medium')
    vp = vsub.add_parser("preview")
    vp.add_argument("engine_voice")
    vp.add_argument("--text", default="Hey! I am your desk secretary. How do I sound now?")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            resp = asyncio.run(_request(args.port, {"id": 1, "cmd": "status"}))
            for d in resp.get("devices", []):
                print(f"device {d['device']}: state={d['state']} muted={d['muted']}")
            if not resp.get("devices"):
                print("no devices connected")
            print(f"pending reminders: {resp.get('reminders_pending')}")
            print(f"demo mode: {resp.get('demo')}")
        elif args.cmd == "remind":
            due = _parse_when(args.when)
            resp = asyncio.run(_request(args.port, {"id": 2, "cmd": "add_reminder",
                                                    "title": args.title, "due": due}))
            if resp.get("ok"):
                r = resp["reminder"]
                print(f"scheduled [{r['id']}] {r['title']} @ {r['due']}")
            else:
                print(f"error: {resp.get('error')}", file=sys.stderr)
                return 1
        elif args.cmd == "reminders":
            resp = asyncio.run(_request(args.port, {"id": 3, "cmd": "reminders_list"}))
            items = resp.get("items", [])
            if not items:
                print("no pending reminders")
            for i in items:
                print(f"[{i['id']}] {i['due']}  {i['title']}")
        elif args.cmd == "rm":
            resp = asyncio.run(_request(args.port, {"id": 4, "cmd": "reminder_remove", "id": args.id}))
            print("removed" if resp.get("ok") else "not found")
        elif args.cmd == "brains":
            return cmd_brains(args.port)
        elif args.cmd == "brain":
            key = f"llm.tiers.{args.tier}"
            resp = asyncio.run(_request(args.port, {"id": 13, "cmd": "brain_set",
                                                    "key": key,
                                                    "value": args.provider_model}))
            if resp.get("ok"):
                print(f"{args.tier} -> {args.provider_model}")
                return 0
            print(f"error: {resp.get('error')}", file=sys.stderr)
            return 1
        elif args.cmd == "voice":
            if args.vcmd == "install":
                return cmd_voice_install(args.name)
            if args.vcmd == "set":
                engine, _, voice = args.engine_voice.partition("/")
                rc = 0
                rc |= cmd_brain_set(args.port, "tts.engine", engine)
                key = "tts.openai_voice" if engine == "openai" else "tts.voice"
                rc |= cmd_brain_set(args.port, key, voice or "alloy")
                print(f"voice -> {args.engine_voice} (live sessions swapped)")
                return rc
            if args.vcmd == "preview":
                return cmd_voice_preview(*args.engine_voice.split("/", 1),
                                         text=args.text)
        elif args.cmd == "capabilities":
            from .capabilities import run_capabilities

            return run_capabilities()
        elif args.cmd in ("doctor", "doctor-play"):
            from .doctor import run_doctor

            return run_doctor(play_audio=(args.cmd == "doctor-play"))
        elif args.cmd == "skill":
            from pathlib import Path as _P

            from .skills.marketplace import installed, install as sk_install, remove as sk_remove

            plug_dir = os.path.expanduser(
                getattr(_cfg().plugins, "dir",
                        "~/desk-secretary/skills-plugins"))
            if args.skcmd == "install":
                try:
                    out = sk_install(args.source, str(plug_dir))
                    print(f"installed: {out}")
                    print("restart deskd to activate (systemctl --user restart deskd-dev)")
                    return 0
                except Exception as e:
                    print(f"error: {e}", file=sys.stderr)
                    return 1
            if args.skcmd == "list":
                for n in installed(str(plug_dir)):
                    print(n)
                remote = None
                try:
                    from .skills.marketplace import fetch_index
                    remote = {x['name'] for x in fetch_index()} - set(installed(str(plug_dir)))
                except Exception:
                    pass
                if remote:
                    print("\navailable in marketplace:")
                    for n in sorted(remote):
                        print(" ", n)
                return 0
            if args.skcmd == "remove":
                print("removed" if sk_remove(args.name, str(plug_dir)) else "not found")
                return 0
        elif args.cmd == "update":
            from .updater import run_update

            return run_update()
        elif args.cmd == "setup":
            from .setup import run_setup

            return run_setup(getattr(args, "config_path", None))
        elif args.cmd == "rule":
            if args.rcmd == "list":
                resp = asyncio.run(_request(args.port, {"id": 40, "cmd": "rule_list"}))
                items = resp.get("items") or []
                if not items:
                    print("no rules")
                for r in items:
                    print(f"[{r['id']}] {r['type']} {r['params']} armed={r['armed']}"
                          + (f" last={r['last_value']}" if r.get("last_value") else ""))
                return 0
            if args.rcmd == "remove":
                resp = asyncio.run(_request(args.port,
                                            {"id": 41, "cmd": "rule_remove",
                                             "id_prefix": args.id_prefix}))
                print("removed" if resp.get("ok") else "not found")
                return 0
            params = {}
            if args.type == "github_stars":
                params.update(repo=args.repo, op=args.op, value=args.value)
                if not args.repo:
                    print("--repo required", file=sys.stderr); return 1
            elif args.type == "rss_keyword":
                params.update(url=args.url, keyword=args.keyword.lower())
                if not (args.url and args.keyword):
                    print("--url and --keyword required", file=sys.stderr); return 1
            else:
                params.update(url=args.url, path=args.path, op=args.op,
                              value=args.value)
                if not (args.url and args.path):
                    print("--url and --path required", file=sys.stderr); return 1
            resp = asyncio.run(_request(args.port, {
                "id": 42, "cmd": "rule_add", "type": args.type,
                "params": params, "message": args.message}))
            print("added:", resp.get("id") or resp)
            return 0
        elif args.cmd == "enroll":
            return asyncio.run(cmd_enroll())
        elif args.cmd == "rag-rebuild":
            resp = asyncio.run(_request(args.port, {"id": 43, "cmd": "rag_rebuild"},
                                        timeout=120))
            print(resp.get("chunks", resp))
            return 0
        elif args.cmd == "reset":
            defaults = {
                "llm.tiers.fast": "gemini/gemini-3.6-flash",
                "llm.tiers.reasoning": "gemini/gemini-3.6-flash",
                "llm.tiers.vision": "gemini/gemini-3.6-flash",
                "stt.engine": "faster-whisper",
                "tts.engine": "piper",
            }
            rc = 0
            for k, v in defaults.items():
                rc |= cmd_brain_set(args.port, k, v)
            print("defaults restored")
            return rc
        elif args.cmd == "wizard":
            return cmd_brain_wizard(args.port)
        elif args.cmd == "ask":
            resp = asyncio.run(_request(args.port, {"id": 5, "cmd": "ask", "text": args.text}, timeout=60))
            print("sent to device" if resp.get("delivered_to_device") else "no device connected; nothing sent")
    except (ConnectionRefusedError, OSError, TimeoutError):
        print("cannot reach daemon on port %d — is deskd running?" % args.port, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

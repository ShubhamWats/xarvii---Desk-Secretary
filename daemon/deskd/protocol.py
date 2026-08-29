import json
from typing import Union

PROTO_VERSION = 1
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
CHANNELS = 1
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * FRAME_MS // 1000


def encode(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def decode(raw: str) -> dict:
    msg = json.loads(raw)
    if not isinstance(msg, dict):
        raise ValueError("control message must be a JSON object")
    return msg


Frame = Union[dict, bytes]


def hello(device: str, fw: str, proto: int = PROTO_VERSION) -> dict:
    return {"type": "hello", "device": device, "fw": fw, "proto": proto}


def welcome(server: str, proto: int = PROTO_VERSION) -> dict:
    return {"type": "welcome", "proto": proto, "server": server}


def state(to: str) -> dict:
    return {"type": "state", "to": to}


def ptt(event: str) -> dict:
    return {"type": "ptt", "event": event}


def abort(reason: str) -> dict:
    return {"type": "abort", "reason": reason}


def tts_start(tid: int, text: str | None = None) -> dict:
    msg = {"type": "tts_start", "id": tid}
    if text:
        msg["text"] = text
    return msg


def transcript(text: str) -> dict:
    return {"type": "transcript", "text": text}


def tts_stop(tid: int) -> dict:
    return {"type": "tts_stop", "id": tid}


def chime(name: str) -> dict:
    return {"type": "chime", "name": name}


def reminder_msg(rid: str, title: str, due: str) -> dict:
    return {"type": "reminder", "id": rid, "title": title, "due": due}


def error(code: str, message: str = "") -> dict:
    return {"type": "error", "code": code, "message": message}

import asyncio
import logging

from .base import Connection

log = logging.getLogger("deskd.serial")

ESP32_USB_CDC_IDS = {"303a", "303A"}


def find_esp32_port() -> str | None:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if p.vid is not None and f"{p.vid:04x}" in {v.lower() for v in ESP32_USB_CDC_IDS}:
            return p.device
    return None


class SerialControlConnection(Connection):
    """NDJSON control over USB CDC. Audio frames are not carried in v1."""

    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._warned = False

    async def send_json(self, msg: dict) -> None:
        import json as _json

        self._writer.write(_json.dumps(msg, separators=(",", ":")).encode() + b"\n")
        await self._writer.drain()

    async def send_audio(self, data: bytes) -> None:
        if not self._warned:
            log.info("audio over serial not supported; dropping %d bytes", len(data))
            self._warned = True

    async def recv(self):
        try:
            line = await self._reader.readline()
        except Exception:
            return None
        if not line:
            return None
        import json as _json

        try:
            obj = _json.loads(line)
        except json.JSONDecodeError:
            return {}
        return obj if isinstance(obj, dict) else {}

    async def close(self) -> None:
        self._writer.close()


async def open_serial_connection(path: str, baudrate: int) -> SerialControlConnection | None:
    try:
        import serial_asyncio_fast  # noqa: F401

        mod = serial_asyncio_fast
    except ImportError:
        try:
            import serial_asyncio as mod  # type: ignore
        except ImportError:
            log.warning("pyserial-asyncio not installed; serial transport disabled")
            return None
    reader, writer = await mod.open_serial_connection(url=path, baudrate=baudrate)
    return SerialControlConnection(reader, writer)

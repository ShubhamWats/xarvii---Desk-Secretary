import json
import logging

from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed

from ..protocol import FRAME_BYTES
from .base import Connection

log = logging.getLogger("deskd.ws")


class WsConnection(Connection):
    MAX_AUDIO_FRAME = 8192

    def __init__(self, ws: ServerConnection):
        self._ws = ws

    async def send_json(self, msg: dict) -> None:
        await self._ws.send(json.dumps(msg, separators=(",", ":")))

    async def send_audio(self, data: bytes) -> None:
        for off in range(0, len(data), FRAME_BYTES * 10):
            await self._ws.send(data[off : off + FRAME_BYTES * 10])

    async def recv(self):
        try:
            msg = await self._ws.recv()
        except ConnectionClosed:
            return None
        if isinstance(msg, str):
            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                log.warning("dropping malformed text frame")
                return {}
            return obj if isinstance(obj, dict) else {}
        return msg

    async def close(self) -> None:
        await self._ws.close()


class DeviceWsServer:
    def __init__(self, host: str, port: int, on_client):
        self.host = host
        self.port = port
        self.on_client = on_client
        self._server = None

    async def start(self):
        self._server = await ws_serve(self._handler, self.host, self.port, max_size=1 << 20)
        log.info("device WS listening on %s:%d", self.host, self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws):
        await self.on_client(WsConnection(ws))

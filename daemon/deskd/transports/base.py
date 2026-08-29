from typing import AsyncIterator, Protocol, Union

Frame = Union[dict, bytes]


class Connection(Protocol):
    async def send_json(self, msg: dict) -> None: ...

    async def send_audio(self, data: bytes) -> None: ...

    async def recv(self) -> Frame | None:
        """Return next dict control message, bytes audio frame, or None on EOF."""
        ...

    async def close(self) -> None: ...

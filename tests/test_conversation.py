import asyncio
import contextlib
from dataclasses import dataclass, field

import pytest

from deskd.config import Cfg
from deskd.conversation import Conversation


@dataclass
class FakeDev:
    states: list = field(default_factory=list)
    sent_json: list = field(default_factory=list)
    sent_audio: bytes = b""
    closed: bool = False

    async def set_state(self, to):
        self.states.append(to)

    async def send_json(self, msg):
        self.sent_json.append(msg)

    async def send_audio(self, data):
        self.sent_audio += data

    async def chime(self, name):
        await self.send_json({"type": "chime", "name": name})

    async def offer_followup(self, seconds):
        await self.set_state("idle")

    @contextlib.asynccontextmanager
    async def speech_slot(self):
        yield

    @property
    def conn(self):
        return self

    def dispatch(self):
        return None


class FakeStt:
    async def transcribe(self, pcm, language="en"):
        return "tell me something interesting"


class FakeProvider:
    def __init__(self, deltas):
        self.deltas = deltas

    async def stream(self, messages, images=None):
        for d in self.deltas:
            yield d
            await asyncio.sleep(0)


def make_conv(deltas):
    cfg = Cfg()
    cfg.llm.max_history_turns = 4
    conv = Conversation(
        cfg,
        FakeStt(),
        llm_router=FakeRouter(FakeProvider(deltas)),
        speaker_factory=lambda: NullSpeaker(),
        context_builder=lambda: "ctx",
    )
    return conv


class FakeRouter:
    def __init__(self, provider):
        self.provider = provider

    def tier_for(self, has_images=False, approx_tokens=0):
        return "fast"

    def resolve(self, s):
        return self.provider


class NullSpeaker:
    def __init__(self):
        self.spoken = []
        self.aborted = False

    async def say(self, text, conn):
        self.spoken.append(text)
        await asyncio.sleep(0)

    def abort(self):
        self.aborted = True


async def run_turn(conv, dev):
    await conv.on_ptt_down(dev)
    conv.feed_audio(b"\x00\x40" * 4000)
    await conv.on_ptt_up(dev)
    assert conv._turn_task is not None
    await conv._turn_task


@pytest.mark.asyncio
async def test_full_turn_states_and_reply():
    conv = make_conv(["Hello there friend. ", "Second sentence here."])
    dev = FakeDev()
    await run_turn(conv, dev)
    assert dev.states == ["listening", "thinking", "speaking", "idle"]
    assert len(conv.speaker.spoken) == 2
    assert conv.history[-1]["role"] == "assistant"
    assert "Hello there" in conv.history[-1]["content"]


@pytest.mark.asyncio
async def test_barge_in_aborts_and_notifies_device():
    conv = make_conv(["A sentence that keeps going. " * 5])
    dev = FakeDev()
    await conv.on_ptt_down(dev)

    slow_provider = FakeRouter(None)

    class SlowProvider:
        async def stream(self, messages, images=None):
            for i in range(50):
                yield f"chunk {i} of a very long reply. "
                await asyncio.sleep(0.01)

    conv.router.resolve = lambda s: SlowProvider()
    conv._turn_task = asyncio.create_task(conv._respond("start", dev))
    await asyncio.sleep(0.05)
    assert dev.states[-1] in ("thinking", "speaking")

    await conv.on_ptt_down(dev)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(conv._turn_task, 1)
    aborts = [m for m in dev.sent_json if m["type"] == "abort"]
    assert aborts and aborts[0]["reason"] == "barge-in"
    assert conv.speaker.aborted


@pytest.mark.asyncio
async def test_short_utterance_ignored():
    conv = make_conv(["ignored"])
    dev = FakeDev()
    await conv.on_ptt_down(dev)
    conv.feed_audio(b"\x00\x00" * 100)
    await conv.on_ptt_up(dev)
    assert dev.states == ["listening", "idle"]

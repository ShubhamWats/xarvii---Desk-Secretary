import json

import pytest

from deskd.config import AgentCfg
from deskd.conversation import Conversation, _needs_agent
from deskd.tools.registry import ToolRegistry


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.responses.pop(0)


class Stub:
    def __init__(self, registry):
        self.tools = registry
        self.cfg = type("C", (), {"agent": AgentCfg(enabled=True, max_rounds=4)})()


@pytest.mark.asyncio
async def test_multi_round_chain():
    reg = ToolRegistry()
    stored = {}

    async def fake_add(title, when_str):
        stored["t"], stored["w"] = title, when_str
        return {"id": "r1", "title": title}

    reg.register("reminder_add", "", {}, fake_add)
    reg.register("web_search", "", {},
                 lambda query: [{"title": "Ronaldo plays Friday", "snippet": ""}])

    provider = FakeProvider([
        {"content": None, "tool_calls": [
            {"function": {"name": "web_search",
                          "arguments": {"query": "when does ronaldo next play"}}}]},
        {"content": None, "tool_calls": [
            {"function": {"name": "reminder_add",
                          "arguments": {"title": "Ronaldo match",
                                        "when_str": "friday 21:00"}}}]},
        {"content": "Reminder scheduled for Friday."},
    ])

    messages = [{"role": "user",
                 "content": "remind me when ronaldo next plays"}]
    await Conversation._maybe_tool_round(Stub(reg), provider,
                                         "remind me when ronaldo next plays",
                                         messages)

    assert stored["t"] == "Ronaldo match"
    assert len(provider.calls) == 3
    assert sum(1 for m in messages if m["role"] == "tool") == 2


def test_max_rounds_respected():
    reg = ToolRegistry()
    reg.register("echo_tool", "", {}, lambda: {})
    provider = FakeProvider([
        {"content": None, "tool_calls": [
            {"function": {"name": "echo_tool", "arguments": {}}}]}] * 10)
    messages = [{"role": "user", "content": "loop forever"}]
    asyncio_run(Conversation._maybe_tool_round(
        Stub(reg), provider, "loop forever", messages))
    assert len(provider.calls) <= 4 + 1


def asyncio_run(coro):
    import asyncio
    return asyncio.run(_wrap(coro))


async def _wrap(coro):
    try:
        await coro
    except Exception as e:
        raise e


def test_gate_matches_lookup_phrases():
    assert _needs_agent("remind me when ronaldo next plays")
    assert _needs_agent("what is the price of bitcoin")
    assert not _needs_agent("tell me a joke")
    assert not _needs_agent("what time is it")

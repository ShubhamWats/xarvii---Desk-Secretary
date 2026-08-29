import asyncio
import json
import logging
import os
from typing import AsyncIterator, Optional

import httpx

log = logging.getLogger("deskd.llm")


class LlmError(RuntimeError):
    pass


def _sse_lines(chunk: str):
    for line in chunk.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            yield line[5:].strip()


class Provider:
    name = "base"

    async def stream(self, messages: list[dict], images: Optional[list[bytes]] = None) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover


class EchoProvider(Provider):
    name = "echo"

    def __init__(self, model: str = "test"):
        self.model = model

    async def stream(self, messages, images=None):
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        demo = (
            "Echo mode is active. The full voice loop works end to end. "
            "You said the following. "
        )
        text = demo + (user if isinstance(user, str) else "")
        for word in text.split(" "):
            yield word + " "
            await asyncio.sleep(0)


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, keep_alive: str = "30m",
                 think: bool | None = False, num_predict: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        self.think = think
        self.num_predict = num_predict

    async def stream(self, messages, images=None):
        payload_msgs = []
        for m in messages:
            entry = {"role": m["role"], "content": m["content"]}
            payload_msgs.append(entry)
        if images:
            payload_msgs[-1]["images"] = [self._b64(img) for img in images]
        payload = {
            "model": self.model,
            "messages": payload_msgs,
            "stream": True,
            "keep_alive": self.keep_alive,
            "num_predict": self.num_predict,
        }
        if self.think is not None:
            payload["think"] = self.think
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    delta = obj.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if obj.get("done"):
                        break

    @staticmethod
    def _b64(data: bytes) -> str:
        import base64

        return base64.b64encode(data).decode()

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Non-streaming call; returns the raw assistant message dict.

        The message may contain 'content' and/or 'tool_calls'.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "num_predict": self.num_predict,
        }
        if self.think is not None:
            payload["think"] = self.think
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            return json.loads(r.text).get("message", {})


class OpenAiCompatProvider(Provider):
    name = "openai"

    def __init__(self, base_url: str, api_key_env: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.model = model

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if not self.api_key:
            raise LlmError(f"missing API key ({self.name})")
        payload_msgs = list(messages)
        payload = {"model": self.model, "messages": payload_msgs, "stream": False}
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"], "description": t["description"],
                              "parameters": t["parameters"]}}
                for t in tools
            ]
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=payload,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            choice = r.json().get("choices", [{}])[0].get("message", {})
            out = {"content": choice.get("content") or ""}
            calls = []
            for tc in choice.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                calls.append({"function": {"name": fn.get("name"),
                                           "arguments": fn.get("arguments")}})
            if calls:
                out["tool_calls"] = calls
            return out

    async def stream(self, messages, images=None):
        if not self.api_key:
            raise LlmError(f"missing API key ({self.name})")
        last_user_idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
        payload_msgs = []
        for i, m in enumerate(messages):
            if m["role"] == "user" and images and i == last_user_idx:
                blocks = [{"type": "text", "text": m["content"]}]
                for img in images:
                    blocks.append(
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(img)}}
                    )
                payload_msgs.append({"role": "user", "content": blocks})
            else:
                payload_msgs.append({"role": m["role"], "content": m["content"]})
        payload = {"model": self.model, "messages": payload_msgs, "stream": True}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     json=payload, headers=headers) as r:
                r.raise_for_status()
                buf = ""
                async for raw in r.aiter_text():
                    buf += raw
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        for data in _sse_data(line):
                            if data == "[DONE]":
                                return
                            obj = json.loads(data)
                            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                            if delta:
                                yield delta


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, base_url: str, api_key_env: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.model = model

    async def stream(self, messages, images=None):
        if not self.api_key:
            raise LlmError(f"missing API key ({self.name})")
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        convo = []
        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "assistant":
                convo.append({"role": "assistant", "content": m["content"]})
            else:
                blocks = []
                for img in images or []:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": _b64(img)},
                        }
                    )
                blocks.append({"type": "text", "text": m["content"]})
                convo.append({"role": "user", "content": blocks})
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "stream": True,
            "system": "\n".join(system_parts),
            "messages": convo,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.base_url}/v1/messages",
                                     json=payload, headers=headers) as r:
                r.raise_for_status()
                buf = ""
                async for raw in r.aiter_text():
                    buf += raw
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        for data in _sse_data(line):
                            try:
                                obj = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if obj.get("type") == "content_block_delta":
                                delta = obj.get("delta", {}).get("text", "")
                                if delta:
                                    yield delta
                            elif obj.get("type") == "message_stop":
                                return


class Router:
    def __init__(self, cfg):
        self.cfg = cfg

    def tier_for(self, has_images: bool, approx_tokens: int = 0) -> str:
        if has_images:
            return "vision"
        if approx_tokens > 1500:
            return "reasoning"
        return "fast"

    def resolve(self, provider_str: str) -> Provider:
        scheme, _, model = provider_str.partition("/")
        if scheme == "echo":
            return EchoProvider(model)
        pconf = dict(self.cfg.llm.providers.get(scheme, {}))
        base_url = pconf.get("base_url", "")
        key_env = pconf.get("api_key_env", "")
        if not model:
            raise LlmError(f"provider string needs a model: {provider_str!r}")
        if scheme == "ollama":
            return OllamaProvider(base_url or "http://127.0.0.1:11434", model,
                                  keep_alive=pconf.get("keep_alive", "30m"),
                                  think=pconf.get("think", False),
                                  num_predict=int(pconf.get("num_predict", 300)))
        if scheme in ("openai", "groq", "openai-compat"):
            return OpenAiCompatProvider(base_url, key_env or "OPENAI_API_KEY", model)
        if scheme == "gemini":
            return OpenAiCompatProvider(
                base_url or "https://generativelanguage.googleapis.com/v1beta/openai",
                key_env or "GEMINI_API_KEY", model)
        if scheme == "anthropic":
            return AnthropicProvider(base_url or "https://api.anthropic.com",
                                     key_env or "ANTHROPIC_API_KEY", model)
        raise LlmError(f"unknown provider {scheme!r}")


def _sse_data(line: str):
    line = line.strip()
    if line.startswith("data:"):
        yield line[5:].strip()


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


async def gather_stream(aiter) -> str:
    parts = []
    async for d in aiter:
        parts.append(d)
    return "".join(parts)

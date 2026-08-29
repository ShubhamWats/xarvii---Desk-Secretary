"""Home Assistant control via REST (long-lived token), with graceful
fallback to a generic webhook when HA isn't configured."""

import logging
import os

import httpx

log = logging.getLogger("deskd.ha")


class HomeAssistant:
    def __init__(self, enabled: bool, url: str, token_env: str,
                 webhook_url: str = ""):
        self.enabled = enabled
        self.url = url.rstrip("/") if url else ""
        self.token = os.environ.get(token_env, "") if enabled else ""
        self.webhook_url = webhook_url

    @property
    def mode(self) -> str | None:
        if self.enabled and self.url and self.token:
            return "ha"
        if self.webhook_url:
            return "webhook"
        return None

    async def call_service(self, domain: str, service: str,
                           entity_id: str, data: dict | None = None) -> dict | None:
        payload = {"entity_id": entity_id, **(data or {})}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{self.url}/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {self.token}"},
                json=payload)
            r.raise_for_status()
            return r.json() if r.text else []

    async def fire_webhook(self, hook_id: str, payload: dict):
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{self.webhook_url}/api/webhook/{hook_id}", json=payload)

    # ------------------------------------------------------------- high level

    async def switch(self, entity: str, on: bool) -> bool:
        if self.mode != "ha":
            return False
        await self.call_service("homeassistant",
                                "turn_on" if on else "turn_off", entity)
        return True

    async def scene(self, scene_entity: str) -> bool:
        if self.mode != "ha":
            return False
        await self.call_service("scene", "turn_on", scene_entity)
        return True

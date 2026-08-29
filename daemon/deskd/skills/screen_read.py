"""Screen-read with EXPLICIT spoken consent before every capture (privacy-first).

The consent state machine lives in Conversation; this module only does the
capture + vision call AFTER consent is granted.
"""

import base64
import logging

from ..integrations import screencap

log = logging.getLogger("deskd.screenread")


async def capture_and_describe(router, context_builder, question: str) -> str | None:
    """Returns spoken description or None. Consent is handled by the caller."""
    try:
        png = await screencap.capture_screen()
    except Exception as e:
        log.warning("capture failed: %s", e)
        return None
    tier = router.tier_for(has_images=True)
    provider_str = router.cfg.llm.tiers.get(tier, "")
    provider = router.resolve(provider_str)
    system = context_builder() + (
        "\nYou are describing the user's screen for a voice assistant."
        " Be concise, spoken-word friendly, no markdown.")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question or "What's on my screen? Summarize briefly."},
    ]
    parts = []
    try:
        async for delta in provider.stream(messages, images=[png]):
            parts.append(delta)
    except Exception as e:
        log.warning("vision brain failed (%s); trying local fallback", e)
        fb = router.resolve("ollama/llama3.2:3b")
        text_only = messages[-1]["content"]
        async for delta in fb.stream(
                [{"role": "system", "content": system},
                 {"role": "user", "content":
                  f"I couldn't process the screenshot ({e}). "
                  f"Here's what I know: {text_only}"}]):
            parts.append(delta)
    return "".join(parts).strip()

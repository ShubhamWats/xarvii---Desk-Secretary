"""Voice catalogs: curated Piper voices, live edge probe, OpenAI list."""

import urllib.request

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

PIPER_CURATED = {
    "en_US-lessac-medium": "en/en_US/lessac/medium",
    "en_US-ryan-high": "en/en_US/ryan/high",
    "en_US-amy-medium": "en/en_US/amy/medium",
    "en_US-kathleen-low": "en/en_US/kathleen/low",
    "en_US-hfc_female-medium": "en/en_US/hfc_female/medium",
    "en_GB-alba-medium": "en/en_GB/alba/medium",
    "en_GB-northern_english_male-medium": "en/en_GB/northern_english_male/medium",
    "hi_IN-pratham-medium": "hi/hi_IN/pratham/medium",
}

EDGE_POPULAR = [
    "en-IN-NeerjaNeural",
    "en-IN-PrabhatNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "hi-IN-SwaraNeural",
    "hi-IN-MadhurNeural",
]

OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def piper_urls(relpath: str) -> tuple[str, str]:
    return (f"{HF_BASE}/{relpath}/{relpath.split('/')[-1]}.onnx",
            f"{HF_BASE}/{relpath}/{relpath.split('/')[-1]}.onnx.json")


def download_piper_voice(name: str, dest_dir: str) -> str:
    """Download onnx+json for a curated voice; returns local model path."""
    import os
    from pathlib import Path

    rel = PIPER_CURATED.get(name, name)
    if "/" not in rel:
        raise ValueError(f"unknown piper voice {name!r}; see 'xarvii voices'")
    onnx_url, json_url = piper_urls(rel)
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    model = dest / f"{name}.onnx"
    for url, out in ((onnx_url, model), (json_url, dest / f"{name}.onnx.json")):
        if out.exists() and out.stat().st_size > 0:
            continue
        urllib.request.urlretrieve(url, out)
    return str(os.path.expanduser(model))


def edge_voices() -> list[str]:
    """Live catalog (~400 voices) via edge-tts; falls back to popular list."""
    try:
        import asyncio

        import edge_tts

        async def _list():
            voices = await edge_tts.list_voices()
            return sorted(v["ShortName"] for v in voices)

        return asyncio.run(asyncio.wait_for(_list(), 15))
    except Exception:
        return list(EDGE_POPULAR)

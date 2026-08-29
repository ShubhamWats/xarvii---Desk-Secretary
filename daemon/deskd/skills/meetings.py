"""Meeting mode: record room audio → transcribe → action items → Obsidian."""

import asyncio
import logging
import wave
from datetime import datetime
from pathlib import Path

log = logging.getLogger("deskd.meetings")


class MeetingRecorder:
    """Taps satellite mic frames while active; writes 16k mono wav on stop."""

    def __init__(self, out_dir: str):
        self.out_dir = Path(out_dir).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.active = False
        self._buf = bytearray()
        self.started_at = None

    def feed(self, chunk: bytes) -> bool:
        if not self.active:
            return False
        self._buf.extend(chunk)
        return True

    def start(self) -> str:
        self.active = True
        self._buf.clear()
        self.started_at = datetime.now()
        return self.started_at.strftime("%Y-%m-%d_%H%M")

    def stop(self) -> Path | None:
        if not self.active:
            return None
        self.active = False
        if len(self._buf) < 32000:
            return None
        path = self.out_dir / f"meeting_{self.started_at.strftime('%Y-%m-%d_%H%M')}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(bytes(self._buf))
        log.info("meeting saved: %s (%.1fs)", path, len(self._buf) / 32000)
        return path


async def transcribe_and_extract(pcm_path: Path, stt, router,
                                 vault, meetings_dir: Path):
    """Transcribe the meeting wav, then extract summary + action items."""
    text = await stt.transcribe(pcm_path)
    text = text.strip()
    if not text:
        return "The recording came back empty — nothing to process."

    tier = router.tier_for(has_images=False, approx_tokens=len(text) // 4)
    provider = router.resolve(router.cfg.llm.tiers[tier])
    system = (
        "You summarize meetings for spoken playback. Produce:\n"
        "1. A two-sentence summary.\n"
        "2. 'Action items:' then each item on its own line starting with '- '.")
    parts = []
    async for delta in provider.stream(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Meeting transcript:\n{text}"}]):
        parts.append(delta)
    answer = "".join(parts).strip()

    # write transcript + notes into the vault
    try:
        meetings_dir = Path(meetings_dir).expanduser()
        meetings_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H%M")
        note = meetings_dir / f"meeting_{stamp}.md"
        action_lines = [l.strip() for l in answer.splitlines()
                        if l.strip().startswith("-")]
        body = [f"# Meeting {stamp}", "", "## Transcript", "", text[:8000], "",
                "## Summary & actions", "", answer]
        if action_lines and vault is not None:
            for a in action_lines:
                vault.append_inbox(a.lstrip("- "), as_task=True)
            body += ["", "Action items copied to Inbox."]
        note.write_text("\n".join(body))
        answer += f" Notes saved to {note.name}."
    except Exception:
        log.exception("failed writing meeting note")
    return answer

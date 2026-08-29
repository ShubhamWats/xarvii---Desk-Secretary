import logging
import re
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("deskd.obsidian")

_TASK_RE = re.compile(r"^\s*[-*]\s+\[( |x|/)\]\s+(.*)$", re.MULTILINE)
_STAMP_RE = re.compile(r"`\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]`")
_DUE_RE = re.compile(r"\b(?:due|by)[:\s]*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


class ObsidianVault:
    def __init__(self, vault_path: Path):
        self.vault = Path(vault_path).expanduser().resolve()
        if not self.vault.is_dir():
            raise FileNotFoundError(f"vault not found: {self.vault}")

    def _safe(self, relpath: str) -> Path:
        p = (self.vault / relpath).resolve()
        if not str(p).startswith(str(self.vault)):
            raise ValueError("path escapes vault")
        return p

    def list_notes(self) -> list[Path]:
        return sorted(
            p for p in self.vault.rglob("*.md")
            if ".obsidian" not in p.parts and ".trash" not in p.parts
        )

    def read_note(self, relpath: str) -> str:
        return self._safe(relpath).read_text(errors="replace")

    def search(self, query: str, limit: int = 5) -> list[dict]:
        q_terms = [t.lower() for t in query.split() if len(t) > 2]
        if not q_terms:
            return []
        scored: list[tuple[float, dict]] = []
        for note in self.list_notes():
            try:
                text = note.read_text(errors="replace")
            except OSError:
                continue
            title = note.stem.lower()
            lower = text.lower()
            score = 0.0
            for t in q_terms:
                if t in title:
                    score += 5.0
                score += lower.count(t) * 0.5
            if score > 0:
                snippet_idx = min((lower.find(t) for t in q_terms if lower.find(t) >= 0), default=0)
                start = max(0, snippet_idx - 60)
                scored.append((
                    score,
                    {
                        "file": str(note.relative_to(self.vault)),
                        "title": note.stem,
                        "score": round(score, 1),
                        "snippet": text[start : start + 200].replace("\n", " ").strip(),
                        "mtime": note.stat().st_mtime,
                    },
                ))
        scored.sort(key=lambda x: (-x[0], -x[1]["mtime"]))
        return [item for _, item in scored[:limit]]

    def tasks(self, limit: int = 50) -> list[dict]:
        out: list[dict] = []
        cutoff = time.time() - 90 * 86400
        for note in self.list_notes():
            try:
                if note.stat().st_mtime < cutoff:
                    continue
                text = note.read_text(errors="replace")
            except OSError:
                continue
            for m in _TASK_RE.finditer(text):
                done = m.group(1) == "x"
                body = m.group(2).strip()
                due_m = _DUE_RE.search(body)
                out.append({
                    "done": done,
                    "text": body,
                    "due": due_m.group(1) if due_m else None,
                    "file": str(note.relative_to(self.vault)),
                })
                if len(out) >= limit * 3:
                    break
        pending = [t for t in out if not t["done"]]
        pending.sort(key=lambda t: (t["due"] or "9999", t["text"]))
        return pending[:limit]

    def digest(self, limit: int = 5) -> list[dict]:
        notes = sorted(self.list_notes(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        out = []
        for note in notes:
            text = note.read_text(errors="replace")
            first_line = ""
            for line in text.splitlines():
                s = line.strip().lstrip("#").strip()
                if s:
                    first_line = s[:140]
                    break
            out.append({
                "file": str(note.relative_to(self.vault)),
                "summary": first_line,
                "mtime": int(note.stat().st_mtime),
            })
        return out

    def append_inbox(self, text: str, as_task: bool = True) -> str:
        target = self._safe(self.inbox_note_name())
        stamp = datetime_stamp()
        line = f"- [ ] {text}  `[{stamp}]`\n" if as_task else f"{text}  `[{stamp}]`\n"
        existing = target.read_text(errors="replace") if target.exists() else ""
        marker = "\n## Inbox\n\n"
        if marker in existing:
            head, _, tail = existing.partition(marker)
            new = head + marker + line + tail
        elif existing.strip():
            new = existing.rstrip("\n") + "\n\n## Inbox\n\n" + line
        else:
            new = marker.lstrip("\n") + line
        target.write_text(new)
        return str(target.relative_to(self.vault))

    def sweep_expired_inbox(self, max_age_days: int = 7) -> int:
        """Drop inbox task lines older than max_age_days (by their stamp or due date).

        Returns number of lines removed.
        """
        target = self._safe(self.inbox_note_name())
        if not target.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        kept, removed = [], 0
        for line in target.read_text(errors="replace").splitlines():
            drop = False
            m = _STAMP_RE.search(line)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").timestamp()
                    if ts < cutoff:
                        drop = True
                except ValueError:
                    pass
            if not drop:
                dm = _DUE_RE.search(line)
                if dm:
                    try:
                        if datetime.strptime(dm.group(1), "%Y-%m-%d").timestamp() < cutoff:
                            drop = True
                    except ValueError:
                        pass
            if drop:
                removed += 1
            else:
                kept.append(line)
        if removed:
            target.write_text("\n".join(kept).rstrip("\n") + "\n")
            log.info("swept %d expired inbox tasks", removed)
        return removed

    def inbox_note_name(self) -> str:
        return getattr(self, "_inbox_note", "Inbox.md")

    def set_inbox_note(self, name: str) -> None:
        self._inbox_note = name


def datetime_stamp() -> str:
    import datetime as dt

    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def make_vault(cfg) -> "ObsidianVault | None":
    vault = cfg.resolved_vault()
    if not vault:
        return None
    try:
        v = ObsidianVault(vault)
        v.set_inbox_note(cfg.obsidian.inbox_note)
        return v
    except FileNotFoundError as e:
        log.warning("%s", e)
        return None

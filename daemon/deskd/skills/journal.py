"""Evening journaling companion + expense ledger helpers (vault-backed)."""

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("deskd.journal")

QUESTIONS = [
    "What was the best part of your day?",
    "What drained you or got in the way?",
    "One thing you want to do better tomorrow?",
]


class JournalSession:
    """Multi-question FSM driven through the normal follow-up window."""

    def __init__(self, vault, out_dir: str, owner_name: str = ""):
        self.vault = vault
        self.out_dir = Path(out_dir).expanduser()
        self.owner_name = owner_name
        self.answers: list[tuple[str, str]] = []
        self.step = 0

    @property
    def done(self) -> bool:
        return self.step >= len(QUESTIONS)

    def next_prompt(self) -> str:
        q = QUESTIONS[self.step]
        return f"Journal time. Question {self.step + 1} of {len(QUESTIONS)}. {q}"

    def answer(self, text: str):
        q = QUESTIONS[self.step]
        self.answers.append((q, text.strip()))
        self.step += 1

    def write(self) -> str | None:
        if not self.answers or self.vault is None:
            return None
        try:
            out_dir = self.out_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{datetime.now():%Y-%m-%d}.md"
            lines = [f"# Journal — {datetime.now():%A, %B %d %Y}", ""]
            for i, (q, a) in enumerate(self.answers, 1):
                lines += [f"## {i}. {q}", "", a, ""]
            path.write_text("\n".join(lines))
            log.info("journal written: %s", path)
            return str(path.name)
        except Exception:
            log.exception("journal write failed")
            return None


# ------------------------------------------------------------------ expenses

def append_expense(vault, ledger_note: str, amount: float, what: str) -> str:
    ledger = vault._safe(ledger_note)
    now = datetime.now()
    month_hdr = now.strftime("%B %Y")
    line = f"- {now.strftime('%Y-%m-%d')} — ₹{amount:g} — {what}"
    existing = ledger.read_text(errors="replace") if ledger.exists() else ""
    if month_hdr.lower() in existing.lower():
        new = existing.rstrip("\n") + "\n" + line + "\n"
    else:
        new = (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + \
              f"# {month_hdr}\n\n" + line + "\n"
    ledger.write_text(new)
    return line


def month_total(ledger_note_path: Path) -> tuple[float, int]:
    total, count = 0.0, 0
    month = datetime.now().strftime("%B %Y")
    in_month = False
    p = Path(ledger_note_path)
    if not p.exists():
        return 0.0, 0
    import re

    for line in p.read_text(errors="replace").splitlines():
        if line.startswith("# ") and month.lower() in line.lower():
            in_month = True
        elif line.startswith("# "):
            in_month = False
            continue
        m = re.search(r"₹(\d+(?:\.\d+)?)", line)
        if in_month and m and "- [" not in line[:4]:
            total += float(m.group(1))
            count += 1
    return total, count

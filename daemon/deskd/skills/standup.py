"""Standup generator: merges git commits + Obsidian tasks into a spoken update."""

import asyncio
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def collect_git_commits(repos: list[str], since_hours: int = 24) -> list[str]:
    since = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M")
    commits = []
    for repo in repos:
        repo = str(Path(repo).expanduser())
        if not Path(repo, ".git").exists():
            continue
        try:
            out = subprocess.run(
                ["git", "-C", repo, "log", "--since", since,
                 "--pretty=%s"], capture_output=True, timeout=10,
                text=True)
            for line in out.stdout.splitlines():
                line = line.strip()
                if line:
                    commits.append(line)
        except Exception:
            continue
    return commits


def build_prompt(commits: list[str], done_tasks: list[str], pending_tasks: list[str],
                 owner_name: str = "") -> list[dict]:
    who = owner_name or "the user"
    system = (
        "You write a crisp spoken standup update. Structure: "
        "'Yesterday I ... Today I will ... Blockers: none/...'. "
        "Plain sentences only, no markdown, max 6 sentences.")
    lines = [f"Commits by {who} in the last 24h:"]
    lines += [f"- {c}" for c in commits[:15]] or ["- none"]
    lines.append("Completed tasks from notes:")
    lines += [f"- {t}" for t in done_tasks[:10]] or ["- none recorded"]
    lines.append("Pending tasks:")
    lines += [f"- {t['text'] if isinstance(t, dict) else t}" for t in pending_tasks[:10]] \
        or ["- none"]
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines)}]


async def generate(router, vault, repos: list[str], owner_name: str = "") -> str | None:
    commits = await asyncio.to_thread(collect_git_commits, repos, 24)
    done, pending = [], []
    if vault is not None:
        try:
            all_tasks = await asyncio.to_thread(vault.tasks, 40)
            done = [t["text"].strip("*x ").strip() for t in all_tasks if t.get("done")]
            pending = [t for t in all_tasks if not t.get("done")]
        except Exception:
            pass
    messages = build_prompt(commits, done, pending, owner_name)
    tier = router.tier_for(has_images=False,
                           approx_tokens=len(json_len(messages)) // 4)
    provider = router.resolve(router.cfg.llm.tiers[tier])
    parts = []
    async for delta in provider.stream(messages):
        parts.append(delta)
    return "".join(parts).strip()


def json_len(messages) -> int:
    return sum(len(m.get("content", "")) for m in messages)

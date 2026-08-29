import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value):
    if isinstance(value, str):

        def sub(m):
            return os.environ.get(m.group(1), "")

        return _ENV_RE.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class ServerCfg:
    ws_host: str = "0.0.0.0"
    ws_port: int = 8765
    ctl_host: str = "127.0.0.1"
    ctl_port: int = 8766
    serial_enabled: bool = False
    serial_path: str = ""
    serial_baud: int = 115200


@dataclass
class SttCfg:
    engine: str = "echo"
    model: str = "small"
    live_partial: bool = True
    language: str = "en"
    compute_type: str = "int8"
    base_url: str = "https://api.groq.com/openai/v1"
    api_key_env: str = "GROQ_API_KEY"
    api_model: str = "whisper-large-v3-turbo"


@dataclass
class LlmCfg:
    tiers: dict = field(
        default_factory=lambda: {
            "fast": "ollama/qwen3:4b",
            "reasoning": "ollama/qwen3:8b",
            "vision": "anthropic/claude-haiku-4-5",
        }
    )
    providers: dict = field(
        default_factory=lambda: {
            "ollama": {"base_url": "http://127.0.0.1:11434"},
            "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
            "anthropic": {"base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
            "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
        }
    )
    max_history_turns: int = 10


@dataclass
class TtsCfg:
    engine: str = "none"
    voice: str = ""
    length_scale: float = 1.0
    sentence_min_len: int = 12
    openai_voice: str = "alloy"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key_env: str = "OPENAI_API_KEY"


@dataclass
class ObsidianCfg:
    vault: str = ""
    inbox_note: str = "Inbox.md"


@dataclass
class WebSearchCfg:
    provider: str = "none"
    max_results: int = 5


@dataclass
class RemindersCfg:
    state_file: str = "~/.local/state/desk-secretary/reminders.json"


@dataclass
class OwnerCfg:
    name: str = ""
    location: str = "Mumbai"
    latitude: float = 0.0
    longitude: float = 0.0


@dataclass
class BriefingCfg:
    enabled: bool = True
    time: str = "08:00"


@dataclass
class WakeWordCfg:
    enabled: bool = False
    model: str = "hey_jarvis"
    threshold: float = 0.5
    cooldown_s: float = 2.0


@dataclass
class CalendarCfg:
    ics_url: str = ""


@dataclass
class GmailCfg:
    host: str = "imap.gmail.com"
    user: str = ""
    password_env: str = "GMAIL_APP_PASSWORD"
    max_unread: int = 5


@dataclass
class TelegramCfg:
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_user_ids: str = ""


@dataclass
class FollowupCfg:
    seconds: int = 10


@dataclass
class AgentCfg:
    enabled: bool = True
    max_rounds: int = 4


@dataclass
class VadCfg:
    threshold: float = 250.0
    min_duration_s: float = 0.35
    pad_ms: int = 120


@dataclass
class ClipboardCfg:
    enabled: bool = True


@dataclass
class HomeAssistantCfg:
    enabled: bool = False
    url: str = ""                 # e.g. http://homeassistant.local:8123
    token_env: str = "HA_TOKEN"


@dataclass
class WebhookCfg:
    url: str = ""                 # generic fallback when HA absent


@dataclass
class MusicCfg:
    provider: str = "ytmusic"     # spotify | ytmusic
    mode: str = "basic"           # api | basic


@dataclass
class MeetingsCfg:
    dir: str = "~/Documents/Obsidian Vault/Meetings"


@dataclass
class ExpensesCfg:
    ledger_note: str = "Ledger.md"


@dataclass
class JournalCfg:
    enabled: bool = True
    time: str = "21:30"
    dir: str = "~/Documents/Obsidian Vault/Journal"


@dataclass
class RulesCfg:
    enabled: bool = True
    interval_minutes: int = 5


@dataclass
class RagCfg:
    enabled: bool = True
    model: str = "BAAI/bge-small-en-v1.5"
    rebuild_minutes: int = 60
    top_k: int = 4


@dataclass
class SpeakerIdCfg:
    enabled: bool = False
    threshold: float = 0.72


@dataclass
class DashboardCfg:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8767
    token: str = ""


@dataclass
class PluginsCfg:
    dir: str = "~/desk-secretary/skills-plugins"


@dataclass
class PersonaCfg:
    quirks: bool = True


@dataclass
class TtsCfgLang:
    pass


@dataclass
class Cfg:
    server: ServerCfg = field(default_factory=ServerCfg)
    stt: SttCfg = field(default_factory=SttCfg)
    llm: LlmCfg = field(default_factory=LlmCfg)
    tts: TtsCfg = field(default_factory=TtsCfg)
    obsidian: ObsidianCfg = field(default_factory=ObsidianCfg)
    websearch: WebSearchCfg = field(default_factory=WebSearchCfg)
    reminders: RemindersCfg = field(default_factory=RemindersCfg)
    owner: OwnerCfg = field(default_factory=OwnerCfg)
    briefing: BriefingCfg = field(default_factory=BriefingCfg)
    wake_word: WakeWordCfg = field(default_factory=WakeWordCfg)
    calendar: CalendarCfg = field(default_factory=CalendarCfg)
    gmail: GmailCfg = field(default_factory=GmailCfg)
    telegram: TelegramCfg = field(default_factory=TelegramCfg)
    followup: FollowupCfg = field(default_factory=FollowupCfg)
    agent: AgentCfg = field(default_factory=AgentCfg)
    vad: VadCfg = field(default_factory=VadCfg)
    clipboard: ClipboardCfg = field(default_factory=ClipboardCfg)
    rules: RulesCfg = field(default_factory=RulesCfg)
    rag: RagCfg = field(default_factory=RagCfg)
    speaker_id: SpeakerIdCfg = field(default_factory=SpeakerIdCfg)
    dashboard: DashboardCfg = field(default_factory=DashboardCfg)
    plugins: PluginsCfg = field(default_factory=PluginsCfg)
    homeassistant: HomeAssistantCfg = field(default_factory=HomeAssistantCfg)
    webhook: WebhookCfg = field(default_factory=WebhookCfg)
    music: MusicCfg = field(default_factory=MusicCfg)
    meetings: MeetingsCfg = field(default_factory=MeetingsCfg)
    expenses: ExpensesCfg = field(default_factory=ExpensesCfg)
    journal: JournalCfg = field(default_factory=JournalCfg)
    persona: PersonaCfg = field(default_factory=PersonaCfg)
    demo: bool = False

    def resolved_reminders_path(self) -> Path:
        return Path(os.path.expanduser(self.reminders.state_file))

    def resolved_vault(self) -> Optional[Path]:
        p = self.obsidian.vault.strip()
        return Path(os.path.expanduser(p)) if p else None


DEFAULT_CONFIG_PATHS = [
    Path("~/.config/desk-secretary/config.toml").expanduser(),
    Path("config.local.toml"),
]


def load_config(path: Optional[str] = None) -> Cfg:
    cfg = Cfg()
    candidates = [Path(path)] if path else DEFAULT_CONFIG_PATHS
    for cand in candidates:
        if cand.is_file():
            with open(cand, "rb") as f:
                data = tomllib.load(f)
            merged = _merge(cfg, _expand(data))
            return merged
    return cfg


def apply_demo_overrides(cfg: Cfg) -> Cfg:
    cfg.stt.engine = "echo"
    cfg.tts.engine = "none"
    cfg.llm.tiers = {k: "echo/test" for k in cfg.llm.tiers}
    cfg.demo = True
    return cfg


def upsert_env_file(path: Path, updates: dict) -> Path:
    """Append/replace KEY=value lines; preserves everything else; chmod 600."""
    path = Path(os.path.expanduser(str(path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    for key, value in updates.items():
        formatted = f"{key}={value}"
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(key + "=") or line.strip() == key:
                lines[i] = formatted
                replaced = True
                break
        if not replaced:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(formatted)
    target = path
    target.write_text("\n".join(lines).rstrip("\n") + "\n")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


BRAIN_KEYS = {
    "llm.tiers.fast": str,
    "llm.tiers.reasoning": str,
    "llm.tiers.vision": str,
    "stt.engine": str,
    "tts.engine": str,
    "tts.voice": str,
    "tts.openai_voice": str,
    "wake_word.enabled": "bool",
}


def set_config_values(path: Optional[str], updates: dict) -> Path:
    """Persist dotted updates (e.g. 'llm.tiers.fast') into the TOML file.

    Edits existing keys line-wise; appends the section if missing. Creates a
    minimal config file when none exists.
    """
    target = Path(path) if path else DEFAULT_CONFIG_PATHS[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = target.read_text().splitlines() if target.exists() else []

    for dotted, value in updates.items():
        section, key = dotted.rsplit(".", 1)
        header = f"[{section}]"
        formatted = f'{key} = "{value}"'
        sec_idx = None
        for i, line in enumerate(lines):
            if line.strip() == header:
                sec_idx = i
                break
        if sec_idx is None:
            if lines:
                lines.append("")
            lines.append(header)
            lines.append(formatted)
            continue
        end = len(lines)
        for j in range(sec_idx + 1, len(lines)):
            if lines[j].strip().startswith("["):
                end = j
                break
        replaced = False
        for j in range(sec_idx + 1, end):
            stripped = lines[j].strip()
            if stripped.startswith(key + " ") or stripped.startswith(key + "=") or stripped == key:
                lines[j] = formatted
                replaced = True
                break
        if not replaced:
            insert = sec_idx + 1
            while insert < end and lines[insert].strip() == "":
                insert += 1
            lines.insert(insert, formatted)

    clean = [ln for ln in lines]
    out = []
    prev_blank = False
    for ln in clean:
        blank = ln.strip() == ""
        if blank and prev_blank:
            continue
        out.append(ln)
        prev_blank = blank
    target.write_text("\n".join(out).rstrip("\n") + "\n")
    return target


_SECTION_MAP = {
    "server": ServerCfg,
    "stt": SttCfg,
    "llm": LlmCfg,
    "tts": TtsCfg,
    "obsidian": ObsidianCfg,
    "websearch": WebSearchCfg,
    "reminders": RemindersCfg,
    "owner": OwnerCfg,
    "briefing": BriefingCfg,
    "wake_word": WakeWordCfg,
    "calendar": CalendarCfg,
    "gmail": GmailCfg,
    "telegram": TelegramCfg,
    "followup": FollowupCfg,
    "vad": VadCfg,
    "agent": AgentCfg,
    "clipboard": ClipboardCfg,
    "rules": RulesCfg,
    "rag": RagCfg,
    "dashboard": DashboardCfg,
    "plugins": PluginsCfg,
    "speaker_id": SpeakerIdCfg,
    "homeassistant": HomeAssistantCfg,
    "webhook": WebhookCfg,
    "music": MusicCfg,
    "meetings": MeetingsCfg,
    "expenses": ExpensesCfg,
    "journal": JournalCfg,
    "persona": PersonaCfg,
}


def _merge(cfg: Cfg, data: dict) -> Cfg:
    for section, cls in _SECTION_MAP.items():
        if section in data and isinstance(data[section], dict):
            current = getattr(cfg, section)
            for key, val in data[section].items():
                if hasattr(current, key):
                    setattr(current, key, val)
    if "demo" in data:
        cfg.demo = bool(data["demo"])
    return cfg

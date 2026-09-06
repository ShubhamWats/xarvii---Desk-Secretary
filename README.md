# ◈ xarvii - your desk secretary

> A voice-first desk companion: speak naturally, get things done.
> Runs its **brain on your laptop** (Gemini, local Ollama, or any provider) and
> speaks through cheap hardware - laptop mic/speakers today, an ESP32-S3
> satellite tomorrow. Private by default, pluggable by design.

```
 ┌──────────────────────┐   WebSocket + USB    ┌───────────────────────────┐
 │  satellite           │   NDJSON control     │  xarvii daemon            │
 │  mic · speaker · PTT │◄────────────────────►│                           │
 │  mute · LED · RTC    │   PCM 16k audio      │  whisper → brain → voice  │
 └──────────────────────┘                      │  skills · rules · memory  │
   ESP32-S3 / Pi / laptop                      └───────────────────────────┘
```

## ✨ Highlights

-  **Natural conversation** - push-to-talk now, wake-word later; follow-up
  window means you just keep talking after every answer
-  **Your choice of brain** - Gemini flash (free tier), local Ollama,
  OpenAI/Anthropic/Groq… per-tier routing with automatic cloud→local fallback
-  **Private options everywhere** - local Whisper STT, local Piper TTS,
  local embeddings for note-memory; screen-read asks permission *out loud*
-  Real secretary skills - reminders with messy human time formats
  ("at 12.38 am"), kitchen timers that re-chime, dictated to-do lists filed
  into Obsidian (auto-expiring after a week)
-  **Remembers your notes** - RAG over your whole Obsidian vault, answers cite files
-  **Watches the internet for you** - GitHub stars, RSS keywords, JSON price APIs → spoken alerts
-  LAN dashboard at `http://localhost:8767` - brains/voices/reminders/timers from any browser
-  **Telegram twin** - text your secretary from anywhere
-  Drop-in plugin system - one Python file = new skill

## Skills (all voice-driven)

reminders & alarms · timers · morning briefing · weather · Obsidian
read/search/tasks/inbox/journal · web search · screen-read (with consent) ·
media & volume & brightness · open apps · expenses ledger *(soon)* · meeting
notes *(soon)* · standup generator · speaker-ID guest mode · MCP tool discovery

## Quick start

```bash
git clone <your-fork> && cd desk-secretary
bash install.sh          # venv + deps + voice + systemd + CLI on PATH

xarvii setup             # guided wizard (validates credentials live)
xarvii                   # control center UI
xarvii device            # voice satellite via laptop mic/speakers
```

Then: hold **ENTER** to talk, release to send, keep talking in the follow-up window.

No hardware? No problem - everything above runs on your laptop's mic + speakers.

## 🎛 Brains & voices

```bash
xarvii brains                        # see what's actually available
xarvii brain fast gemini/gemini-3.6-flash
xarvii voices                        # 300+ neural + piper catalog
xarvii voice set edge/en-IN-NeerjaNeural
```

Any tier accepts any provider string:
`ollama/qwen3:4b` · `gemini/gemini-3.6-flash` · `anthropic/claude-haiku-4-5`
· `openai/gpt-5-mini` · `groq/llama-3.3-70b-versatile` · `echo/test`.

Cloud fails? It falls back to local automatically.

## Plugins

Drop a file in `skills-plugins/`:

```python
# skills-plugins/crypto_price.py
def register(registry, ctx):
    registry.register("btc_price", "Current BTC price in USD", {},
                      lambda: {"usd": fetch_btc()})
```

Restart the daemon - the agent can now call it mid-conversation.

## 📡 Hardware roadmap (ESP32-S3)

The wire protocol is **frozen** (see [docs/protocol.md](docs/protocol.md)) and
any client must pass [scripts/conformance.py](scripts/conformance.py).
Firmware phase adds: I2S mic/speaker, FreeRTOS ring buffers, on-device wake
word (ESP-SR), acoustic-echo barge-in, LED status ring, offline reminder cache
with RTC, hardware mic kill-switch, deep-sleep battery profile.

Parts list (~$12): ESP32-S3 devkit · INMP441 mic · MAX98357A amp + speaker ·
PTT/mute buttons · WS2812 LED. Wiring guide lands with the firmware phase.

## Docs

| Doc | What's inside |
|---|---|
| [docs/protocol.md](docs/protocol.md) | frozen wire protocol v1 |
| [docs/satellite_contract.md](docs/satellite_contract.md) | what every client must do |
| [docs/setup.md](docs/setup.md) | engines, keys, systemd, testing |
| [config/config.example.toml](config/config.example.toml) | every knob explained |

## Status

| Phase | State |
|---|---|
| Core loop + skills + brains + dashboard | ✅ shipped |
| Speaker ID, RAG memory, rules engine | ✅ shipped |
| Packaging (installer/dashboard/plugins) | ✅ shipped |
| ESP32-S3 firmware (Tier-A features) | 🔜 next |

Built with faster-whisper, Piper, Ollama, Gemini, edge-tts,
openwakeword, resemblyzer, fastembed - standing on giants.

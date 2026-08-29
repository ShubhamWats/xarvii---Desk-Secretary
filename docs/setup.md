# Setup Guide

## 1. Daemon install

```bash
cd ~/desk-secretary
python3 -m venv .venv && source .venv/bin/activate
pip install -e './daemon[dev]'
```

Extras:

| extra | gives you |
|---|---|
| `audio` | live mic/speaker for `mock_esp32.py` (sounddevice, numpy-free path) |
| `stt-local` | faster-whisper local transcription |
| `serial` | USB CDC control transport (pyserial-asyncio) |

## 2. Choose engines (`~/.config/desk-secretary/config.toml`)

### STT

* local: `engine = "faster-whisper"` (first run downloads the model to cache)
* Groq: `engine = "groq"` + `export GROQ_API_KEY=...`
* OpenAI: `engine = "openai"`, set `base_url`/`api_model`

### LLM tiers

```toml
[llm.tiers]
fast = "ollama/qwen3:4b"          # short replies, chit-chat
reasoning = "ollama/qwen3:8b"     # multi-step / long context
vision = "anthropic/claude-haiku-4-5"
```

Any tier can be any provider string. Cloud keys come from the env vars listed
under `[llm.providers]`.

### TTS

```bash
pipx install piper-tts
mkdir -p ~/.local/share/piper/voices
# download a voice, e.g. en_US-lessac-medium.onnx (+ .onnx.json) from
# https://github.com/rhasspy/piper/blob/master/VOICES.md
```

then `engine = "piper"`, `voice = "~/.local/share/piper/voices/en_US-lessac-medium.onnx"`.

## 3. Obsidian

Set `[obsidian] vault = "~/Documents/Obsidian Vault"`. The daemon reads notes
read-only; only `inbox_append` writes, and only into your chosen inbox note.

## 4. Web search (optional)

`export TAVILY_API_KEY=...` or `BRAVE_SEARCH_API_KEY=...`, set provider in
config. No key → search tools simply return empty.

## 5. Run as a service

```ini
# ~/.config/systemd/user/deskd.service
[Unit]
Description=Desk secretary daemon
After=graphical-session.target

[Service]
ExecStart=%h/desk-secretary/.venv/bin/deskd
Restart=on-failure
Environment=GROQ_API_KEY=

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now deskd
journalctl --user -u deskd -f
```

## 6. Testing without hardware

```bash
deskd --demo &
printf 'hello there' > /tmp/t.wav   # or record a real one
xarvii --wave /tmp/t.wav
```

Demo mode needs zero models: STT returns a canned phrase, the LLM echoes, TTS
chimes instead of speaking — but every state transition, sentence pipeline,
barge-in abort and reminder push is exercised exactly like production.

## 7. Firmware (Phase 4)

See `firmware/README.md`. Wiring guide arrives with the INMP441/MAX98357A
bring-up.

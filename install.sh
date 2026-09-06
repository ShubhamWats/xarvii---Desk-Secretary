
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
VENV="$ROOT/.venv"

bold() { echo -e "\033[1m$*\033[0m"; }
ok()   { echo "  ✓ $*"; }
info() { echo -e "\033[36m→\033[0m $*"; }

bold "== xarvii installer =="

info "checking system packages…"
MISSING=()
for p in ffmpeg playerctl brightnessctl libportaudio2; do
  dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  info "installing: ${MISSING[*]}  (sudo prompt expected)"
  sudo apt-get update -qq && sudo apt-get install -y -qq "${MISSING[@]}" || \
    echo "  ⚠ some system packages failed — voice preview/media may need them"
else
  ok "system packages present"
fi


if [ ! -x "$VENV/bin/python" ]; then
  info "creating venv…"
  python3 -m venv "$VENV"
fi
info "installing python dependencies (this can take a few minutes)…"
"$VENV/bin/pip" -q install --upgrade pip setuptools"<81"
"$VENV/bin/pip" -q install -e './daemon[audio,stt-local,serial,dev]' edge-tts av rich fastembed feedparser resemblyzer
ok "python environment ready"


VOICE_DIR="$HOME/.local/share/piper/voices"
mkdir -p "$VOICE_DIR"
if [ ! -f "$VOICE_DIR/en_US-lessac-medium.onnx" ]; then
  info "downloading Piper voice en_US-lessac-medium (~60MB)…"
  curl -sL -o "$VOICE_DIR/en_US-lessac-medium.onnx" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
  curl -sL -o "$VOICE_DIR/en_US-lessac-medium.onnx.json" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
fi
ok "piper voices in $VOICE_DIR"


mkdir -p "$HOME/.local/bin"
for cmd in xarvii deskd; do
  printf '#!/bin/bash\nexec "%s/.venv/bin/%s" "$@"\n' "$ROOT" "$cmd" > "$HOME/.local/bin/$cmd"
  chmod +x "$HOME/.local/bin/$cmd"
done
ok "commands installed: xarvii deskd"


CFG_DIR="$HOME/.config/desk-secretary"
mkdir -p "$CFG_DIR"
touch "$CFG_DIR/env" && chmod 600 "$CFG_DIR/env"
[ -f "$CFG_DIR/config.toml" ] || cp config/config.example.toml "$CFG_DIR/config.toml"
ok "config at $CFG_DIR/config.toml"


UNIT_DIR="$HOME/.config/systemd/user/deskd-dev.service.d"
mkdir -p "$UNIT_DIR"
cat > "$HOME/.config/systemd/user/deskd-dev.service" <<EOF
[Unit]
Description=xarvii desk secretary daemon

[Service]
ExecStart=$VENV/bin/deskd
WorkingDirectory=$ROOT
EnvironmentFile=$CFG_DIR/env
Restart=on-failure
Environment=PATH=$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload 2>/dev/null || true
ok "service unit ready (deskd-dev)"

bold ""
read -r -p "Start the daemon now? [Y/n]: " ans
if [[ ! "${ans:-y}" =~ ^[Nn] ]]; then
  systemctl --user reset-failed deskd-dev 2>/dev/null || true
  systemd-run --user --unit=deskd-dev --setenv=PATH="$VENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    --working-directory="$ROOT" "$VENV/bin/deskd" >/dev/null 2>&1 || \
    systemctl --user start deskd-dev
  sleep 2 && systemctl --user is-active deskd-dev && ok "daemon running"
fi

cat <<EOF

$(bold "== setup complete ==")
next steps:
  xarvii setup        # guided credentials (gemini/gmail/telegram/calendar)
  xarvii              # open the control center UI
  xarvii device       # run the voice satellite on this laptop
  xarvii status       # quick health check

dashboard: http://localhost:8767   (once daemon runs)
logs:      journalctl --user -u deskd-dev -f
EOF

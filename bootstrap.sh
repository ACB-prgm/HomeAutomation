#!/bin/bash
set -e

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RUNTIME="$BASE_DIR/runtime"
VENV="$RUNTIME/venv"
BOOTSTRAP="$BASE_DIR/bootstrap"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_SRC="$BOOTSTRAP/macos_launchd_plist.xml"
PLIST_DEST="$LAUNCH_AGENTS/com.aaron.homeassistant.plist"

echo "=== Home Assistant Bootstrap ==="

# 1. Ensure Homebrew Python is installed
if ! command -v python3 >/dev/null 2>&1; then
    echo "[+] Installing Python3 via Homebrew..."
    brew install python@3
else
    echo "[+] Python3 already installed."
fi

# 2. Ensure runtime directory exists
if [ ! -d "$RUNTIME" ]; then
    echo "[+] Creating runtime directory..."
    mkdir -p "$RUNTIME"
fi

# 3. Create venv if missing
if [ ! -d "$VENV" ]; then
    echo "[+] Creating Python venv..."
    python3 -m venv "$VENV"
    source "$VENV/bin/activate"

    echo "[+] Upgrading pip + wheel + setuptools..."
    pip install --upgrade pip wheel setuptools

    echo "[+] Installing Home Assistant..."
    pip install homeassistant

    echo "[+] Freezing requirements.txt..."
    pip freeze > "$BASE_DIR/requirements.txt"
else
    echo "[+] Virtual environment already exists."
fi

# 4. Install launchd plist
if [ ! -f "$PLIST_DEST" ]; then
    echo "[+] Installing launchd plist..."
    mkdir -p "$LAUNCH_AGENTS"
    cp "$PLIST_SRC" "$PLIST_DEST"
    launchctl load "$PLIST_DEST"
else
    echo "[+] launchd plist already installed."
fi

echo "=== Bootstrap complete ==="
echo "You can now start Home Assistant using:"
echo "  $VENV/bin/hass"

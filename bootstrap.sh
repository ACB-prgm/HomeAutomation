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

# 1. Ensure Homebrew Python 3.12 is installed
if ! brew list python@3.12 >/dev/null 2>&1; then
    echo "[+] Installing Python 3.12 via Homebrew..."
    brew install python@3.12
else
    echo "[+] Homebrew Python 3.12 already installed."
fi

# 2. Ensure we are using the correct Python interpreter
PYTHON_BIN="/opt/homebrew/bin/python3.12"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.12 not found at $PYTHON_BIN."
    echo "Make sure Homebrew is installed and python@3.12 is installed correctly."
    exit 1
fi

# 2. Ensure runtime directory exists
if [ ! -d "$RUNTIME" ]; then
    echo "[+] Creating runtime directory..."
    mkdir -p "$RUNTIME"
fi

# 3. Create venv if missing
if [ ! -d "$VENV" ]; then
    echo "[+] Creating Python 3.12 venv..."
    "$PYTHON_BIN" -m venv "$VENV"

    # Activate venv
    source "$VENV/bin/activate"

    echo "[+] Upgrading pip + wheel + setuptools..."
    pip install --upgrade pip wheel setuptools

    echo "[+] Installing Home Assistant..."
    pip install homeassistant

    echo "[+] Installing project dependencies..."
    pip install -r "$BASE_DIR/requirements.txt"
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

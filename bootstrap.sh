#!/bin/bash
set -e

echo "=== Home Automation Bootstrap Start ==="

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$BASE_DIR/.venv"

##############################################
# 1. Ensure Python 3.13 exists
##############################################

if ! brew list python@3.13 >/dev/null 2>&1; then
    echo "[+] Installing python@3.13 ..."
    brew install python@3.13
else
    echo "[+] python@3.13 already installed."
fi

ARCH="$(uname -m)"
if [ "$ARCH" = "arm64" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.13"
else
    PYTHON_BIN="/usr/local/bin/python3.13"
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "[ERROR] python3.13 not found at $PYTHON_BIN"
    exit 1
fi

echo "[+] Using Python interpreter: $PYTHON_BIN"

##############################################
# 2. Create virtual environment
##############################################

if [ ! -d "$VENV" ]; then
    echo "[+] Creating venv at .venv ..."
    "$PYTHON_BIN" -m venv "$VENV"
else
    echo "[+] venv already exists at .venv"
fi

echo "[+] Activating venv..."
# shellcheck source=/dev/null
source "$VENV/bin/activate"

echo "[+] Upgrading pip/setuptools/wheel..."
pip install --upgrade pip setuptools wheel

##############################################
# 3. Install Python dependencies
##############################################

REQ="$BASE_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    echo "[+] Installing Python project dependencies..."
    pip install -r "$REQ"
else
    echo "[!] No requirements.txt found — skipping."
fi

##############################################
# 4. Launch Flask server
##############################################

echo "[+] Starting Flask server..."
python -m server.app &
SERVER_PID=$!

echo "[+] Server started with PID $SERVER_PID"
echo "=== Bootstrap complete ==="


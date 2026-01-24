#!/bin/bash
set -e

echo "=== Home Automation Bootstrap Start ==="

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$BASE_DIR/.venv"

##############################################
# Ensure Homebrew exists
##############################################

BREW_BIN="$(command -v brew || true)"
if [ -z "$BREW_BIN" ]; then
    if [ -x /opt/homebrew/bin/brew ]; then
        BREW_BIN="/opt/homebrew/bin/brew"
    elif [ -x /usr/local/bin/brew ]; then
        BREW_BIN="/usr/local/bin/brew"
    else
        echo "[+] Installing Homebrew ..."
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ -x /opt/homebrew/bin/brew ]; then
            BREW_BIN="/opt/homebrew/bin/brew"
        elif [ -x /usr/local/bin/brew ]; then
            BREW_BIN="/usr/local/bin/brew"
        else
            echo "[ERROR] Homebrew install failed or brew not found."
            exit 1
        fi
    fi
fi

eval "$("$BREW_BIN" shellenv)"

##############################################
# Ensure Python 3.13 exists
##############################################

if ! brew list python@3.13 >/dev/null 2>&1; then
    echo "[+] Installing python@3.13 ..."
    brew install python@3.13
else
    echo "[+] python@3.13 already installed."
fi

BREW_PY_PREFIX="$(brew --prefix python@3.13 2>/dev/null || true)"
if [ -z "$BREW_PY_PREFIX" ]; then
    BREW_PY_PREFIX="$(brew --prefix)"
fi
PYTHON_BIN="$BREW_PY_PREFIX/bin/python3.13"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3.13 || true)"
fi

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "[ERROR] python3.13 not found (checked $BREW_PY_PREFIX/bin and PATH)"
    exit 1
fi

echo "[+] Using Python interpreter: $PYTHON_BIN"

##############################################
# install git-lfs
##############################################

if ! brew list --formula git-lfs >/dev/null 2>&1; then
    echo "[+] Installing git-lfs (Hugging Face)..."
    brew install git-lfs
else
    echo "[+] git-lfs already installed."
fi

# Ensure git-lfs is initialized for this user
if ! git lfs env >/dev/null 2>&1; then
    echo "[+] Initializing git-lfs..."
    git lfs install
else
    echo "[+] git-lfs already initialized."
fi

##############################################
# Install Ollama
##############################################

if ! brew list --formula ollama >/dev/null 2>&1; then
    echo "[+] Installing ollama ..."
    brew install ollama
else
    echo "[+] ollama already installed."
fi

if brew services list | grep -q '^ollama'; then
    STATUS="$(brew services list | awk '$1 == "ollama" {print $2}')"
    if [ "$STATUS" != "started" ]; then
        echo "[+] Starting ollama service..."
        brew services start ollama
    else
        echo "[+] ollama service already running."
    fi
else
    echo "[+] Starting ollama service..."
    brew services start ollama
fi

##############################################
# Create virtual environment
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
# Install Python dependencies
##############################################

REQ="$BASE_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    echo "[+] Installing Python project dependencies..."
    pip install -r "$REQ"
else
    echo "[!] No requirements.txt found — skipping."
fi

##############################################
# Launch Flask server
##############################################

echo "[+] Starting Flask server..."
python -m server.app &
SERVER_PID=$!

echo "[+] Server started with PID $SERVER_PID"
echo "=== Bootstrap complete ==="

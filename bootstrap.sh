#!/bin/bash
set -e

echo "=== Home Automation Bootstrap Start ==="

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$BASE_DIR/.venv"
COMPOSE_FILE="$BASE_DIR/docker-compose.yml"
HA_CONFIG_DIR="$BASE_DIR/ha_config"

##############################################
# 1. Install python 3.13 explicitly
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
# 2. Set up venv with python3.13
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
pip install --upgrade pip wheel setuptools

if [ -f "$BASE_DIR/requirements.txt" ]; then
    echo "[+] Installing Python project dependencies..."
    pip install -r "$BASE_DIR/requirements.txt"
else
    echo "[!] No requirements.txt found — skipping."
fi

##############################################
# 3. Install Docker Desktop if missing
##############################################

if ! command -v docker >/dev/null 2>&1; then
    echo "[+] Docker not found. Installing Docker Desktop..."
    brew install --cask docker

    echo "[+] Launching Docker..."
    open -a Docker

    echo "[*] Waiting for Docker to start..."
    while ! docker info >/dev/null 2>&1; do
        sleep 2
    done
else
    echo "[+] Docker already installed."
fi

##############################################
# 4. Ensure HA config directory exists
##############################################

if [ ! -d "$HA_CONFIG_DIR" ]; then
    echo "[+] Creating Home Assistant config directory..."
    mkdir -p "$HA_CONFIG_DIR"
else
    echo "[+] ha_config directory already exists."
fi

##############################################
# 5. Run docker compose
##############################################

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "[ERROR] docker-compose.yml not found in project root."
    exit 1
fi

echo "[+] Starting Docker Compose stack..."
docker compose -f "$COMPOSE_FILE" up -d

##############################################
# Done
##############################################

echo "=== Bootstrap complete ==="
echo "Home Assistant is available at http://localhost:8123"
echo "Activate Python venv with:"
echo "  source \"$VENV/bin/activate\""

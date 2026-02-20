#!/bin/bash
set -e

echo "=== Home Automation Bootstrap Start ==="

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$BASE_DIR/.venv"

##############################################
# Ensure Homebrew exists
##############################################

ARCH="$(uname -m)"
HW_ARM64="$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)"
if [ "$HW_ARM64" = "1" ]; then
    TARGET_ARCH="arm64"
else
    TARGET_ARCH="$ARCH"
fi

if [ "$TARGET_ARCH" = "arm64" ]; then
    EXPECTED_BREW="/opt/homebrew/bin/brew"
else
    EXPECTED_BREW="/usr/local/bin/brew"
fi

BREW_BIN="$(command -v brew || true)"
if [ -z "$BREW_BIN" ]; then
    if [ -x "$EXPECTED_BREW" ]; then
        BREW_BIN="$EXPECTED_BREW"
    elif [ -x /opt/homebrew/bin/brew ]; then
        BREW_BIN="/opt/homebrew/bin/brew"
    elif [ -x /usr/local/bin/brew ]; then
        BREW_BIN="/usr/local/bin/brew"
    else
        echo "[+] Installing Homebrew ..."
        if [ "$TARGET_ARCH" = "arm64" ] && [ "$ARCH" = "x86_64" ] && command -v arch >/dev/null 2>&1; then
            NONINTERACTIVE=1 /usr/bin/arch -arm64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        else
            NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        if [ -x "$EXPECTED_BREW" ]; then
            BREW_BIN="$EXPECTED_BREW"
        elif [ -x /opt/homebrew/bin/brew ]; then
            BREW_BIN="/opt/homebrew/bin/brew"
        elif [ -x /usr/local/bin/brew ]; then
            BREW_BIN="/usr/local/bin/brew"
        else
            echo "[ERROR] Homebrew install failed or brew not found."
            exit 1
        fi
    fi
fi

if [ "$BREW_BIN" != "$EXPECTED_BREW" ] && [ -x "$EXPECTED_BREW" ]; then
    echo "[!] Using native Homebrew at $EXPECTED_BREW for $TARGET_ARCH"
    BREW_BIN="$EXPECTED_BREW"
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
# Download ASR models
##############################################

ASR_MODEL_DIR="$BASE_DIR/core/asr/models"
mkdir -p "$ASR_MODEL_DIR"

download() {
    local url="$1"
    local output="$2"

    if command -v wget >/dev/null 2>&1; then
        wget -O "$output" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl -L --fail -o "$output" "$url"
    else
        echo "Error: neither wget nor curl is installed" >&2
        exit 1
    fi
}

extract_rename() {
    local filename="$1"
    local target_dir="$2"

    local default_name="${filename%.tar.bz2}"
    if [ -z "$target_dir" ]; then
        target_dir="$default_name"
    fi

    local roots
    roots="$(
        tar -tjf "$filename" \
        | sed 's|^\./||' \
        | cut -d/ -f1 \
        | sort -u
    )"

    tar -xjf "$filename"

    local root_count
    root_count="$(echo "$roots" | wc -l | tr -d ' ')"

    if [[ "$root_count" -eq 1 && -d "$roots" ]]; then
        rm -rf "$target_dir"
        mv "$roots" "$target_dir"
    else
        rm -rf "$target_dir"
        mkdir "$target_dir"

        for item in $roots; do
            [[ -e "$item" ]] && mv "$item" "$target_dir/"
        done
    fi

    rm "$filename"

    local test_wavs_dir="$ASR_MODEL_DIR/$target_dir/test_wavs"
    if [[ -d "$test_wavs_dir" ]]; then
        rm -rf "$test_wavs_dir"
    fi
}

echo "[+] Downloading ASR models..."
pushd "$ASR_MODEL_DIR" >/dev/null

FILENAME="gtcrn_simple.onnx"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/${FILENAME}"
RENAME="denoiser.onnx"
download "$URL" "$FILENAME"
mv "$FILENAME" "$RENAME"

FILENAME="sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8.tar.bz2"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${FILENAME}"
RENAME="asr"
download "$URL" "$FILENAME"
extract_rename "$FILENAME" "$RENAME"

popd >/dev/null

##############################################
# Launch Flask server
##############################################

echo "[+] Starting Flask server..."
python -m server.app &
SERVER_PID=$!

echo "[+] Server started with PID $SERVER_PID"
echo "=== Bootstrap complete ==="

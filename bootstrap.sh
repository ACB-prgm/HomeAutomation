#!/bin/bash
set -e

echo "=== Home Automation Bootstrap Start ==="

if [ "$EUID" -eq 0 ]; then
    if [ -n "${SUDO_USER:-}" ]; then
        echo "[!] Do not run bootstrap as root; re-running as $SUDO_USER"
        exec sudo -u "$SUDO_USER" -H "$0" "$@"
    fi
    echo "[ERROR] Do not run bootstrap as root."
    exit 1
fi

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$BASE_DIR/.venv"

##############################################
# Ensure Python 3.13 exists
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
# install git-lfs
##############################################

get_macos_tag() {
    local version major minor
    version="$(sw_vers -productVersion)"
    major="${version%%.*}"
    minor="${version#*.}"
    minor="${minor%%.*}"
    case "$major" in
        15) echo "sequoia" ;;
        14) echo "sonoma" ;;
        13) echo "ventura" ;;
        12) echo "monterey" ;;
        11) echo "big_sur" ;;
        10)
            if [ "$minor" = "15" ]; then
                echo "catalina"
            else
                echo ""
            fi
            ;;
        *) echo "" ;;
    esac
}

PY_JSON_BIN="$(command -v python3 || true)"
if [ -z "$PY_JSON_BIN" ]; then
    PY_JSON_BIN="/usr/bin/python3"
fi

BREW_LOCK_WARNED=0

brew_prefix() {
    brew --prefix 2>/dev/null || true
}

warn_brew_lock() {
    local prefix lock_path
    prefix="$(brew_prefix)"
    if [ -z "$prefix" ]; then
        if [ "$(uname -m)" = "arm64" ]; then
            prefix="/opt/homebrew"
        else
            prefix="/usr/local"
        fi
    fi

    lock_path="$(find "$prefix/Cellar" -name ".brew.lock" -print -quit 2>/dev/null || true)"
    if [ -n "$lock_path" ]; then
        if [ "$BREW_LOCK_WARNED" -eq 0 ]; then
            echo "[!] Homebrew lock detected at $lock_path"
            echo "[!] Another brew process may be stuck. Consider terminating it and removing the lock file."
            BREW_LOCK_WARNED=1
        fi
        return 0
    fi

    return 1
}

json_output_valid() {
    case "$1" in
        \{*|\[*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

brew_git_lfs_version() {
    local json
    warn_brew_lock >/dev/null 2>&1 || true
    json="$(brew info --json=v2 git-lfs 2>/dev/null || true)"
    if [ -z "$json" ] || ! json_output_valid "$json"; then
        echo ""
        return 1
    fi
    printf "%s" "$json" | "$PY_JSON_BIN" - <<'PY'
import json, sys
data = json.load(sys.stdin)
version = data.get("formulae", [{}])[0].get("versions", {}).get("stable", "")
print(version)
PY
}

brew_git_lfs_has_bottle() {
    local os_tag arch_tag
    warn_brew_lock >/dev/null 2>&1 || true
    os_tag="$(get_macos_tag)"
    if [ -z "$os_tag" ]; then
        return 1
    fi

    if [ "$(uname -m)" = "arm64" ]; then
        arch_tag="arm64_${os_tag}"
    else
        arch_tag="$os_tag"
    fi

    local json
    json="$(brew info --json=v2 git-lfs 2>/dev/null || true)"
    if [ -z "$json" ] || ! json_output_valid "$json"; then
        return 1
    fi

    OS_TAG="$os_tag" ARCH_TAG="$arch_tag" printf "%s" "$json" | "$PY_JSON_BIN" - <<'PY'
import json, os, sys
data = json.load(sys.stdin)
files = data.get("formulae", [{}])[0].get("bottle", {}).get("stable", {}).get("files", {})
os_tag = os.environ.get("OS_TAG")
arch_tag = os.environ.get("ARCH_TAG")
if arch_tag in files or os_tag in files:
    sys.exit(0)
sys.exit(1)
PY
}

install_git_lfs_from_github() {
    local url=""
    local version="${GIT_LFS_VERSION:-}"
    local arch_tag="darwin-amd64"
    local install_dir="${GIT_LFS_INSTALL_DIR:-/usr/local/bin}"

    if [ "$(uname -m)" = "arm64" ]; then
        arch_tag="darwin-arm64"
    fi

    if [ -n "${GIT_LFS_URL:-}" ]; then
        url="$GIT_LFS_URL"
    elif [ -n "$version" ]; then
        url="https://github.com/git-lfs/git-lfs/releases/download/v${version}/git-lfs-${arch_tag}-v${version}.zip"
    else
        echo "[ERROR] Set GIT_LFS_VERSION or GIT_LFS_URL to install from GitHub."
        return 1
    fi

    echo "[+] Installing git-lfs from GitHub: $url"
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    curl -L "$url" -o "$tmp_dir/git-lfs.zip"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q "$tmp_dir/git-lfs.zip" -d "$tmp_dir/unpack"
    else
        ditto -x -k "$tmp_dir/git-lfs.zip" "$tmp_dir/unpack"
    fi

    local bin_path
    bin_path="$(find "$tmp_dir/unpack" -type f -name git-lfs -perm -111 | head -n 1)"
    if [ -z "$bin_path" ]; then
        echo "[ERROR] git-lfs binary not found in archive."
        rm -rf "$tmp_dir"
        return 1
    fi

    if [ ! -w "$install_dir" ]; then
        install_dir="$HOME/.local/bin"
        mkdir -p "$install_dir"
        echo "[!] /usr/local/bin not writable; installing to $install_dir"
        echo "[!] Ensure $install_dir is in PATH."
    fi

    install -m 755 "$bin_path" "$install_dir/git-lfs"
    "$install_dir/git-lfs" install --skip-repo || true
    rm -rf "$tmp_dir"
}

GIT_LFS_INSTALL_METHOD="${GIT_LFS_INSTALL_METHOD:-auto}"
GIT_LFS_FALLBACK_VERSION="${GIT_LFS_FALLBACK_VERSION:-3.7.1}"
if ! command -v git-lfs >/dev/null 2>&1 && ! brew list --formula git-lfs >/dev/null 2>&1; then
    if [ "$GIT_LFS_INSTALL_METHOD" = "auto" ]; then
        if brew_git_lfs_has_bottle; then
            GIT_LFS_INSTALL_METHOD="brew"
        else
            GIT_LFS_INSTALL_METHOD="github"
        fi
    fi

    if [ "$GIT_LFS_INSTALL_METHOD" = "github" ]; then
        if [ -z "${GIT_LFS_VERSION:-}" ] && [ -z "${GIT_LFS_URL:-}" ]; then
            GIT_LFS_VERSION="$GIT_LFS_FALLBACK_VERSION"
            export GIT_LFS_VERSION
        fi
        install_git_lfs_from_github
    else
        echo "[+] Installing git-lfs (Homebrew)..."
        if ! brew install git-lfs; then
            echo "[!] Homebrew install failed."
            exit 1
        fi
    fi
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

brew_ollama_has_bottle() {
    local os_tag arch_tag
    warn_brew_lock >/dev/null 2>&1 || true
    os_tag="$(get_macos_tag)"
    if [ -z "$os_tag" ]; then
        return 1
    fi

    if [ "$(uname -m)" = "arm64" ]; then
        arch_tag="arm64_${os_tag}"
    else
        arch_tag="$os_tag"
    fi

    local json
    json="$(brew info --json=v2 ollama 2>/dev/null || true)"
    if [ -z "$json" ] || ! json_output_valid "$json"; then
        return 1
    fi

    OS_TAG="$os_tag" ARCH_TAG="$arch_tag" printf "%s" "$json" | "$PY_JSON_BIN" - <<'PY'
import json, os, sys
data = json.load(sys.stdin)
files = data.get("formulae", [{}])[0].get("bottle", {}).get("stable", {}).get("files", {})
os_tag = os.environ.get("OS_TAG")
arch_tag = os.environ.get("ARCH_TAG")
if arch_tag in files or os_tag in files:
    sys.exit(0)
sys.exit(1)
PY
}

install_ollama_from_github() {
    local url=""
    local version="${OLLAMA_VERSION:-}"
    local arch_tag="darwin-amd64"
    local install_dir="${OLLAMA_INSTALL_DIR:-/usr/local/bin}"
    local tmp_dir

    if [ "$(uname -m)" = "arm64" ]; then
        arch_tag="darwin-arm64"
    fi

    if [ -n "${OLLAMA_URL:-}" ]; then
        url="$OLLAMA_URL"
    elif [ -n "$version" ]; then
        local base="https://github.com/ollama/ollama/releases/download/v${version}"
        local candidates=(
            "${base}/ollama-${arch_tag}"
            "${base}/ollama-darwin"
            "${base}/ollama-${arch_tag}.zip"
            "${base}/ollama-darwin.zip"
            "${base}/ollama-${arch_tag}.tgz"
            "${base}/ollama-darwin.tgz"
            "${base}/ollama-${arch_tag}.tar.gz"
            "${base}/ollama-darwin.tar.gz"
        )
        for candidate in "${candidates[@]}"; do
            if curl -fL "$candidate" -o /tmp/ollama-download >/dev/null 2>&1; then
                url="$candidate"
                break
            fi
        done
    else
        echo "[ERROR] Set OLLAMA_VERSION or OLLAMA_URL to install from GitHub."
        return 1
    fi

    if [ -z "$url" ]; then
        echo "[ERROR] Unable to find a suitable Ollama release asset."
        return 1
    fi

    echo "[+] Installing ollama from GitHub: $url"
    tmp_dir="$(mktemp -d)"
    curl -L "$url" -o "$tmp_dir/ollama-download"

    local bin_path=""
    if [[ "$url" == *.zip ]]; then
        if command -v unzip >/dev/null 2>&1; then
            unzip -q "$tmp_dir/ollama-download" -d "$tmp_dir/unpack"
        else
            ditto -x -k "$tmp_dir/ollama-download" "$tmp_dir/unpack"
        fi
        bin_path="$(find "$tmp_dir/unpack" -type f -name ollama -perm -111 | head -n 1)"
    elif [[ "$url" == *.tgz ]] || [[ "$url" == *.tar.gz ]]; then
        mkdir -p "$tmp_dir/unpack"
        tar -xzf "$tmp_dir/ollama-download" -C "$tmp_dir/unpack"
        bin_path="$(find "$tmp_dir/unpack" -type f -name ollama -perm -111 | head -n 1)"
    else
        bin_path="$tmp_dir/ollama-download"
        chmod +x "$bin_path"
    fi

    if [ -z "$bin_path" ]; then
        echo "[ERROR] ollama binary not found in archive."
        rm -rf "$tmp_dir"
        return 1
    fi

    if [ ! -w "$install_dir" ]; then
        install_dir="$HOME/.local/bin"
        mkdir -p "$install_dir"
        echo "[!] /usr/local/bin not writable; installing to $install_dir"
        echo "[!] Ensure $install_dir is in PATH."
    fi

    install -m 755 "$bin_path" "$install_dir/ollama"
    rm -rf "$tmp_dir"
    echo "$install_dir/ollama"
}

OLLAMA_INSTALL_METHOD="${OLLAMA_INSTALL_METHOD:-auto}"
OLLAMA_FALLBACK_VERSION="${OLLAMA_FALLBACK_VERSION:-0.13.1}"
OLLAMA_BIN="ollama"

if ! command -v ollama >/dev/null 2>&1 && ! brew list --formula ollama >/dev/null 2>&1; then
    if [ "$OLLAMA_INSTALL_METHOD" = "auto" ]; then
        if brew_ollama_has_bottle; then
            OLLAMA_INSTALL_METHOD="brew"
        else
            OLLAMA_INSTALL_METHOD="github"
        fi
    fi

    if [ "$OLLAMA_INSTALL_METHOD" = "github" ]; then
        if [ -z "${OLLAMA_VERSION:-}" ] && [ -z "${OLLAMA_URL:-}" ]; then
            OLLAMA_VERSION="$OLLAMA_FALLBACK_VERSION"
            export OLLAMA_VERSION
        fi
        OLLAMA_BIN="$(install_ollama_from_github)"
    else
        echo "[+] Installing ollama (Homebrew)..."
        brew install ollama
    fi
else
    echo "[+] ollama already installed."
fi

if brew list --formula ollama >/dev/null 2>&1; then
    if brew services list | grep -q '^ollama'; then
        STATUS="$(brew services list | awk '$1 == \"ollama\" {print $2}')"
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
else
    echo "[+] Starting ollama in background..."
    "$OLLAMA_BIN" serve >/tmp/ollama.log 2>&1 &
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

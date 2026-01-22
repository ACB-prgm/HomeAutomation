#!/bin/bash
set -euo pipefail

echo "=== HomeAutomation macOS Server Setup ==="

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Run this script with sudo."
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
echo "[+] Target user: $REAL_USER"

##############################################
# Enable SSH (remote login)
##############################################

echo "[+] Enabling SSH..."
systemsetup -setremotelogin on

SSHD_CONFIG="/etc/ssh/sshd_config"
BACKUP="/etc/ssh/sshd_config.bak-$(date +%Y%m%d%H%M%S)"
cp "$SSHD_CONFIG" "$BACKUP"
echo "[+] Backed up sshd_config to $BACKUP"

update_sshd() {
    local key="$1"
    local value="$2"
    if grep -qE "^[# ]*${key}\b" "$SSHD_CONFIG"; then
        sed -i '' -E "s|^[# ]*${key}\b.*|${key} ${value}|g" "$SSHD_CONFIG"
    else
        printf "\n%s %s\n" "$key" "$value" >> "$SSHD_CONFIG"
    fi
}

update_sshd "PasswordAuthentication" "yes"
update_sshd "PermitRootLogin" "no"
update_sshd "KbdInteractiveAuthentication" "no"

echo "[+] Reloading SSH daemon..."
launchctl kickstart -k system/com.openssh.sshd

##############################################
# Auto-restart after power loss
##############################################

echo "[+] Enabling auto-restart after power failure..."
pmset -a autorestart 1
systemsetup -setrestartpowerfailure on

##############################################
# Disable automatic login
##############################################

echo "[+] Disabling automatic login..."
defaults delete /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null || true
defaults write /Library/Preferences/com.apple.loginwindow DisableAutomaticLogin -bool true

##############################################
# Firewall
##############################################

# echo "[+] Enabling Application Firewall..."
# /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
# /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on
# /usr/libexec/ApplicationFirewall/socketfilterfw --setallowsigned on
# /usr/libexec/ApplicationFirewall/socketfilterfw --setallowsignedapp on

echo "=== Server setup complete ==="
echo "Note: Ensure $REAL_USER has a login password set for SSH."

##############################################
# Run bootstrap
##############################################

BOOTSTRAP="$PWD/bootstrap.sh"
if [ -f "$BOOTSTRAP" ]; then
    echo "[+] Ensuring bootstrap.sh is executable..."
    chmod +x "$BOOTSTRAP"
    echo "[+] Running bootstrap.sh as $REAL_USER..."
    sudo -u "$REAL_USER" "$BOOTSTRAP"
else
    echo "[!] bootstrap.sh not found at $BOOTSTRAP"
fi

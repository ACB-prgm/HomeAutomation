#!/bin/bash
set -euo pipefail

echo "=== HomeAutomation macOS Server Setup ==="

if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Run this script with sudo."
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
echo "[+] Target user: $REAL_USER"

warn_continue() {
    echo "[WARN] $1 (continuing)"
}

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
# Show IP + SSH hint
##############################################

IP_ADDR="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [ -z "$IP_ADDR" ]; then
    IP_ADDR="$(ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [ -z "$IP_ADDR" ]; then
    IP_ADDR="$(ifconfig | awk '/inet / && $2 != "127.0.0.1" {print $2; exit}')"
fi

if [ -n "$IP_ADDR" ]; then
    echo "[+] Device IP: $IP_ADDR"
    echo "[+] SSH example: ssh $REAL_USER@$IP_ADDR"
else
    echo "[WARN] Could not determine IP address."
fi

##############################################
# Power management (server reliability)
##############################################

if pmset -g batt 2>/dev/null | grep -q "InternalBattery"; then
    PMSET_SCOPE="-c"
    POWER_PROFILE="AC power (laptop detected)"
else
    PMSET_SCOPE="-a"
    POWER_PROFILE="all power sources"
fi

echo "[+] Applying power settings for $POWER_PROFILE..."
pmset "$PMSET_SCOPE" sleep 0 disksleep 0 powernap 1 womp 1 tcpkeepalive 1 || warn_continue "pmset power settings failed"

##############################################
# Auto-restart after power loss
##############################################

echo "[+] Enabling auto-restart after power failure..."
pmset -a autorestart 1 || warn_continue "pmset autorestart failed"
systemsetup -setrestartpowerfailure on || warn_continue "systemsetup restartpowerfailure failed"

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

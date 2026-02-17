#!/usr/bin/env bash
set -euo pipefail

RULE_PATH="${RULE_PATH:-/etc/udev/rules.d/99-respeaker-xvf3800.rules}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
	if command -v sudo >/dev/null 2>&1; then
		exec sudo "$0" "$@"
	fi
	echo "[respeaker-udev] Must run as root." >&2
	exit 1
fi

cat > "$RULE_PATH" <<'EOF'
# ReSpeaker XVF3800 USB permissions
SUBSYSTEM=="usb", ATTR{idVendor}=="2886", ATTR{idProduct}=="001a", MODE:="0660", GROUP:="audio", TAG+="uaccess"
EOF

chmod 644 "$RULE_PATH"

if command -v udevadm >/dev/null 2>&1; then
	udevadm control --reload-rules
	udevadm trigger --attr-match=idVendor=2886 --attr-match=idProduct=001a || true
fi

if command -v lsusb >/dev/null 2>&1; then
	info="$(lsusb -d 2886:001a || true)"
	if [[ -n "$info" ]]; then
		bus="$(echo "$info" | awk '{print $2}')"
		dev="$(echo "$info" | awk '{print $4}' | tr -d ':')"
		dev_path="/dev/bus/usb/$bus/$dev"
		if [[ -e "$dev_path" ]]; then
			echo "[respeaker-udev] Device permissions: $(ls -l "$dev_path")"
		fi
	fi
fi

echo "[respeaker-udev] Installed rule at $RULE_PATH"

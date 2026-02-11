from __future__ import annotations

import socket
import subprocess
import sys
from typing import Callable


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _hardware_ports() -> list[dict[str, str]]:
    try:
        out = _run(["networksetup", "-listallhardwareports"])
    except Exception:
        return []

    ports: list[dict[str, str]] = []
    block: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            if block:
                ports.append(block)
                block = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        block[key.strip()] = value.strip()

    if block:
        ports.append(block)

    return ports


def _ip_for_device(device: str) -> str | None:
    if not device:
        return None
    try:
        return _run(["ipconfig", "getifaddr", device])
    except Exception:
        return None


def _pick_ip(ports: list[dict[str, str]], predicate: Callable[[str], bool]) -> str | None:
    for port in ports:
        name = port.get("Hardware Port", "")
        if predicate(name):
            ip = _ip_for_device(port.get("Device", ""))
            if ip:
                return ip
    return None


def _default_route_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # This does not send packets; it selects the outbound interface.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return None
    finally:
        sock.close()


def get_preferred_ip() -> str:
    if sys.platform == "darwin":
        ports = _hardware_ports()
        ip = _pick_ip(ports, lambda name: "Ethernet" in name)
        if ip:
            return ip
        ip = _pick_ip(ports, lambda name: name in ("Wi-Fi", "AirPort"))
        if ip:
            return ip

    ip = _default_route_ip()
    return ip or "127.0.0.1"

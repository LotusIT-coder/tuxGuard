#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kleiner PAM-Connector-Client für den optionalen TuxGuard-System-Login.

Dieses Tool ist für einen externen PAM-Wrapper gedacht:
- Exit 0: biometrische Auth erfolgreich
- Exit 1: biometrisch abgelehnt, Passwort-Fallback verwenden
- Exit 2: technischer Fehler, Passwort-Fallback verwenden
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Dict, Optional

from config import Config


def send_request(socket_path: str, payload: Dict[str, object], timeout: float) -> Dict[str, object]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(max(0.1, float(timeout)))
    try:
        client.connect(socket_path)
        client.sendall((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))
        chunks = []
        while True:
            data = client.recv(4096)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        return json.loads(raw) if raw else {}
    finally:
        client.close()


def authenticate(
    username: str,
    image_path: str,
    pin: Optional[str],
    socket_path: str,
    timeout: float,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "action": "authenticate",
        "username": username,
        "image_path": image_path,
    }
    if pin is not None:
        payload["pin"] = pin
    return send_request(socket_path=socket_path, payload=payload, timeout=timeout)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TuxGuard PAM connector client")
    parser.add_argument("--username", required=True, help="Linux-Benutzername")
    parser.add_argument("--image-path", required=True, help="Pfad zu einem Kameraframe")
    parser.add_argument(
        "--pin-stdin",
        action="store_true",
        help="PIN aus der ersten stdin-Zeile lesen (nie als Argument übergeben)",
    )
    parser.add_argument(
        "--socket",
        default=str(getattr(Config, "SYSTEM_LOGIN_SOCKET_PATH", "/run/tuxguard-authd.sock")),
        help="Unix-Socket Pfad des TuxGuard Auth-Daemons",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(getattr(Config, "SYSTEM_LOGIN_REQUEST_TIMEOUT_SECONDS", 8.0)),
        help="Timeout in Sekunden",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    pin: Optional[str] = None
    if args.pin_stdin:
        # PIN nie über argv (via ps/procfs einsehbar), nur über stdin.
        pin = sys.stdin.readline().rstrip("\n") or None
    try:
        result = authenticate(
            username=args.username,
            image_path=args.image_path,
            pin=pin,
            socket_path=args.socket,
            timeout=args.timeout,
        )
    except Exception:
        return 2

    if bool(result.get("ok", False)) and str(result.get("result", "")) == "accepted":
        return 0
    if bool(result.get("requires_password_fallback", True)):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

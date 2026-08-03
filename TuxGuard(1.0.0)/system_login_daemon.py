#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optionaler TuxGuard Auth-Daemon für System-Login (PAM-Connector Backend).

JSON-Line-Protokoll über Unix-Socket:

Request:
  {"action":"ping"}
  {"action":"authenticate","username":"alice","image_path":"/tmp/frame.jpg","pin":"123456"}

Response:
  {"ok":true,"service":"tuxguard-authd"}
  {"ok":true,"result":"accepted","user":"alice","requires_password_fallback":false}
  {"ok":false,"result":"rejected","reason":"...","requires_password_fallback":true}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import stat
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from config import Config
from database import DatabaseManager
from face_mediapipe import face_distance, safe_face_analysis_from_file
from logging_setup import setup_logging
from system_login_policy import (
    AttemptLimiter,
    LoginPolicy,
    decide_before_auth,
    requires_pin_second_factor,
)

logger = logging.getLogger("TuxGuard.SystemLogin")

# Obergrenzen gegen DoS über den lokalen Socket.
_MAX_REQUEST_BYTES = 64 * 1024
_CLIENT_TIMEOUT_SECONDS = 10.0
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass
class AuthResult:
    ok: bool
    result: str
    reason: str = ""
    user: Optional[str] = None
    confidence: Optional[float] = None
    requires_password_fallback: bool = True

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "ok": bool(self.ok),
            "result": self.result,
            "requires_password_fallback": bool(self.requires_password_fallback),
        }
        if self.reason:
            data["reason"] = self.reason
        if self.user:
            data["user"] = self.user
        if self.confidence is not None:
            data["confidence"] = float(self.confidence)
        return data


class SystemLoginAuthenticator:
    def __init__(self, db_manager: DatabaseManager, policy: LoginPolicy):
        self.db_manager = db_manager
        self.policy = policy
        self.limiter = AttemptLimiter(policy)
        self.tolerance = float(getattr(Config, "SYSTEM_LOGIN_FACE_TOLERANCE", Config.FACE_MATCH_TOLERANCE))

    def authenticate(self, username: str, image_path: str, pin: Optional[str] = None) -> AuthResult:
        user_name = (username or "").strip()
        if not user_name:
            return AuthResult(False, "rejected", reason="missing_username")
        if not image_path:
            return AuthResult(False, "rejected", reason="missing_image_path")

        pre = decide_before_auth(self.policy, self.limiter, user_name)
        if not pre.allowed:
            return AuthResult(
                False,
                "rejected",
                reason=pre.reason,
                requires_password_fallback=pre.fallback_to_password,
            )

        path_error = _validate_image_path(image_path)
        if path_error:
            return AuthResult(False, "rejected", reason=path_error)

        try:
            auth_result = self._authenticate_face(user_name, image_path)
            if not auth_result.ok:
                self.limiter.register_attempt(user_name, success=False)
                return auth_result

            if requires_pin_second_factor(self.policy):
                if not pin:
                    self.limiter.register_attempt(user_name, success=False)
                    return AuthResult(
                        False,
                        "rejected",
                        reason="pin_required",
                        requires_password_fallback=True,
                    )
                if not self.db_manager.verify_user_pin_for_user(user_name, pin):
                    self.limiter.register_attempt(user_name, success=False)
                    return AuthResult(
                        False,
                        "rejected",
                        reason="pin_invalid",
                        requires_password_fallback=True,
                    )

            self.limiter.register_attempt(user_name, success=True)
            return AuthResult(
                True,
                "accepted",
                reason="ok",
                user=user_name,
                confidence=auth_result.confidence,
                requires_password_fallback=False,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Auth-Ausnahme für Benutzer %s: %s", user_name, exc)
            self.limiter.register_attempt(user_name, success=False)
            return AuthResult(
                False,
                "error",
                reason="internal_error",
                requires_password_fallback=True,
            )

    def _authenticate_face(self, username: str, image_path: str) -> AuthResult:
        known_encodings = self.db_manager.get_user_face_encodings(username)
        if not known_encodings:
            return AuthResult(False, "rejected", reason="no_templates_for_user")

        analysis = safe_face_analysis_from_file(
            image_path,
            timeout=max(1, int(getattr(Config, "SYSTEM_LOGIN_REQUEST_TIMEOUT_SECONDS", 8))),
        )
        encodings = list(analysis.get("encodings", []))
        if not encodings:
            return AuthResult(False, "rejected", reason="no_face_detected")

        candidates = [enc for _, enc in known_encodings]
        best_distance = float("inf")
        for probe in encodings:
            distances = face_distance(candidates, np.asarray(probe, dtype=np.float64))
            if distances.size:
                best_distance = min(best_distance, float(distances.min()))

        if not np.isfinite(best_distance):
            return AuthResult(False, "rejected", reason="distance_unavailable")

        confidence = float(max(0.0, min(1.0, 1.0 - (best_distance / max(self.tolerance, 1e-6)))))
        if best_distance > self.tolerance:
            return AuthResult(
                False,
                "rejected",
                reason="face_mismatch",
                confidence=confidence,
            )

        return AuthResult(True, "accepted", reason="face_match", user=username, confidence=confidence)


def _validate_image_path(image_path: str) -> Optional[str]:
    """Wehrt Symlink-/FIFO-/Größen-Angriffe auf den privilegierten Daemon ab."""
    try:
        path = Path(image_path)
        if not path.is_absolute():
            return "image_path_not_absolute"
        resolved = path.resolve(strict=True)
        info = os.lstat(resolved)
        if not stat.S_ISREG(info.st_mode):
            return "image_path_not_regular_file"
        if info.st_size <= 0 or info.st_size > _MAX_IMAGE_BYTES:
            return "image_path_size_invalid"
    except (OSError, RuntimeError):
        return "image_path_unreadable"
    return None


class AuthDaemon:
    def __init__(self, socket_path: str):
        self.socket_path = Path(socket_path)
        self.logger = setup_logging()
        self.policy = LoginPolicy.from_config()
        self.db = DatabaseManager()
        self.auth = SystemLoginAuthenticator(self.db, self.policy)
        self._server: Optional[socket.socket] = None

    def run(self) -> None:
        self._prepare_socket_path()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # umask statt nachträglichem chmod: kein Zeitfenster mit laxen Rechten.
        old_umask = os.umask(0o177)
        try:
            server.bind(str(self.socket_path))
        finally:
            os.umask(old_umask)
        server.listen(32)
        self._server = server

        self.logger.info(
            "System-Login-Daemon gestartet: socket=%s enabled=%s mode=%s",
            self.socket_path,
            self.policy.enabled,
            self.policy.mode,
        )
        while True:
            conn, _ = server.accept()
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _prepare_socket_path(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(_CLIENT_TIMEOUT_SECONDS)
                if not self._peer_allowed(conn):
                    self._send_json(conn, {
                        "ok": False,
                        "result": "rejected",
                        "reason": "peer_not_allowed",
                        "requires_password_fallback": True,
                    })
                    return
                payload = self._recv_json(conn)
                action = str(payload.get("action", "")).strip().lower()
                if action == "ping":
                    self._send_json(conn, {"ok": True, "service": "tuxguard-authd"})
                    return
                if action == "authenticate":
                    username = str(payload.get("username", "") or "")
                    image_path = str(payload.get("image_path", "") or "")
                    pin = payload.get("pin")
                    pin_val = str(pin) if pin is not None else None
                    result = self.auth.authenticate(username=username, image_path=image_path, pin=pin_val)
                    self._send_json(conn, result.to_dict())
                    return
                self._send_json(conn, {
                    "ok": False,
                    "result": "error",
                    "reason": "unknown_action",
                    "requires_password_fallback": True,
                })
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Client-Verarbeitung fehlgeschlagen: %s", exc)
                self._send_json(conn, {
                    "ok": False,
                    "result": "error",
                    "reason": "invalid_request",
                    "requires_password_fallback": True,
                })

    @staticmethod
    def _peer_allowed(conn: socket.socket) -> bool:
        """Erlaubt nur root oder Prozesse mit der UID des Daemons."""
        try:
            creds = conn.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            _pid, uid, _gid = struct.unpack("3i", creds)
            return uid in (0, os.getuid())
        except (OSError, struct.error):
            return False

    @staticmethod
    def _recv_json(conn: socket.socket) -> Dict[str, object]:
        chunks = []
        total = 0
        while True:
            data = conn.recv(4096)
            if not data:
                break
            total += len(data)
            if total > _MAX_REQUEST_BYTES:
                raise ValueError("request too large")
            chunks.append(data)
            if b"\n" in data:
                break
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not raw:
            return {}
        return json.loads(raw)

    @staticmethod
    def _send_json(conn: socket.socket, payload: Dict[str, object]) -> None:
        conn.sendall((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TuxGuard optional system login auth daemon")
    parser.add_argument(
        "--socket",
        default=str(getattr(Config, "SYSTEM_LOGIN_SOCKET_PATH", "/tmp/tuxguard-authd.sock")),
        help="Unix-Socket Pfad",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    daemon = AuthDaemon(socket_path=args.socket)
    daemon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

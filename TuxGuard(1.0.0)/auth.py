#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Authentication Module
================================

Verwaltet:
  * Master-Passwort + Recovery-Code (zentral, nur per Recovery-Code änderbar)
  * Passwort-Hashing (PBKDF2-SHA256) für Benutzer- und Master-Credentials
  * Generierung sicherer Recovery-Codes

Speicherformat (JSON in ``Config.MASTER_CREDENTIALS_FILE``)::

    {
        "version": 1,
        "password": "pbkdf2_sha256$<iter>$<salt>$<hash>",
        "additional_passwords": [
            "pbkdf2_sha256$<iter>$<salt>$<hash>"
        ],
        "recovery": "pbkdf2_sha256$<iter>$<salt>$<hash>",
        "created_at": "2024-01-01T12:00:00"
    }

Die Datei wird mit ``0600`` Rechten erzeugt; sie enthält nur Hashes,
nie Klartext-Geheimnisse.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import Config
from database import SecurityUtils

logger = logging.getLogger("TuxGuard.Auth")


# ---------------------------------------------------------------------------
# Passwort-Hashing (delegiert an SecurityUtils, semantisch generischer Name)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Erzeugt einen PBKDF2-Hash für ein Passwort/Recovery-Code."""
    return SecurityUtils.hash_pin_pbkdf2(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Prüft ein Passwort gegen einen gespeicherten PBKDF2-Hash."""
    if not stored_hash:
        return False
    return SecurityUtils.verify_pin(password, stored_hash)


# ---------------------------------------------------------------------------
# Recovery-Codes
# ---------------------------------------------------------------------------

_RECOVERY_ALPHABET = string.ascii_uppercase + string.digits
_RECOVERY_GROUPS = 4   # 4 Gruppen
_RECOVERY_GROUP_LEN = 5  # mit je 5 Zeichen → 20 Zeichen Gesamtentropie


def generate_recovery_code() -> str:
    """Erzeugt einen leicht abschreibbaren Recovery-Code (z.B. ``A1B2C-...``)."""
    groups = [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_GROUP_LEN))
        for _ in range(_RECOVERY_GROUPS)
    ]
    return "-".join(groups)


def normalize_recovery_code(code: str) -> str:
    """Normalisiert einen Recovery-Code (Großbuchstaben, ohne Whitespace)."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


# ---------------------------------------------------------------------------
# MasterAuth: zentrale Verwaltung des Master-Passworts
# ---------------------------------------------------------------------------

class MasterAuthError(Exception):
    """Fehler im Master-Authentifizierungssystem."""


class MasterAuth:
    """Persistente Verwaltung des TuxGuard-Master-Passworts."""

    VERSION = 1

    def __init__(self, path: Optional[Path] = None):
        self.path: Path = Path(path) if path else Path(Config.MASTER_CREDENTIALS_FILE)

    # -- Status -----------------------------------------------------------

    def is_initialized(self) -> bool:
        """True, sobald eine gültige Master-Credential-Datei existiert."""
        if not self.path.exists():
            return False
        try:
            data = self._load()
            return bool(data.get("password") and data.get("recovery"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Master-Credentials konnten nicht gelesen werden: %s", exc)
            return False

    # -- Initialisierung --------------------------------------------------

    def initialize(self, password: str, recovery_code: Optional[str] = None) -> str:
        """Legt Master-Passwort + Recovery-Code an. Gibt den Recovery-Code zurück.

        Schlägt fehl, wenn bereits initialisiert.
        """
        if self.is_initialized():
            raise MasterAuthError("Master-Passwort ist bereits gesetzt.")
        self._validate_password(password)

        code = recovery_code or generate_recovery_code()
        normalized = normalize_recovery_code(code)
        if len(normalized) < 12:
            raise MasterAuthError("Recovery-Code zu kurz.")

        self._save({
            "version": self.VERSION,
            "password": hash_password(password),
            "additional_passwords": [],
            "recovery": hash_password(normalized),
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        })
        logger.info("Master-Credentials initialisiert (%s)", self.path)
        return code

    # -- Verifikation -----------------------------------------------------

    def verify(self, password: str) -> bool:
        """Prüft das Master-Passwort."""
        if not password:
            return False
        try:
            data = self._load()
        except FileNotFoundError:
            return False
        return verify_password(password, data.get("password", ""))

    def verify_recovery(self, code: str) -> bool:
        """Prüft den Recovery-Code."""
        if not code:
            return False
        try:
            data = self._load()
        except FileNotFoundError:
            return False
        return verify_password(normalize_recovery_code(code), data.get("recovery", ""))

    def verify_admin_password(self, password: str) -> bool:
        """Prüft ein Admin-Passwort (primär oder zusätzlich)."""
        if not password:
            return False
        try:
            data = self._load()
        except FileNotFoundError:
            return False

        if verify_password(password, data.get("password", "")):
            return True

        for stored_hash in data.get("additional_passwords", []):
            if verify_password(password, stored_hash):
                return True
        return False

    def add_admin_password(self, primary_admin_password: str, new_password: str) -> int:
        """Fügt ein weiteres Admin-Passwort hinzu.

        Autorisierung erfolgt bewusst nur über das primäre Master-Passwort.
        Gibt die Gesamtanzahl hinterlegter Admin-Passwörter zurück.
        """
        if not self.verify(primary_admin_password):
            raise MasterAuthError("Primäres Admin-Passwort ungültig.")
        self._validate_password(new_password)

        data = self._load()
        additional = list(data.get("additional_passwords", []))

        if verify_password(new_password, data.get("password", "")):
            raise MasterAuthError("Dieses Passwort ist bereits als primäres Admin-Passwort gesetzt.")
        for stored_hash in additional:
            if verify_password(new_password, stored_hash):
                raise MasterAuthError("Dieses Passwort ist bereits als zusätzliches Admin-Passwort vorhanden.")

        additional.append(hash_password(new_password))
        data["additional_passwords"] = additional
        self._save(data)
        logger.info("Zusätzliches Admin-Passwort hinzugefügt")
        return 1 + len(additional)

    # -- Passwortänderung -------------------------------------------------

    def change_password_with_recovery(self, recovery_code: str, new_password: str) -> str:
        """Setzt ein neues Master-Passwort, wenn der Recovery-Code stimmt.

        Erzeugt zugleich einen neuen Recovery-Code (alter Code wird ungültig).
        Gibt den neuen Recovery-Code zurück.
        """
        if not self.verify_recovery(recovery_code):
            raise MasterAuthError("Ungültiger Recovery-Code.")
        self._validate_password(new_password)

        data = self._load()
        additional = list(data.get("additional_passwords", []))

        new_code = generate_recovery_code()
        self._save({
            "version": self.VERSION,
            "password": hash_password(new_password),
            "additional_passwords": additional,
            "recovery": hash_password(normalize_recovery_code(new_code)),
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        })
        logger.warning("Master-Passwort wurde per Recovery-Code zurückgesetzt.")
        return new_code

    # -- Interna ----------------------------------------------------------

    def _load(self) -> dict:
        with open(self.path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - best effort on non-POSIX
            pass

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or len(password) < Config.MIN_PASSWORD_LENGTH:
            raise MasterAuthError(
                f"Passwort muss mindestens {Config.MIN_PASSWORD_LENGTH} Zeichen lang sein."
            )

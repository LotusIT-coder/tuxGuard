#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Configuration Module
Zentrale Konfigurationsdatei für alle Anwendungsparameter
"""

import os
from pathlib import Path

class Config:
    """Zentrale Konfigurationsklasse für TuxGuard"""
    
    # Anwendungskonstanten
    APP_NAME = "TuxGuard"
    APP_VERSION = "2.0.0"
    APP_WM_CLASS = "TuxGuard"
    
    # Ermittle das Installationsverzeichnis (relativ zum Skriptpfad)
    _SCRIPT_DIR = Path(__file__).resolve().parent
    
    # Datenbankeinstellungen
    DATABASE_FILE = "face_recognition.db"
    
    # Sicherheitseinstellungen
    MAX_SESSION_DURATION = 12 * 3600  # 12 Stunden in Sekunden
    MIN_PIN_LENGTH = 6
    MIN_PASSWORD_LENGTH = 8
    PBKDF2_ITERATIONS = 100_000
    SECURITY_MODE = "strict_pin"
    DEADMAN_TIMEOUT_SECONDS = 60
    DEADMAN_ACTION = "suspend"

    # Auto-Lock nach fehlender Erkennung (Sekunden)
    SECURITY_LOCK_DELAY_SECONDS = 10
    # Sperrziel: "screen" (nur TuxGuard-Overlay) oder "computer" (zusätzlich loginctl lock-session)
    LOCK_TARGET = "screen"

    # Master-Credential-Datei (vom Installer angelegt, enthält Master-Passwort + Recovery-Hash)
    MASTER_CREDENTIALS_FILE = _SCRIPT_DIR / "master_credentials.json"
    
    # Kameraeinstellungen
    CAMERA_DEVICE = "/dev/video0"
    CAMERA_LOCK_FILE = "/tmp/tuxguard_camera.lock"
    CAMERA_RETRY_ATTEMPTS = 3
    CAMERA_RETRY_DELAY = 1  # Sekunden
    
    # Modell-Pfade (relativ zum Installationsverzeichnis)
    MODELS_DIR = _SCRIPT_DIR / "models"
    FACE_LANDMARKER_MODEL = MODELS_DIR / "face_landmarker_v2.task"
    
    # Adaptives Lernen
    ADAPTIVE_RETRAIN_INTERVAL = 10
    ADAPTIVE_POSITIVE_SAMPLES_MAX = 1000

    # Emotionsanzeige (optional, nur Live-Overlay)
    EMOTION_OVERLAY_ENABLED = True
    EMOTION_MIN_CONFIDENCE = 0.35
    EMOTION_SMOOTHING_ALPHA = 0.35
    EMOTION_TRACK_MAX_DISTANCE = 90.0
    EMOTION_TRACK_TTL_SECONDS = 1.5
    
    # Logging (relativ zum Installationsverzeichnis)
    LOGS_DIR = _SCRIPT_DIR / "logs"
    LOG_FILE = LOGS_DIR / "tuxguard.log"
    ERROR_LOG_FILE = LOGS_DIR / "error.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5
    
    # UI Einstellungen
    WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"
    WINDOW_GEOMETRY = "800x600"
    PIN_DIALOG_GEOMETRY = "300x220"
    CAMERA_PERMISSION_DIALOG_GEOMETRY = "400x250"
    APP_ICON_PATH = _SCRIPT_DIR / "tux_256.png"
    
    # Systemtray
    TRAY_ICON_SIZE = (64, 64)
    TRAY_ICON_COLOR = 'blue'
    
    # Dateifilter
    IMAGE_FILE_TYPES = [("Bilder", "*.jpg *.jpeg *.png")]
    LOG_FILE_TYPES = [("Text files", "*.txt"), ("All files", "*.*")]
    
    @classmethod
    def ensure_directories(cls):
        """Stellt sicher, dass alle erforderlichen Verzeichnisse existieren"""
        cls.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def get_database_path(cls):
        """Gibt den vollständigen Pfad zur Datenbank zurück"""
        return cls._SCRIPT_DIR / cls.DATABASE_FILE

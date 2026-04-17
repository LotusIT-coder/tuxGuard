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
    
    # Datenbankeinstellungen
    DATABASE_FILE = "face_recognition.db"
    
    # Sicherheitseinstellungen
    MAX_SESSION_DURATION = 12 * 3600  # 12 Stunden in Sekunden
    MIN_PIN_LENGTH = 6
    PBKDF2_ITERATIONS = 100_000
    
    # Kameraeinstellungen
    CAMERA_DEVICE = "/dev/video0"
    CAMERA_LOCK_FILE = "/tmp/tuxguard_camera.lock"
    CAMERA_RETRY_ATTEMPTS = 3
    CAMERA_RETRY_DELAY = 1  # Sekunden
    
    # Mausüberwachung
    MOUSE_MONITOR_INTERVAL = 5  # Sekunden
    MOUSE_DATA_COLLECTION_DURATION = 10  # Sekunden
    MOUSE_TRAINING_DURATION = 15  # Sekunden für aktives Training
    MOUSE_TRAINING_EPOCHS = 6
    MOUSE_TRAINING_BATCH_SIZE = 64
    MOUSE_MIN_TRAINING_SAMPLES = 80
    MOUSE_VERIFICATION_THRESHOLD = 0.6
    
    # Modell-Pfade
    MODELS_DIR = Path("models")
    MOUSE_PATTERN_MODEL = MODELS_DIR / "mouse_pattern_model.keras"
    MOUSE_PATTERN_NEGATIVES = MODELS_DIR / "mouse_pattern_negatives.npy"
    
    # Adaptives Lernen
    ADAPTIVE_RETRAIN_INTERVAL = 10
    ADAPTIVE_POSITIVE_SAMPLES_MAX = 1000
    
    # Logging
    LOGS_DIR = Path("logs")
    LOG_FILE = LOGS_DIR / "tuxguard.log"
    ERROR_LOG_FILE = LOGS_DIR / "error.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5
    
    # UI Einstellungen
    WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"
    WINDOW_GEOMETRY = "800x600"
    PIN_DIALOG_GEOMETRY = "300x220"
    CAMERA_PERMISSION_DIALOG_GEOMETRY = "400x250"
    
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
        return Path.cwd() / cls.DATABASE_FILE
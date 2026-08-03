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
    DEADMAN_TIMEOUT_SECONDS = 30
    DEADMAN_ACTION = "suspend"

    # Auto-Lock nach fehlender Erkennung (Sekunden)
    SECURITY_LOCK_DELAY_SECONDS = 10
    # Sperrziel: "screen" (nur TuxGuard-Overlay) oder "computer" (zusätzlich loginctl lock-session)
    LOCK_TARGET = "screen"

    # Master-Credential-Datei (vom Installer angelegt, enthält Master-Passwort + Recovery-Hash)
    MASTER_CREDENTIALS_FILE = _SCRIPT_DIR / "master_credentials.json"
    # Laufzeit-Einstellungen (nicht sicherheitskritisch, z. B. Autostart-Präferenzen)
    RUNTIME_SETTINGS_FILE = _SCRIPT_DIR / "runtime_settings.json"
    
    # Kameraeinstellungen
    CAMERA_DEVICE = "/dev/video0"
    CAMERA_LOCK_FILE = "/tmp/tuxguard_camera.lock"
    CAMERA_RETRY_ATTEMPTS = 3
    CAMERA_RETRY_DELAY = 1  # Sekunden
    
    # Modell-Pfade (relativ zum Installationsverzeichnis)
    MODELS_DIR = _SCRIPT_DIR / "models"
    FACE_LANDMARKER_MODEL = MODELS_DIR / "face_landmarker_v2.task"

    # Gesichtsabgleich: maximale Distanz zwischen Kodierungen (kleiner = strenger)
    FACE_MATCH_TOLERANCE = 0.9
    # Mindest-Konfidenz der MediaPipe-Gesichtsdetektion [0..1].
    # Höher = weniger Phantomgesichter, niedriger = empfindlicher.
    FACE_DETECTION_MIN_CONFIDENCE = 0.5
    # Mindestgröße eines Gesichts relativ zur kleineren Bildkante [0..0.5].
    # Filtert winzige Fehldetektionen (z. B. Muster im Hintergrund).
    FACE_MIN_RELATIVE_SIZE = 0.08
    # Anteil der am stärksten abweichenden Gesichtsregionen, der beim Abgleich
    # ignoriert wird [0..0.4]. Macht die Wiedererkennung robust gegen
    # Teilverdeckungen wie Headsets, Brillen oder Mikrofonbügel.
    FACE_MATCH_OCCLUSION_TRIM = 0.25
    
    # ------------------------------------------------------------------
    # Liveness / Anti-Spoofing (verhindert Überlistung per 2D-Foto)
    # ------------------------------------------------------------------
    LIVENESS_ENABLED = True
    # Passive Textur-/Moiré-Analyse: Mindest-Echtheitsscore [0..1]
    LIVENESS_TEXTURE_MIN_SCORE = 0.45
    # Blinzel-Erkennung
    LIVENESS_REQUIRE_BLINK = True
    LIVENESS_BLINK_CLOSE_THRESHOLD = 0.45
    LIVENESS_BLINK_OPEN_THRESHOLD = 0.20
    LIVENESS_BLINK_WINDOW_SECONDS = 8.0
    # Bewegungs-Parallaxe (Tiefe aus Bewegung)
    LIVENESS_REQUIRE_PARALLAX = True
    LIVENESS_PARALLAX_MIN_YAW_RANGE = 8.0
    LIVENESS_PARALLAX_MIN_SLOPE = 0.004
    LIVENESS_MOTION_WINDOW_SECONDS = 6.0
    # 3D-Geometrie-Konsistenz gegen das hinterlegte Referenzmodell
    LIVENESS_GEOMETRY_MAX_RMS = 0.18
    LIVENESS_GEOMETRY_REQUIRED = False
    # Harte Fehlgründe (Textur/Geometrie/Parallaxe) müssen über diese Zeit
    # anhalten, bevor sie als echter Spoof gewertet werden.
    LIVENESS_SPOOF_GRACE_SECONDS = 2.5
    # Kürzlich als "live" bestätigte Nutzer bleiben bei kurzen Aussetzern
    # innerhalb dieses Zeitfensters im Pending-Zustand statt sofort auf Spoof.
    LIVENESS_RECENT_LIVE_TTL_SECONDS = 2.0
    # Aktive Challenge (z. B. "bitte blinzeln / Kopf drehen")
    LIVENESS_ACTIVE_CHALLENGE_ENABLED = True
    LIVENESS_CHALLENGE_TIMEOUT_SECONDS = 12.0
    LIVENESS_CHALLENGE_TURN_YAW_DEGREES = 15.0
    
    # ------------------------------------------------------------------
    # Tippmustererkennung (Keystroke Dynamics) – 2. Faktor der Dauerüberwachung
    # ------------------------------------------------------------------
    KEYSTROKE_DYNAMICS_ENABLED = True
    # Systemweite Erfassung (nur Zeitabstände, nie Zeichen). Fehlt pynput oder
    # die Rechte, degradiert TuxGuard automatisch (kein zweiter Faktor).
    KEYSTROKE_GLOBAL_CAPTURE = True
    # Anschläge für ein vollständiges Referenzprofil (Anlernen, je Nutzer)
    KEYSTROKE_MIN_ENROLLMENT_KEYSTROKES = 200
    # Fenstergröße einer Live-Probe während der Überwachung
    KEYSTROKE_MATCH_WINDOW_KEYSTROKES = 30
    # Obergrenze adaptiv gelernter Anschläge (hält neue Eingaben wirksam)
    KEYSTROKE_MAX_PROFILE_KEYSTROKES = 2000
    # Schwellwert der normierten Distanz (kleiner = strenger)
    KEYSTROKE_MATCH_THRESHOLD = 1.8
    # Konfidenzschwelle für das Anschlagen bei fremdem Tippmuster [0..1].
    # Unterhalb dieses Werts wird ein nicht passendes Muster als Eindringling
    # gewertet; darüber bleibt es zunächst nur ein unscharfer Fehlmatch.
    KEYSTROKE_INTRUDER_CONFIDENCE_THRESHOLD = 0.35
    # Plausibilitätsgrenzen (größere Werte beenden einen Tipplauf)
    KEYSTROKE_MAX_DWELL_MS = 600.0
    KEYSTROKE_MAX_FLIGHT_MS = 1500.0
    # Untergrenze der Streuung im Distanzmaß (verhindert Überstrenge)
    KEYSTROKE_STD_FLOOR_MS = 8.0
    # Profil mit bestätigten Live-Proben nachschärfen (adaptives Lernen)
    KEYSTROKE_ADAPTIVE_LEARNING = True
    # Wie lange eine bestätigte Tippprobe als „präsent" gilt (Sekunden)
    KEYSTROKE_PRESENCE_TTL_SECONDS = 90
    # Wie lange ein fremdes Tippmuster als „Eindringling" nachwirkt (Sekunden)
    KEYSTROKE_INTRUDER_TTL_SECONDS = 30

    # ------------------------------------------------------------------
    # Mehrfaktor-Fusion der Dauerüberwachung (Gesicht + Tippmuster)
    # ------------------------------------------------------------------
    # Wie schnell ein Gesicht ohne neue Erkennung als „weg" gilt (Sekunden)
    FACE_PRESENCE_TTL_SECONDS = 4
    # Fusionsstrategie der beiden Faktoren:
    #   "face_only"      – nur Gesicht entscheidet (Tippmuster nur protokollieren)
    #   "keystroke_only" – nur Tippmuster entscheidet
    #   "any"            – präsent, wenn EIN Faktor erkennt (tolerant)
    #   "all"            – präsent nur, wenn Gesicht UND Tippmuster passen (streng)
    #   "priority"       – Primärfaktor entscheidet, Sekundärfaktor als Rückfall
    PRESENCE_FUSION_MODE = "priority"
    # Primärfaktor für "priority": "face" oder "keystroke"
    PRESENCE_PRIMARY_FACTOR = "face"
    # Reaktion, wenn das Gesicht nicht mehr erkannt wird:
    #   "lock" (Sperrbildschirm) | "warn" (nur warnen) | "ignore" | "deadman"
    PRESENCE_ON_FACE_LOST = "lock"
    # Reaktion bei fremdem Tippmuster (anderer Tipprhythmus):
    PRESENCE_ON_KEYSTROKE_INTRUDER = "lock"
    # Reaktion, wenn das passende Tippmuster ausbleibt (idR neutral lassen):
    PRESENCE_ON_KEYSTROKE_LOST = "ignore"
    
    # Adaptives Lernen
    ADAPTIVE_RETRAIN_INTERVAL = 10
    ADAPTIVE_POSITIVE_SAMPLES_MAX = 1000

    # Emotionsanalyse (intern, ohne sichtbare UI-Anzeige)
    EMOTION_MIN_CONFIDENCE = 0.35
    EMOTION_SMOOTHING_ALPHA = 0.35
    EMOTION_TRACK_MAX_DISTANCE = 90.0
    EMOTION_TRACK_TTL_SECONDS = 1.5

    # ------------------------------------------------------------------
    # Optionaler System-Login (PAM/Display-Manager Integration)
    # ------------------------------------------------------------------
    # Schaltet den optionalen Biometrie-Login-Dienst ein/aus.
    SYSTEM_LOGIN_ENABLED = False
    # Policy-Modus:
    #   face_or_password    -> biometrisch versuchen, sonst Passwort-Fallback
    #   face_and_pin        -> biometrisch + PIN als zweiter Faktor
    #   password_only       -> Biometrie deaktiviert
    SYSTEM_LOGIN_MODE = "face_or_password"
    # Unix-Socket für lokalen Auth-Daemon.
    SYSTEM_LOGIN_SOCKET_PATH = "/run/tuxguard-authd.sock"
    # Standard-Timeout pro Auth-Anfrage (Sekunden).
    SYSTEM_LOGIN_REQUEST_TIMEOUT_SECONDS = 8.0
    # Standard-Schwelle für Face-Matching im System-Login.
    SYSTEM_LOGIN_FACE_TOLERANCE = FACE_MATCH_TOLERANCE
    # Maximalversuche pro Benutzer innerhalb des Fensterintervalls.
    SYSTEM_LOGIN_MAX_ATTEMPTS = 5
    SYSTEM_LOGIN_ATTEMPT_WINDOW_SECONDS = 60
    SYSTEM_LOGIN_LOCKOUT_SECONDS = 120

    # Stufe 2: Dediziertes Emotion-Backend (blendshape oder onnx)
    EMOTION_BACKEND = "blendshape"  # "blendshape" oder "onnx" (ONNX=optional mit Fallback)
    EMOTION_ONNX_MODEL = MODELS_DIR / "emotion_fer_onnx.onnx"  # Optional FER-Modell
    EMOTION_BACKEND_FALLBACK_ENABLED = True  # Fallback zu Blendshape wenn ONNX fehlt

    # Emotionale Risikoerkennung waehrend aktiver Ueberwachung
    EMOTION_ANALYSIS_ENABLED = True
    EMOTION_ALERT_DURATION_SECONDS = 3.0
    EMOTION_ALERT_MIN_CONFIDENCE = 0.35
    
    # Logging
    LOGS_DIR = Path("/var/log/tuxguard")
    LOG_FILE = LOGS_DIR / "tuxguard.log"
    ERROR_LOG_FILE = LOGS_DIR / "error.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5
    USER_RECOGNIZED_LOG_INTERVAL_SECONDS = 5.0
    
    # UI Einstellungen
    WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"
    WINDOW_GEOMETRY = "800x600"
    PIN_DIALOG_GEOMETRY = "300x220"
    CAMERA_PERMISSION_DIALOG_GEOMETRY = "400x250"
    APP_ICON_PATH = _SCRIPT_DIR / "tux_256.png"
    MINIMIZE_BEHAVIOR = "tray"   # "tray" | "normal"
    CLOSE_BEHAVIOR = "ask"       # "ask" | "tray" | "quit"
    AUTOSTART_MONITORING_DEFAULT = False
    
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

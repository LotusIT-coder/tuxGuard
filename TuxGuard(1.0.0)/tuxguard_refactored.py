#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard - Refactored Security Application
Hauptmodul für die TuxGuard Sicherheitsanwendung
"""

import sys
import time
import threading
import tempfile
import os
import json
import logging
import re
import io
import shlex
import subprocess
from pathlib import Path
from typing import Optional, List

import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk
import numpy as np
from PIL import Image, ImageDraw, ImageTk
import pystray

from face_mediapipe import (
    safe_face_enrollment_from_file,
)
from face_liveness import (
    aggregate_geometries,
    combine_geometry_models,
    deserialize_geometry,
    serialize_geometry,
)
import keystroke_dynamics as ksd
import presence

# Lokale Module
from config import Config
from logging_setup import setup_logging
from database import DatabaseManager, SecurityUtils
from camera import CameraManager
from simple_ui import (
    MainUI,
    PasswordDialog,
    LoginDialog,
    FirstRunWizard,
    MasterPasswordSetupDialog,
    KeystrokeEnrollmentDialog,
    show_recovery_code,
)
from auth import MasterAuth, MasterAuthError


class UILogHandler(logging.Handler):
    """Spiegelt Logeinträge thread-sicher in die GUI."""

    def __init__(self, app: "TuxGuardApplication"):
        super().__init__(level=logging.INFO)
        self.app = app

    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
            level = record.levelname if record.levelname in {"INFO", "WARNING", "ERROR"} else "INFO"
            self.app.root.after(0, lambda: self.app._append_persistent_log(message, level))
        except Exception:
            pass

class TuxGuardApplication:
    """Hauptanwendungsklasse für TuxGuard"""
    
    def __init__(self):
        # Logging initialisieren
        self.logger = setup_logging()
        self.logger.info(f"TuxGuard {Config.APP_VERSION} wird gestartet...")
        
        # Verzeichnisse sicherstellen
        Config.ensure_directories()
        
        # Tkinter Root
        self.root = tk.Tk(className=Config.APP_WM_CLASS)
        self.root.withdraw()  # Verstecke zunächst
        self._set_window_icon()
        
        # Komponenten
        self.db_manager = DatabaseManager()
        self.camera_manager = None
        self.ui = None
        self.tray_icon = None
        self.master_auth = MasterAuth()
        
        # Status
        self.monitoring_active = False
        self.session_start = time.time()
        self.ui_log_handler = None
        self.security_mode = Config.SECURITY_MODE
        self.security_lock_delay_seconds = Config.SECURITY_LOCK_DELAY_SECONDS
        self.deadman_timeout_seconds = Config.DEADMAN_TIMEOUT_SECONDS
        self.deadman_action = Config.DEADMAN_ACTION
        self.lock_target = Config.LOCK_TARGET  # "screen" | "computer"
        self.security_lock_active = False
        self.security_lock_reason = ""
        self.security_lock_window = None
        self.security_lock_windows: List[tk.Toplevel] = []
        self.security_lock_status_label = None
        self.security_lock_status_labels: List[tk.Label] = []
        self.security_lock_pin_entries: List[tk.Entry] = []
        self.security_lock_recognized_user: Optional[str] = None
        self.security_lock_unlock_pending = False
        self.force_admin_unlock_required = False
        self.security_lock_camera_status = ""
        self.security_lock_camera_status_level = "INFO"
        self.deadman_triggered = False
        self.last_authorized_seen_at = time.time()
        self.deadman_thread = None
        self.current_user: Optional[str] = None
        self.current_user_is_admin: bool = False
        self.minimize_behavior = Config.MINIMIZE_BEHAVIOR
        self.close_behavior = Config.CLOSE_BEHAVIOR
        self._load_security_runtime_settings()

        # Tippmustererkennung (2. Überwachungsfaktor)
        self.keystroke_monitor = None
        self._keystroke_profiles_cache: List[tuple] = []
        self.last_face_seen_at = 0.0
        self.last_keystroke_match_at = 0.0
        self.last_keystroke_intruder_at = 0.0
        self.keystroke_matched_user: Optional[str] = None
        self.face_presence_ttl = float(getattr(Config, "FACE_PRESENCE_TTL_SECONDS", 4))
        
        # Threads
        self.active_threads = []
        
        try:
            self._initialize_components()
            self._setup_callbacks()
            self._setup_ui_logging()

            # Sicherheits-Gate: Master-Passwort, Erststart-Wizard, Login
            if not self._ensure_master_credentials():
                self.logger.warning("Master-Passwort wurde nicht gesetzt – Anwendung wird beendet.")
                self._quit_application()
                return
            if not self._ensure_initial_admin_user():
                self.logger.warning("Kein initialer Admin angelegt – Anwendung wird beendet.")
                self._quit_application()
                return
            if not self._require_login():
                self.logger.info("Login abgebrochen – Anwendung wird beendet.")
                self._quit_application()
                return

            self.root.deiconify()
            self.logger.info("TuxGuard erfolgreich initialisiert (Benutzer: %s)", self.current_user)
            def _init_autostart_ui():
                autostart_enabled = self._is_autostart_enabled()
                autostart_monitoring = self._load_autostart_monitoring_preference()
                if hasattr(self.ui, 'set_autostart_settings'):
                    self.ui.set_autostart_settings(autostart_enabled, autostart_monitoring)
                elif hasattr(self.ui, 'set_autostart_state'):
                    self.ui.set_autostart_state(autostart_enabled)
                if hasattr(self.ui, 'autostart_preferences_callback'):
                    self.ui.autostart_preferences_callback = self._on_autostart_preferences_changed
                elif hasattr(self.ui, 'autostart_callback'):
                    self.ui.autostart_callback = self._on_autostart_checkbox
                if hasattr(self.ui, 'system_login_callback'):
                    self.ui.system_login_callback = self._on_system_login_preferences_changed

                # Überwachung nur dann automatisch starten, wenn die App
                # tatsächlich aus dem Autostart-Service gestartet wurde.
                if (
                    autostart_enabled
                    and autostart_monitoring
                    and self._is_started_from_autostart_service()
                    and self._has_registered_users()
                ):
                    self._start_monitoring()
            self.root.after(0, _init_autostart_ui)
        except Exception as e:
            self.root.deiconify()
            self.logger.error(f"Fehler bei der Initialisierung: {e}")
            messagebox.showerror("Initialisierungsfehler", f"Fehler beim Starten der Anwendung: {e}")
            sys.exit(1)

    def _set_window_icon(self):
        """Setzt ein Fenster-Icon, damit Dock und Taskleiste die App korrekt zuordnen."""
        try:
            if Config.APP_ICON_PATH.exists():
                self.window_icon = tk.PhotoImage(file=str(Config.APP_ICON_PATH))
                self.root.iconphoto(True, self.window_icon)
        except Exception as e:
            self.logger.warning(f"Fenster-Icon konnte nicht gesetzt werden: {e}")

    # ------------------------------------------------------------------
    # Startup-Gates (Master-Passwort, Erststart-Wizard, Login)
    # ------------------------------------------------------------------

    def _ensure_master_credentials(self) -> bool:
        """Stellt sicher, dass ein Master-Passwort + Recovery-Code existieren.

        Falls der Installer es nicht erledigt hat, wird der Nutzer im GUI
        einmalig dazu aufgefordert. Gibt ``True`` zurück, wenn am Ende
        gültige Credentials vorliegen.
        """
        if self.master_auth.is_initialized():
            self.logger.info("Master-Credentials gefunden: %s", self.master_auth.path)
            return True

        self.logger.warning(
            "Kein Master-Passwort gefunden – Setup wird im GUI nachgeholt."
        )
        self.root.deiconify()
        messagebox.showinfo(
            "Master-Passwort einrichten",
            "TuxGuard hat noch kein Master-Passwort.\n"
            "Bitte legen Sie jetzt eines fest. Sie erhalten anschließend einen "
            "Recovery-Code, der für spätere Passwortänderungen erforderlich ist.",
        )
        dialog = MasterPasswordSetupDialog(self.root)
        password = dialog.show()
        if not password:
            return False
        try:
            recovery = self.master_auth.initialize(password)
        except MasterAuthError as exc:
            messagebox.showerror("Fehler", str(exc))
            return False
        show_recovery_code(self.root, recovery,
                           title="Recovery-Code – sicher aufbewahren!")
        self.root.withdraw()
        return True

    def _ensure_initial_admin_user(self) -> bool:
        """Startet den Erststart-Wizard, falls noch kein Admin existiert."""
        if self.db_manager.has_admin():
            return True
        self.logger.info("Kein Admin-Benutzer vorhanden – Erststart-Wizard wird gestartet.")
        self.root.deiconify()

        wizard = FirstRunWizard(
            self.root,
            capture_face_callback=self._capture_face_for_wizard,
        )
        result = wizard.show()
        if not result:
            return False

        # Erstelle Admin-Benutzer + Gesichtsbilder
        try:
            user_id = self.db_manager.add_user(
                name=result["name"],
                pin=result["pin"],
                password=result["password"],
                is_admin=True,
            )
            file_specs = [(p, p == result.get("captured_image"))
                          for p in result["image_paths"]]
            saved = self._store_face_images_for_user(user_id, result["name"], file_specs)
            self._cleanup_temporary_image_files(file_specs)
            if saved <= 0:
                self.db_manager.delete_user(result["name"])
                messagebox.showerror(
                    "Fehler",
                    "Es konnte kein gültiges Gesichtsbild gespeichert werden. "
                    "Bitte erneut versuchen.")
                return self._ensure_initial_admin_user()
            self._refresh_user_list()
            messagebox.showinfo(
                "Admin angelegt",
                f"Admin-Benutzer '{result['name']}' wurde erstellt "
                f"({saved} Gesichtsbild(er)).",
            )
        except (ValueError, Exception) as exc:
            self.logger.error("Anlegen des Admins fehlgeschlagen: %s", exc)
            messagebox.showerror("Fehler", f"Admin konnte nicht angelegt werden: {exc}")
            return False

        self.root.withdraw()
        return True

    def _capture_face_for_wizard(self) -> Optional[str]:
        """Wird vom Wizard aufgerufen, um eine Webcam-Aufnahme zu erzeugen."""
        if not self.camera_manager or not self.camera_manager.is_available:
            messagebox.showwarning("Kamera nicht verfügbar",
                                   "Die Webcam ist nicht verfügbar.")
            return None
        try:
            return self.camera_manager.capture_image()
        except Exception as exc:
            self.logger.error("Webcam-Aufnahme fehlgeschlagen: %s", exc)
            messagebox.showerror("Fehler", f"Webcam-Aufnahme fehlgeschlagen: {exc}")
            return None

    def _require_login(self) -> bool:
        """Verlangt eine Benutzeranmeldung. Bei Erfolg werden ``current_user``
        und ``current_user_is_admin`` gesetzt."""
        users_meta = self.db_manager.get_users_with_meta()
        users_with_pw = [name for _, name, _, has_pw in users_meta if has_pw]
        if not users_with_pw:
            self.logger.error("Login nicht möglich: kein Benutzer mit Passwort vorhanden.")
            return False

        for _attempt in range(3):
            self.root.deiconify()
            dialog = LoginDialog(self.root, users_with_pw)
            creds = dialog.show()
            self.root.withdraw()
            if not creds:
                return False
            username, password = creds
            if self.db_manager.verify_user_password(username, password):
                self.current_user = username
                # is_admin nachladen
                for _, name, is_admin, _ in users_meta:
                    if name == username:
                        self.current_user_is_admin = is_admin
                        break
                self.logger.info("Benutzer angemeldet: %s (admin=%s)",
                                 username, self.current_user_is_admin)
                return True
            messagebox.showerror("Anmeldung fehlgeschlagen",
                                 "Benutzer oder Passwort falsch.")
        return False

    # ------------------------------------------------------------------
    # Admin-Gate für sensible Aktionen (Tray, Einstellungen)
    # ------------------------------------------------------------------

    def _require_admin_password(self, reason: str = "Diese Aktion benötigt Admin-Rechte.") -> bool:
        """Prompt für ein Admin-Passwort (Master oder zusätzliches Admin-Passwort)."""
        dialog = PasswordDialog(
            self.root,
            title="Admin-Passwort erforderlich",
            reason=reason,
            allow_cancel=True,
        )
        password = dialog.show()
        if password is None:
            return False
        if not self.master_auth.verify_admin_password(password):
            messagebox.showerror("Fehler", "Ungültiges Admin-Passwort.")
            return False
        self.logger.info("Admin-Aktion autorisiert: %s", reason)
        return True
    def _has_registered_users(self):
        try:
            users = self.db_manager.get_all_users()
            return bool(users)
        except Exception as e:
            self.logger.error(f"Fehler beim Prüfen der Benutzerliste: {e}")
            return False
    def _get_systemd_user_service_path(self):
        import os
        return os.path.expanduser('~/.config/systemd/user/tuxguard.service')

    def _load_runtime_settings(self) -> dict:
        path = Path(getattr(Config, "RUNTIME_SETTINGS_FILE", Config._SCRIPT_DIR / "runtime_settings.json"))
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            self.logger.debug("Runtime-Settings konnten nicht gelesen werden: %s", exc)
            return {}

    def _save_runtime_settings(self, updates: dict) -> None:
        path = Path(getattr(Config, "RUNTIME_SETTINGS_FILE", Config._SCRIPT_DIR / "runtime_settings.json"))
        try:
            current = self._load_runtime_settings()
            current.update(updates)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(current, handle, indent=2)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except Exception as exc:
            self.logger.warning("Runtime-Settings konnten nicht gespeichert werden: %s", exc)

    def _load_security_runtime_settings(self) -> None:
        """Übernimmt die zuletzt bestätigten Sicherheitsoptionen beim Start."""
        settings = self._load_runtime_settings()
        mode = settings.get("security_mode", self.security_mode)
        action = settings.get("deadman_action", self.deadman_action)
        timeout = settings.get("deadman_timeout_seconds", self.deadman_timeout_seconds)

        if mode in {"self_unlock", "strict_pin", "deadman"}:
            self.security_mode = mode
        if action in {"suspend", "shutdown"}:
            self.deadman_action = action
        try:
            self.deadman_timeout_seconds = max(10, int(timeout))
        except (TypeError, ValueError):
            pass

    def _load_autostart_monitoring_preference(self) -> bool:
        settings = self._load_runtime_settings()
        default = bool(getattr(Config, "AUTOSTART_MONITORING_DEFAULT", False))
        return bool(settings.get("autostart_monitoring", default))

    @staticmethod
    def _is_started_from_autostart_service() -> bool:
        marker = str(os.environ.get("TUXGUARD_AUTOSTART", "") or "").strip().lower()
        return marker in {"1", "true", "yes"}

    def _is_autostart_enabled(self):
        import os
        service_path = self._get_systemd_user_service_path()
        return os.path.exists(service_path)

    def _on_autostart_checkbox(self, enabled: bool):
        self._on_autostart_preferences_changed(
            bool(enabled),
            self._load_autostart_monitoring_preference(),
        )

    def _on_autostart_preferences_changed(self, enabled: bool, start_monitoring: bool):
        self._save_runtime_settings({"autostart_monitoring": bool(start_monitoring)})
        if enabled:
            self._enable_autostart_service(start_monitoring=bool(start_monitoring))
        else:
            self._disable_autostart_service()
        self.logger.info(
            "Autostart aktualisiert: enabled=%s start_monitoring=%s",
            bool(enabled), bool(start_monitoring),
        )

    def _on_system_login_preferences_changed(
        self,
        enabled: bool,
        mode: str,
        face_tolerance: str,
        max_attempts: str,
        lockout_seconds: str,
    ) -> None:
        try:
            tolerance = float(face_tolerance)
            max_attempts_int = max(1, int(max_attempts))
            lockout_int = max(1, int(lockout_seconds))
        except ValueError:
            self.logger.warning("Ungültige System-Login-Einstellungen ignoriert")
            return

        self._save_runtime_settings({
            "system_login_enabled": bool(enabled),
            "system_login_mode": str(mode),
            "system_login_face_tolerance": tolerance,
            "system_login_max_attempts": max_attempts_int,
            "system_login_lockout_seconds": lockout_int,
        })
        self.logger.info(
            "System-Login-Einstellungen gespeichert: enabled=%s mode=%s tolerance=%.2f max_attempts=%s lockout=%s",
            bool(enabled),
            str(mode),
            tolerance,
            max_attempts_int,
            lockout_int,
        )

    @staticmethod
    def _systemctl_user(*args: str) -> None:
        try:
            subprocess.run(
                ["systemctl", "--user", *args],
                check=False,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _enable_autostart_service(self, start_monitoring: bool):
        import os, getpass
        service_path = self._get_systemd_user_service_path()
        os.makedirs(os.path.dirname(service_path), exist_ok=True)
        script_path = os.path.abspath(__file__)
        python_path = sys.executable or "python3"
        user = getpass.getuser()
        monitor_env = "1" if start_monitoring else "0"
        exec_start = f"{shlex.quote(python_path)} {shlex.quote(script_path)}"
        service_content = (
            "[Unit]\n"
            "Description=TuxGuard Security Service\n"
            "After=graphical-session.target network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "Environment=TUXGUARD_AUTOSTART=1\n"
            f"Environment=TUXGUARD_AUTOSTART_MONITORING={monitor_env}\n"
            f"ExecStart={exec_start}\n"
            "Restart=on-failure\n"
            f"User={user}\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        with open(service_path, 'w') as f:
            f.write(service_content)
        # Enable the service
        self._systemctl_user("daemon-reload")
        self._systemctl_user("enable", "--now", "tuxguard.service")
        self.logger.info("Autostart als Systemdienst aktiviert.")

    def _disable_autostart_service(self):
        import os
        service_path = self._get_systemd_user_service_path()
        if os.path.exists(service_path):
            self._systemctl_user("disable", "--now", "tuxguard.service")
            os.remove(service_path)
            self._systemctl_user("daemon-reload")
            self.logger.info("Autostart als Systemdienst deaktiviert.")
    
    def _initialize_components(self):
        """Initialisiert alle Komponenten"""
        try:
            # Datenbank verbinden
            self.db_manager.connect()
            self.logger.info("Datenbank verbunden")
            
            # Kamera-Manager erstellen
            self.camera_manager = CameraManager(self.root, self.db_manager)
            self.logger.info("Kamera-Manager initialisiert")
            
            # UI erstellen
            self.ui = MainUI(self.root)
            self.logger.info("Benutzeroberfläche initialisiert")
            
            # Status aktualisieren
            self.ui.update_status(
                camera_available=self.camera_manager.is_available
            )
            
            # Kamera-Buttons konfigurieren
            self.ui.configure_camera_buttons(self.camera_manager.is_available)
            
            # Benutzerliste laden
            self._refresh_user_list()
            self.logger.info("Benutzerliste geladen")
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Komponenteninitialisierung: {e}")
            messagebox.showerror("Initialisierungsfehler", 
                               f"Fehler beim Starten der Anwendung: {e}")
            sys.exit(1)
    
    def _setup_callbacks(self):
        """Setzt alle Callback-Funktionen"""
        # UI Callbacks
        self.ui.set_callback('test_camera', self._test_camera)
        self.ui.set_callback('diagnose_camera', self._diagnose_camera)
        self.ui.set_callback('toggle_monitoring', self._toggle_monitoring)
        self.ui.set_callback('add_new_user', self._add_new_user)
        self.ui.set_callback('add_admin_password', self._add_additional_admin_password)
        self.ui.set_callback('security_settings_changed', self._on_security_settings_changed)
        self.ui.set_callback('ui_behavior_changed', self._on_ui_behavior_changed)
        self.ui.set_callback('save_keystroke_settings', self._on_save_keystroke_settings)
        self.ui.set_callback('train_keystrokes_prompt', self._train_keystrokes_prompt)
        
        # Kamera Callbacks
        self.camera_manager.set_callbacks(
            user_recognized=self._on_user_recognized,
            unauthorized_access=self._on_unauthorized_access,
            preview_updated=self._on_camera_preview_updated,
            user_seen=self._on_user_seen,
            emotion_alert=self._on_emotion_alert,
        )
        
        # User List Callbacks
        self.ui.user_list_widget.set_callbacks(
            show_images=self._show_user_images,
            add_images=self._add_images_to_user,
            delete_user=self._delete_user,
            train_keystrokes=self._train_keystrokes
        )
        
        # Window Callback
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.root.bind("<Unmap>", self._on_window_unmap)
        self.ui.set_security_settings(
            self.security_mode,
            self.deadman_timeout_seconds,
            self.deadman_action,
        )
        self.ui.set_ui_behavior(self.minimize_behavior, self.close_behavior)
        self.ui.set_keystroke_settings(self._current_keystroke_settings())

    def _setup_ui_logging(self):
        """Lädt vorhandene Logs in die GUI und spiegelt neue Einträge live hinein."""
        self._load_persistent_logs()

        if self.ui_log_handler is None:
            handler = UILogHandler(self)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "%Y-%m-%d %H:%M:%S",
            ))
            logging.getLogger("TuxGuard").addHandler(handler)
            self.ui_log_handler = handler

    def _load_persistent_logs(self, limit: int = 300):
        """Lädt die letzten Zeilen aus der Logdatei in den GUI-Logtab."""
        try:
            if not Config.LOG_FILE.exists():
                return
            with open(Config.LOG_FILE, "r", encoding="utf-8", errors="replace") as log_file:
                lines = log_file.readlines()[-limit:]
            if hasattr(self.ui, "system_log_widget") and self.ui.system_log_widget:
                self.ui.system_log_widget.set_logs(lines)
        except Exception as e:
            self.logger.error(f"Persistente Logs konnten nicht geladen werden: {e}")

    def _append_persistent_log(self, message: str, level: str):
        """Hängt einen neuen Logeintrag an die GUI an."""
        if hasattr(self.ui, "system_log_widget") and self.ui.system_log_widget:
            self.ui.system_log_widget.add_log(message, level)

    def _on_security_settings_changed(self, mode: str, deadman_timeout: str, deadman_action: str):
        """Übernimmt geänderte Sicherheitsoptionen aus der UI – nur mit Admin-Passwort."""
        # Vor Anwendung Admin-Passwort verlangen
        if not self._require_admin_password(
            "Änderungen am Sicherheitsmodus erfordern das Admin-Passwort."
        ):
            # Werte zurücksetzen
            if self.ui:
                self.ui.set_security_settings(
                    self.security_mode,
                    self.deadman_timeout_seconds,
                    self.deadman_action,
                )
            return

        try:
            timeout = max(10, int(deadman_timeout))
        except (TypeError, ValueError):
            timeout = Config.DEADMAN_TIMEOUT_SECONDS

        if mode not in {"self_unlock", "strict_pin", "deadman"}:
            mode = Config.SECURITY_MODE
        if deadman_action not in {"suspend", "shutdown"}:
            deadman_action = Config.DEADMAN_ACTION

        self.security_mode = mode
        self.deadman_timeout_seconds = timeout
        self.deadman_action = deadman_action
        self._save_runtime_settings({
            "security_mode": self.security_mode,
            "deadman_timeout_seconds": self.deadman_timeout_seconds,
            "deadman_action": self.deadman_action,
        })
        self.logger.info(
            "Sicherheitsmodus aktualisiert: modus=%s timeout=%ss aktion=%s",
            self.security_mode,
            self.deadman_timeout_seconds,
            self.deadman_action,
        )

        if self.security_lock_active:
            self._update_security_lock_status()

    def _on_ui_behavior_changed(self, minimize_behavior: str, close_behavior: str):
        """Übernimmt UI-Verhalten für Minimieren/Schließen (Admin-geschützt)."""
        if minimize_behavior not in {"tray", "normal"}:
            minimize_behavior = Config.MINIMIZE_BEHAVIOR
        if close_behavior not in {"ask", "tray", "quit"}:
            close_behavior = Config.CLOSE_BEHAVIOR

        if not self._require_admin_password(
            "Änderungen am UI-Verhalten erfordern das Admin-Passwort."
        ):
            if self.ui:
                self.ui.set_ui_behavior(self.minimize_behavior, self.close_behavior)
            return

        self.minimize_behavior = minimize_behavior
        self.close_behavior = close_behavior
        self.logger.info(
            "UI-Verhalten aktualisiert: minimieren=%s schliessen=%s",
            self.minimize_behavior,
            self.close_behavior,
        )

    def _add_additional_admin_password(self):
        """Fügt ein weiteres Admin-Passwort hinzu (nur mit primärem Admin-Passwort)."""
        primary_dialog = PasswordDialog(
            self.root,
            title="Primäres Admin-Passwort",
            reason="Bitte primäres Admin-Passwort eingeben, um ein weiteres Admin-Passwort anzulegen.",
            allow_cancel=True,
        )
        primary_password = primary_dialog.show()
        if not primary_password:
            return
        if not self.master_auth.verify(primary_password):
            messagebox.showerror("Fehler", "Primäres Admin-Passwort ist falsch.")
            return

        new_dialog = PasswordDialog(
            self.root,
            title="Neues Admin-Passwort",
            reason=f"Neues Admin-Passwort (mind. {Config.MIN_PASSWORD_LENGTH} Zeichen):",
            allow_cancel=True,
        )
        new_password = new_dialog.show()
        if not new_password:
            return

        confirm_dialog = PasswordDialog(
            self.root,
            title="Admin-Passwort bestätigen",
            reason="Bitte neues Admin-Passwort zur Bestätigung erneut eingeben.",
            allow_cancel=True,
        )
        confirm_password = confirm_dialog.show()
        if not confirm_password:
            return
        if new_password != confirm_password:
            messagebox.showerror("Fehler", "Passwörter stimmen nicht überein.")
            return

        try:
            total = self.master_auth.add_admin_password(primary_password, new_password)
            messagebox.showinfo(
                "Erfolg",
                f"Zusätzliches Admin-Passwort gespeichert. Insgesamt hinterlegte Admin-Passwörter: {total}",
            )
            self.logger.info("Zusätzliches Admin-Passwort angelegt")
        except MasterAuthError as exc:
            messagebox.showerror("Fehler", str(exc))

    def _on_window_unmap(self, _event=None):
        """Reagiert auf Minimieren des Hauptfensters."""
        try:
            if self.tray_icon is not None:
                return
            if self.root.state() == "iconic" and self.minimize_behavior == "tray":
                self.root.after(100, self._minimize_to_tray)
        except Exception:
            pass

    def _deadman_monitor_loop(self):
        """Überwacht Sperr- und Totmannschalter-Timeouts während der Überwachung."""
        while self.monitoring_active:
            time.sleep(1)
            now = time.time()

            # Fusion aus Gesichts- und Tippmustererkennung (falls aktiv).
            fusion_loss_action = None
            fusion_loss_reason = ""
            if self._fusion_active():
                face_present = (now - self.last_face_seen_at) <= self.face_presence_ttl
                ks_state = self._keystroke_state(now)
                decision = presence.evaluate_presence(
                    face_present, ks_state, self._presence_config())
                if decision.keep_alive:
                    self.last_authorized_seen_at = now
                    self.deadman_triggered = False
                elif decision.immediate_action:
                    reason = decision.reason or "Präsenzfaktor verloren"
                    self.root.after(0, lambda a=decision.immediate_action, r=reason:
                                    self._apply_presence_action(a, r))
                    continue
                else:
                    # Passiver Verlust: konfigurierte Aktion erst nach Karenzzeit.
                    fusion_loss_action = (
                        self._presence_config().on_keystroke_lost
                        if decision.lost_factor == presence.FACTOR_KEYSTROKE
                        else self._presence_config().on_face_lost
                    )
                    fusion_loss_reason = decision.reason or "Präsenzfaktor verloren"

            absence_seconds = now - self.last_authorized_seen_at

            if self.security_mode == "deadman":
                if not self.deadman_triggered and absence_seconds >= self.deadman_timeout_seconds:
                    self.deadman_triggered = True
                    self.root.after(0, self._execute_deadman_action)
                continue

            if not self.security_lock_active and absence_seconds >= self.security_lock_delay_seconds:
                if fusion_loss_action is not None:
                    self.root.after(0, lambda a=fusion_loss_action, r=fusion_loss_reason:
                                    self._apply_presence_action(a, r))
                else:
                    self.root.after(0, lambda: self._activate_security_lock(
                        f"Kein legitimer Nutzer seit {self.security_lock_delay_seconds} Sekunden erkannt"
                    ))

    def _execute_deadman_action(self):
        """Führt die konfigurierte Totmannschalter-Aktion aus."""
        import subprocess as sp

        action_label = "Bereitschaftsmodus" if self.deadman_action == "suspend" else "Herunterfahren"
        self.ui.add_security_log(f"Totmannschalter ausgelöst: {action_label}", "WARNING")
        self.logger.warning("Totmannschalter ausgelöst: %s", action_label)

        try:
            if self.deadman_action == "shutdown":
                sp.run(["systemctl", "poweroff"], check=False)
            else:
                sp.run(["systemctl", "suspend"], check=False)
        except Exception as exc:
            self.logger.error("Totmannschalter-Aktion fehlgeschlagen: %s", exc)

    def _activate_security_lock(self, reason: str, force_admin_password: bool = False):
        """Zeigt den TuxGuard-Sperrbildschirm an, ohne die Kameraüberwachung zu stoppen.

        - Nach 10s ohne legitimen Nutzer wird die Sperre aktiviert.
        - Bei Tasten- oder Mausereignis erscheint ein Passwort-Dialog.
        - Korrektes Passwort hebt die Sperre auf; die Überwachung läuft nahtlos weiter.
        - Optional kann zusätzlich der gesamte Rechner gesperrt werden
          (Config.LOCK_TARGET == "computer").
        """
        if self.security_lock_active:
            self.security_lock_reason = reason
            if force_admin_password:
                self.force_admin_unlock_required = True
            self._update_security_lock_status()
            return

        self.security_lock_active = True
        self.security_lock_reason = reason
        self.security_lock_unlock_pending = False
        self.force_admin_unlock_required = force_admin_password
        self.security_lock_camera_status = ""
        self.security_lock_camera_status_level = "INFO"
        self.security_lock_pin_entries = []
        self.security_lock_recognized_user = None
        self.logger.warning("Sperrbildschirm aktiviert: %s", reason)

        camera_manager = getattr(self, "camera_manager", None)
        reset_recognition_state = getattr(camera_manager, "reset_recognition_state", None)
        if callable(reset_recognition_state):
            reset_recognition_state(reset_liveness=True)

        # Optional: Computer-Session sperren
        if self.lock_target == "computer":
            self._lock_system_session()

        self.security_lock_windows = []
        self.security_lock_status_labels = []
        for index, geometry in enumerate(self._get_security_lock_geometries()):
            window, status_label = self._create_security_lock_window(geometry, reason)
            self.security_lock_windows.append(window)
            self.security_lock_status_labels.append(status_label)
            if index == 0:
                self.security_lock_window = window
                self.security_lock_status_label = status_label

        if not self.security_lock_windows:
            window, status_label = self._create_security_lock_window((0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()), reason)
            self.security_lock_windows = [window]
            self.security_lock_status_labels = [status_label]
            self.security_lock_window = window
            self.security_lock_status_label = status_label

        # Bei erzwungenem Admin-Entsperren (z.B. kein Benutzer vorhanden)
        # ist nur der Admin-Passwort-Dialog erlaubt.
        if self.force_admin_unlock_required:
            for window in self.security_lock_windows:
                for sequence in ("<Key>", "<Button-1>", "<Button-2>", "<Button-3>"):
                    window.bind(sequence, lambda _e: self._prompt_lock_unlock())
        # Bind: in strict_pin löst jede Taste/Maustaste den PIN-Prompt aus.
        # In self_unlock erfolgt die Entsperrung automatisch durch Gesichtserkennung.
        elif self.security_mode == "strict_pin":
            def _trigger_unlock(_event=None):
                self._focus_security_lock_pin_entry()

            for window in self.security_lock_windows:
                for sequence in ("<Key>", "<Button-1>", "<Button-2>", "<Button-3>"):
                    window.bind(sequence, _trigger_unlock)

        self._update_security_lock_status()

    def _security_lock_heading(self) -> str:
        """Liefert eine zum aktiven Entsperrmodus passende Überschrift."""
        if self.force_admin_unlock_required:
            return "Admin-Entsperrung erforderlich"
        if self.security_mode == "strict_pin":
            return "PIN-Entsperrung aktiv"
        if self.security_mode == "self_unlock":
            return "Gesichtsentsperrung aktiv"
        return "Totmannschalter aktiv"

    def _security_lock_liveness_hint(self) -> str:
        if not Config.LIVENESS_ENABLED:
            return "Kamera: Gesichtserkennung ohne Lebendigkeitsprüfung."

        checks = []
        if Config.LIVENESS_REQUIRE_BLINK:
            checks.append("blinzeln")
        if Config.LIVENESS_REQUIRE_PARALLAX:
            checks.append("den Kopf leicht bewegen")
        if Config.LIVENESS_ACTIVE_CHALLENGE_ENABLED:
            checks.append("eine angezeigte Kamera-Challenge erfüllen")
        if not checks:
            return "Kamera: Lebendigkeitsprüfung aktiv."
        return "Kamera: Bitte " + " und ".join(checks) + "."

    def _security_lock_target_hint(self) -> str:
        if self.lock_target == "computer":
            return (
                "Sperrziel: System-Sitzung. Wenn der Desktop-Sperrbildschirm sichtbar ist, "
                "verwaltet er Tastatur, Maus und Entsperrung selbst. Die TuxGuard-PIN und "
                "Gesichtserkennung funktionieren nur auf diesem TuxGuard-Overlay."
            )
        return "Sperrziel: TuxGuard-Overlay. PIN- und Kameraentsperrung bleiben aktiv."

    def _security_lock_interaction_hint(self) -> str:
        if self.force_admin_unlock_required:
            return "Klicken Sie auf den Knopf oder drücken Sie eine Taste für das Admin-Passwort."
        if self.security_mode == "strict_pin":
            return "Geben Sie die PIN direkt im Sperrbildschirm ein und bestätigen Sie sie."
        if self.security_mode == "self_unlock":
            return "Die Entsperrung erfolgt ausschließlich über eine bestätigte Gesichtserkennung."
        return "Der Totmannschalter führt die konfigurierte Schutzaktion aus."

    def _security_lock_action(self):
        if self.force_admin_unlock_required:
            return "Admin-Passwort eingeben", self._prompt_lock_unlock
        return None, None

    def _get_security_lock_geometries(self):
        """Ermittelt die Geometrien aller sichtbaren Bildschirme.

        Unter Linux wird bevorzugt xrandr genutzt, damit das Overlay auf allen
        angeschlossenen Displays erscheint. Fallback ist der bisherige
        Einzeldisplay-Modus.
        """
        import shutil
        import subprocess as sp

        geometries = []
        if os.environ.get("DISPLAY") and shutil.which("xrandr"):
            try:
                result = sp.run(["xrandr", "--query"], capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    pattern = re.compile(
                        r"^(?P<name>\S+)\s+connected(?:\s+primary)?\s+(?P<width>\d+)x(?P<height>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
                    )
                    for line in result.stdout.splitlines():
                        match = pattern.match(line)
                        if match:
                            geometries.append(
                                (
                                    int(match.group("x")),
                                    int(match.group("y")),
                                    int(match.group("width")),
                                    int(match.group("height")),
                                )
                            )
            except Exception as exc:
                self.logger.debug("xrandr-Monitorerkennung fehlgeschlagen: %s", exc)

        if not geometries:
            geometries.append((0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()))

        return geometries

    def _create_security_lock_window(self, geometry, reason: str):
        """Erstellt ein Overlay-Fenster für einen Bildschirm."""
        x_pos, y_pos, width, height = geometry
        window = tk.Toplevel(self.root)
        window.title("TuxGuard Sicherheitsmodus")
        window.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
        try:
            window.overrideredirect(True)
        except Exception:
            pass
        window.attributes("-topmost", True)
        window.configure(bg="black")
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        window.bind("<Escape>", lambda _e: None)
        window.focus_force()

        content = tk.Frame(window, bg="black")
        content.pack(expand=True)

        tk.Label(
            content,
            text=f"🔒 {self._security_lock_heading()}",
            font=("Arial", 24, "bold"),
            fg="white",
            bg="black",
        ).pack(pady=(0, 18))
        tk.Label(
            content,
            text=reason,
            font=("Arial", 15),
            fg="#ffb3b3",
            bg="black",
        ).pack(pady=(0, 14))
        tk.Label(
            content,
            text=self._security_lock_interaction_hint(),
            font=("Arial", 12),
            fg="#cfe8ff",
            bg="black",
            wraplength=max(360, width - 80),
            justify=tk.CENTER,
        ).pack(pady=(0, 14))

        action_label, action_callback = self._security_lock_action()
        if action_label and action_callback:
            tk.Button(
                content,
                text=action_label,
                command=action_callback,
                bg="#2e8b57",
                fg="white",
                activebackground="#3da66d",
                activeforeground="white",
                font=("Arial", 13, "bold"),
                padx=20,
                pady=8,
                bd=0,
            ).pack(pady=(0, 20))

        if self.security_mode == "strict_pin" and not self.force_admin_unlock_required:
            pin_frame = tk.Frame(content, bg="black")
            pin_frame.pack(fill=tk.X, padx=28, pady=(0, 18))
            tk.Label(
                pin_frame,
                text="PIN",
                font=("Arial", 12, "bold"),
                fg="white",
                bg="black",
            ).pack(anchor="w", pady=(0, 5))
            pin_entry = tk.Entry(
                pin_frame,
                show="●",
                font=("Arial", 16),
                justify="center",
                bg="#ffffff",
                fg="#111111",
                insertbackground="#111111",
                bd=2,
            )
            pin_entry.pack(fill=tk.X, pady=(0, 8))
            pin_entry.bind("<Return>", lambda _event, entry=pin_entry: self._submit_security_lock_pin(entry))
            tk.Button(
                pin_frame,
                text="Entsperren",
                command=lambda entry=pin_entry: self._submit_security_lock_pin(entry),
                bg="#2e8b57",
                fg="white",
                activebackground="#3da66d",
                activeforeground="white",
                font=("Arial", 12, "bold"),
                padx=18,
                pady=7,
                bd=0,
            ).pack()
            self.security_lock_pin_entries.append(pin_entry)

        status_label = tk.Label(
            content,
            font=("Arial", 13),
            fg="#cfe8ff",
            bg="black",
            justify=tk.CENTER,
        )
        status_label.pack()

        window.grab_set()
        return window, status_label

    def _lock_system_session(self):
        """Sperrt zusätzlich die Systemsitzung über loginctl/xdg-screensaver."""
        import shutil
        import subprocess as sp
        try:
            if shutil.which("loginctl"):
                sp.Popen(["loginctl", "lock-session"])
                return
            if shutil.which("xdg-screensaver"):
                sp.Popen(["xdg-screensaver", "lock"])
                return
            self.logger.warning("Kein Tool zum Sperren der Sitzung gefunden (loginctl/xdg-screensaver)")
        except Exception as exc:
            self.logger.error("System-Lock fehlgeschlagen: %s", exc)

    def _security_lock_dialog_parent(self):
        """Liefert das Sperr-Overlay, das aktuell die Eingabe besitzt."""
        try:
            active_grab = self.root.grab_current()
        except (AttributeError, tk.TclError):
            active_grab = None

        if active_grab in getattr(self, "security_lock_windows", []):
            return active_grab
        return getattr(self, "security_lock_window", None) or self.root

    def _prompt_lock_unlock(self):
        """Zeigt den Admin-Passwort-Dialog zur Aufhebung der TuxGuard-Sperre."""
        if not self.security_lock_active or self.security_lock_unlock_pending:
            return
        self.security_lock_unlock_pending = True
        try:
            dialog = PasswordDialog(
                self._security_lock_dialog_parent(),
                title="TuxGuard – Bildschirm entsperren",
                reason="Bitte geben Sie ein gültiges Admin-Passwort ein.",
                allow_cancel=False,
            )
            try:
                password = dialog.show()
            except tk.TclError as exc:
                self.logger.error("Admin-Passwort-Dialog konnte nicht geöffnet werden: %s", exc)
                return
            if not password:
                return
            if not self.master_auth.verify_admin_password(password):
                messagebox.showerror("Falsches Passwort",
                                     "Das eingegebene Passwort ist ungültig.")
                return
            self.last_authorized_seen_at = time.time()
            self.deadman_triggered = False
            self._release_security_lock("Admin")
        finally:
            self.security_lock_unlock_pending = False

    def _update_security_lock_status(self):
        """Aktualisiert den Hinweistext des Sperrbildschirms."""
        status_labels = getattr(self, "security_lock_status_labels", [])
        if not status_labels:
            return

        if self.security_mode == "deadman":
            remaining = max(0, self.deadman_timeout_seconds - int(time.time() - self.last_authorized_seen_at))
            action = "Bereitschaft" if self.deadman_action == "suspend" else "Herunterfahren"
            text = (
                "Totmannschalter aktiv.\n"
                f"Wenn kein legitimer Nutzer erkannt wird: {action} in {remaining}s."
            )
        elif self.force_admin_unlock_required:
            text = (
                "Admin-Entsperrung erforderlich.\n"
                "Keine gültigen Benutzerdaten verfügbar."
            )
        elif self.security_mode == "self_unlock":
            text = (
                "Gesichtsentsperrung aktiv.\n"
                "Die Sperre wird nach einer bestätigten Erkennung automatisch aufgehoben.\n"
                f"{self._security_lock_liveness_hint()}"
            )
        else:  # strict_pin
            text = (
                "PIN-Entsperrung aktiv.\n"
                "Eine bestätigte Gesichtserkennung öffnet die PIN-Abfrage für diesen Nutzer.\n"
                f"{self._security_lock_liveness_hint()}"
            )
        camera_status = str(getattr(self, "security_lock_camera_status", "") or "").strip()
        if camera_status:
            text = f"{text}\nKamera: {camera_status}"
        text = f"{text}\n{self._security_lock_interaction_hint()}\n{self._security_lock_target_hint()}"
        level_colors = {
            "INFO": "#cfe8ff",
            "SUCCESS": "#98e698",
            "WARN": "#ffd27f",
            "WARNING": "#ffd27f",
            "ERROR": "#ffb3b3",
        }
        color = level_colors.get(
            str(getattr(self, "security_lock_camera_status_level", "INFO")).upper(),
            "#cfe8ff",
        )
        for status_label in status_labels:
            status_label.config(text=text, fg=color)

    def _release_security_lock(self, user_name: Optional[str] = None):
        """Hebt den Sperrbildschirm wieder auf."""
        for window in self.security_lock_windows or ([self.security_lock_window] if self.security_lock_window is not None else []):
            try:
                window.grab_release()
            except Exception:
                pass
            try:
                window.destroy()
            except Exception:
                pass
        self.security_lock_window = None
        self.security_lock_windows = []
        self.security_lock_status_label = None
        self.security_lock_status_labels = []
        self.security_lock_pin_entries = []
        self.security_lock_recognized_user = None
        self.security_lock_active = False
        self.security_lock_reason = ""
        self.security_lock_unlock_pending = False
        self.force_admin_unlock_required = False
        self.security_lock_camera_status = ""
        self.security_lock_camera_status_level = "INFO"

        # Falls die Kamera während der Sperrphase freigegeben/gestoppt wurde,
        # wird die aktive Überwachung nach Entsperren sofort wieder angehoben.
        if self.monitoring_active and self.camera_manager and self.camera_manager.is_available:
            if not self.camera_manager.is_active:
                try:
                    if self.camera_manager.start():
                        self.ui.add_security_log("Kameraüberwachung nach Entsperren fortgesetzt", "SUCCESS")
                        self.logger.info("Kameraüberwachung nach Entsperren fortgesetzt")
                    else:
                        self.ui.add_security_log("Kamera konnte nach Entsperren nicht gestartet werden", "WARNING")
                        self.logger.warning("Kamera konnte nach Entsperren nicht gestartet werden")
                except Exception as exc:
                    self.logger.error("Neustart der Kamera nach Entsperren fehlgeschlagen: %s", exc)

        if user_name:
            self.ui.add_security_log(f"Sperrbildschirm aufgehoben: {user_name}", "SUCCESS")
            self.logger.info("Sperrbildschirm aufgehoben durch legitimen Nutzer: %s", user_name)

    def _focus_security_lock_pin_entry(self):
        """Aktiviert das PIN-Feld des Sperr-Overlays ohne ein weiteres Fenster."""
        entries = getattr(self, "security_lock_pin_entries", [])
        if not entries:
            return
        try:
            active_window = self._security_lock_dialog_parent()
            for entry in entries:
                if entry.winfo_toplevel() is active_window:
                    entry.focus_set()
                    return
            entries[0].focus_set()
        except tk.TclError:
            pass

    def _prompt_strict_unlock(self, user_name: Optional[str]):
        """Verknüpft eine bestätigte Gesichtserkennung mit dem PIN-Feld."""
        if not self.security_lock_active:
            return
        self.security_lock_recognized_user = user_name
        if user_name:
            self.security_lock_camera_status = (
                f"Legitimer Nutzer erkannt: {user_name}. PIN eingeben."
            )
            self.security_lock_camera_status_level = "SUCCESS"
            self._update_security_lock_status()
        self._focus_security_lock_pin_entry()

    def _submit_security_lock_pin(self, pin_entry):
        """Prüft die direkt im Sperrbildschirm eingegebene PIN."""
        if not self.security_lock_active:
            return False
        pin = pin_entry.get()
        if not pin:
            self.security_lock_camera_status = "Bitte eine PIN eingeben."
            self.security_lock_camera_status_level = "WARN"
            self._update_security_lock_status()
            self._focus_security_lock_pin_entry()
            return False

        user_name = getattr(self, "security_lock_recognized_user", None)
        if user_name:
            pin_valid = self.db_manager.verify_user_pin_for_user(user_name, pin)
        else:
            pin_valid = self.db_manager.verify_user_pin(pin)

        try:
            pin_entry.delete(0, tk.END)
        except tk.TclError:
            pass

        if pin_valid:
            self.last_authorized_seen_at = time.time()
            self.deadman_triggered = False
            self._release_security_lock(user_name)
            return True

        self.security_lock_camera_status = "PIN ungültig. Bitte erneut eingeben."
        self.security_lock_camera_status_level = "ERROR"
        self.ui.add_security_log("PIN für Strict-Mode war falsch", "ERROR")
        self.logger.warning("Strict-Mode-Entsperrung mit falscher PIN")
        self._update_security_lock_status()
        self._focus_security_lock_pin_entry()
        return False

    def _schedule_self_unlock(self, user_name: str):
        """Plant die Kamera-Entsperrung im Tk-Hauptthread ein."""
        if (
            self.security_lock_active
            and self.security_mode == "self_unlock"
            and not self.force_admin_unlock_required
            and not self.security_lock_unlock_pending
        ):
            self.security_lock_unlock_pending = True
            self.root.after(0, lambda u=user_name: self._auto_release_self_unlock(u))

    def _auto_release_self_unlock(self, user_name: str):
        """Hebt im self_unlock-Modus die Sperre automatisch auf, sobald
        ein legitimer Nutzer erkannt wird – ohne weitere Eingabe."""
        try:
            if not self.security_lock_active or self.security_mode != "self_unlock":
                return
            self.logger.info("Sperre per Gesichtserkennung aufgehoben (self_unlock): %s", user_name)
            self._release_security_lock(user_name)
        finally:
            self.security_lock_unlock_pending = False
    
    # ------------------------------------------------------------------
    # Tippmustererkennung (Keystroke Dynamics) – 2. Faktor der Überwachung
    # ------------------------------------------------------------------

    def _keystroke_config(self) -> "ksd.KeystrokeConfig":
        """Liefert die aktuelle Keystroke-Konfiguration aus Config."""
        return ksd.KeystrokeConfig.from_app_config(Config)

    def _presence_config(self) -> "presence.PresenceConfig":
        """Liefert die aktuelle Fusions-/Reaktionskonfiguration aus Config."""
        return presence.PresenceConfig.from_app_config(Config)

    def _fusion_active(self) -> bool:
        """True, wenn das Tippmuster aktiv in die Präsenzbewertung eingeht."""
        cfg = self._keystroke_config()
        return (
            cfg.enabled
            and self.keystroke_monitor is not None
            and self.keystroke_monitor.running
            and bool(self._keystroke_profiles_cache)
            and self._presence_config().fusion_mode != presence.FUSION_FACE_ONLY
        )

    def _load_keystroke_profiles(self) -> None:
        """Lädt alle Tippmuster-Profile in den Cache (nur Hauptthread/DB)."""
        cache = []
        try:
            for _uid, name, blob in self.db_manager.get_all_keystroke_profiles():
                profile = ksd.deserialize_profile(blob)
                if profile is not None:
                    cache.append((name, profile))
        except Exception as exc:
            self.logger.error("Tippmuster-Profile konnten nicht geladen werden: %s", exc)
        self._keystroke_profiles_cache = cache

    def _start_keystroke_monitor(self) -> None:
        """Startet den systemweiten Tippmuster-Monitor (falls aktiviert)."""
        cfg = self._keystroke_config()
        if not cfg.enabled:
            return
        self._load_keystroke_profiles()
        if not self._keystroke_profiles_cache:
            self.ui.add_security_log(
                "Tippmuster-Überwachung inaktiv: keine Referenzmuster angelernt", "WARNING")
            return
        try:
            self.keystroke_monitor = ksd.KeystrokeMonitor(
                cfg, self._on_keystroke_sample, self.logger)
            if self.keystroke_monitor.start():
                self.ui.add_security_log("Tippmuster-Überwachung aktiv (2. Faktor)")
            else:
                self.ui.add_security_log(
                    "Tippmuster-Überwachung nicht verfügbar (pynput/Rechte fehlen)", "WARNING")
        except Exception as exc:
            self.logger.error("Tippmuster-Monitor-Start fehlgeschlagen: %s", exc)
            self.keystroke_monitor = None

    def _stop_keystroke_monitor(self) -> None:
        if self.keystroke_monitor is not None:
            try:
                self.keystroke_monitor.stop()
            except Exception:
                pass
            self.keystroke_monitor = None

    def _match_keystroke_sample(self, sample) -> tuple:
        """Vergleicht eine Live-Probe mit allen Referenzmustern (reine Funktion).

        Bevorzugt das Profil des aktuell per Gesicht erkannten Nutzers; sonst
        wird der beste Treffer über alle Nutzer gewählt. Rückgabe:
        (user_name|None, distance).
        """
        cfg = self._keystroke_config()
        cache = list(self._keystroke_profiles_cache)
        if not cache:
            return None, float("inf")

        # Vorrang: zuletzt per Gesicht erkannter Nutzer.
        ordered = cache
        face_user = self.current_user
        if face_user:
            ordered = sorted(cache, key=lambda e: 0 if e[0] == face_user else 1)

        best_user = None
        best_distance = float("inf")
        for name, profile in ordered:
            distance = ksd.match_distance(profile, sample, cfg.std_floor_ms)
            if distance < best_distance:
                best_distance = distance
                best_user = name
        if best_distance <= cfg.match_threshold:
            return best_user, best_distance
        return None, best_distance

    def _on_keystroke_sample(self, sample) -> None:
        """Callback des Monitors (pynput-Thread): nur In-Memory-Arbeit.

        DB-/UI-Operationen werden auf den Tk-Hauptthread umgeleitet.
        """
        try:
            matched_user, distance = self._match_keystroke_sample(sample)
            now = time.time()
            cfg = self._keystroke_config()
            confidence = ksd.match_confidence(distance, cfg.match_threshold)
            if matched_user:
                self.last_keystroke_match_at = now
                self.keystroke_matched_user = matched_user
                self.root.after(0, lambda u=matched_user, d=distance, s=sample:
                                self._handle_keystroke_match(u, d, s))
            else:
                intruder_threshold = float(getattr(
                    Config, "KEYSTROKE_INTRUDER_CONFIDENCE_THRESHOLD", 0.35
                ))
                if confidence <= intruder_threshold:
                    self.last_keystroke_intruder_at = now
                    self.root.after(0, lambda d=distance, c=confidence:
                                    self._handle_keystroke_intruder(d, c))
        except Exception as exc:
            self.logger.debug("Tippmuster-Auswertung fehlgeschlagen: %s", exc)

    def _handle_keystroke_match(self, user_name, distance, sample) -> None:
        """Hauptthread: bestätigtes Tippmuster protokollieren + adaptiv lernen."""
        cfg = self._keystroke_config()
        confidence = ksd.match_confidence(distance, cfg.match_threshold)
        self.logger.info(
            "Tippmuster bestätigt: %s (Distanz=%.2f, Konfidenz=%.0f%%)",
            user_name, distance, confidence * 100)
        if cfg.adaptive_learning:
            self._apply_keystroke_adaptive(user_name, sample)

    def _handle_keystroke_intruder(self, distance, confidence: float) -> None:
        """Hauptthread: fremdes Tippmuster protokollieren."""
        self.ui.add_security_log(
            f"Fremdes Tippmuster erkannt (Distanz {distance:.2f}, Konfidenz {confidence * 100:.0f}%)",
            "WARNING",
        )
        self.logger.warning(
            "Fremdes Tippmuster erkannt (Distanz=%.2f, Konfidenz=%.0f%%)",
            distance, confidence * 100,
        )

    def _apply_keystroke_adaptive(self, user_name, sample) -> None:
        """Verfeinert das Profil eines Nutzers mit einer bestätigten Probe."""
        try:
            user_id = self.db_manager.get_user_id(user_name)
            if user_id is None:
                return
            blob = self.db_manager.get_keystroke_profile(user_id)
            profile = ksd.deserialize_profile(blob)
            if profile is None:
                return
            cfg = self._keystroke_config()
            updated = ksd.update_profile(profile, sample, cfg.max_profile_keystrokes)
            self.db_manager.upsert_keystroke_profile(
                user_id,
                ksd.serialize_profile(updated),
                int(updated.get("n_keystrokes", 0)),
                0,
            )
            # Cache aktualisieren.
            self._keystroke_profiles_cache = [
                (name, updated if name == user_name else prof)
                for name, prof in self._keystroke_profiles_cache
            ]
        except Exception as exc:
            self.logger.debug("Adaptives Tippmuster-Update fehlgeschlagen: %s", exc)

    def _keystroke_state(self, now: float) -> str:
        """Liefert den aktuellen Tippmuster-Faktorzustand für die Fusion."""
        cfg = self._keystroke_config()
        if (now - self.last_keystroke_intruder_at) <= cfg.intruder_ttl_seconds:
            return presence.KS_INTRUDER
        if (now - self.last_keystroke_match_at) <= cfg.presence_ttl_seconds:
            return presence.KS_MATCH
        return presence.KS_IDLE

    def _apply_presence_action(self, action: str, reason: str) -> None:
        """Führt die konfigurierte Reaktion auf einen Faktor-Verlust aus."""
        if action == presence.ACTION_IGNORE:
            return
        if action == presence.ACTION_WARN:
            self.ui.add_security_log(f"Warnung: {reason}", "WARNING")
            return
        if action == presence.ACTION_DEADMAN:
            if not self.deadman_triggered:
                self.deadman_triggered = True
                self._execute_deadman_action()
            return
        # ACTION_LOCK (Standard)
        if not self.security_lock_active:
            self._activate_security_lock(reason)

    def _enroll_keystrokes(self, user_id: int, user_name: str) -> bool:
        """Bietet direkt nach der Benutzeranlage das Tippmuster-Training an."""
        cfg = self._keystroke_config()
        if not cfg.enabled:
            return False
        if not messagebox.askyesno(
            "Tippmuster trainieren",
            "Möchten Sie jetzt das Tippmuster als zweiten Überwachungsfaktor anlernen?\n"
            "Dazu tippen Sie kurz natürlichen Text.",
        ):
            return False
        return self._run_keystroke_enrollment(user_id, user_name)

    def _train_keystrokes(self, user_name: str) -> None:
        """Kontextmenü-Aktion: Tippmuster eines bestehenden Nutzers anlernen."""
        user_id = self.db_manager.get_user_id(user_name)
        if user_id is None:
            messagebox.showerror("Fehler", f"Benutzer '{user_name}' nicht gefunden.")
            return
        self._run_keystroke_enrollment(user_id, user_name)

    def _run_keystroke_enrollment(self, user_id: int, user_name: str) -> bool:
        """Sammelt Freitext-Anschläge und speichert das Referenzprofil."""
        cfg = self._keystroke_config()
        try:
            dialog = KeystrokeEnrollmentDialog(
                self.root, user_name, cfg.min_enrollment_keystrokes,
                max_dwell_ms=cfg.max_dwell_ms, max_flight_ms=cfg.max_flight_ms)
            samples = dialog.show()
            if not samples:
                self.ui.add_security_log(
                    f"Tippmuster-Training für {user_name} abgebrochen", "WARNING")
                return False
            profile = ksd.build_profile(samples)
            if profile is None:
                messagebox.showerror("Fehler", "Zu wenige Anschläge für ein Profil.")
                return False
            self.db_manager.upsert_keystroke_profile(
                user_id,
                ksd.serialize_profile(profile),
                int(profile.get("n_keystrokes", 0)),
                0,
            )
            self._load_keystroke_profiles()
            self.ui.add_security_log(
                f"Tippmuster für {user_name} gespeichert "
                f"({int(profile.get('n_keystrokes', 0))} Anschläge)", "SUCCESS")
            return True
        except Exception as exc:
            self.logger.error("Tippmuster-Training fehlgeschlagen: %s", exc)
            messagebox.showerror("Fehler", f"Tippmuster konnte nicht gespeichert werden:\n{exc}")
            return False

    def _current_keystroke_settings(self) -> dict:
        """Liefert die aktuelle Tippmuster-/Fusionskonfiguration für die UI."""
        kcfg = self._keystroke_config()
        pcfg = self._presence_config()
        return {
            "enabled": kcfg.enabled,
            "global_capture": kcfg.global_capture,
            "adaptive_learning": kcfg.adaptive_learning,
            "match_threshold": kcfg.match_threshold,
            "intruder_confidence_threshold": float(
                getattr(Config, "KEYSTROKE_INTRUDER_CONFIDENCE_THRESHOLD", 0.35)
            ),
            "min_enrollment_keystrokes": kcfg.min_enrollment_keystrokes,
            "fusion_mode": pcfg.fusion_mode,
            "primary_factor": pcfg.primary_factor,
            "on_face_lost": pcfg.on_face_lost,
            "on_keystroke_intruder": pcfg.on_keystroke_intruder,
            "on_keystroke_lost": pcfg.on_keystroke_lost,
        }

    def _on_save_keystroke_settings(self) -> None:
        """Speichert die in der UI vorgenommenen Tippmuster-/Fusionsoptionen."""
        if not self.ui:
            return
        settings = self.ui.collect_keystroke_settings()
        if not self._require_admin_password(
            "Änderungen an der Tippmustererkennung erfordern das Admin-Passwort."
        ):
            if self.ui:
                self.ui.set_keystroke_settings(self._current_keystroke_settings())
            return

        valid_actions = {"lock", "warn", "deadman", "ignore"}
        valid_fusion = {"face_only", "keystroke_only", "any", "all", "priority"}

        try:
            threshold = min(5.0, max(0.5, float(settings.get("match_threshold"))))
        except (TypeError, ValueError):
            threshold = Config.KEYSTROKE_MATCH_THRESHOLD
        try:
            intruder_confidence = min(
                1.0,
                max(0.0, float(settings.get("intruder_confidence_threshold"))),
            )
        except (TypeError, ValueError):
            intruder_confidence = float(
                getattr(Config, "KEYSTROKE_INTRUDER_CONFIDENCE_THRESHOLD", 0.35)
            )
        try:
            enrollment = min(2000, max(50, int(settings.get("min_enrollment_keystrokes"))))
        except (TypeError, ValueError):
            enrollment = Config.KEYSTROKE_MIN_ENROLLMENT_KEYSTROKES

        fusion = settings.get("fusion_mode")
        if fusion not in valid_fusion:
            fusion = Config.PRESENCE_FUSION_MODE
        primary = settings.get("primary_factor")
        if primary not in {"face", "keystroke"}:
            primary = Config.PRESENCE_PRIMARY_FACTOR
        on_face_lost = settings.get("on_face_lost")
        if on_face_lost not in valid_actions:
            on_face_lost = Config.PRESENCE_ON_FACE_LOST
        on_intruder = settings.get("on_keystroke_intruder")
        if on_intruder not in valid_actions:
            on_intruder = Config.PRESENCE_ON_KEYSTROKE_INTRUDER
        on_ks_lost = settings.get("on_keystroke_lost")
        if on_ks_lost not in valid_actions:
            on_ks_lost = Config.PRESENCE_ON_KEYSTROKE_LOST

        Config.KEYSTROKE_DYNAMICS_ENABLED = bool(settings.get("enabled", True))
        Config.KEYSTROKE_GLOBAL_CAPTURE = bool(settings.get("global_capture", True))
        Config.KEYSTROKE_ADAPTIVE_LEARNING = bool(settings.get("adaptive_learning", True))
        Config.KEYSTROKE_MATCH_THRESHOLD = threshold
        Config.KEYSTROKE_INTRUDER_CONFIDENCE_THRESHOLD = intruder_confidence
        Config.KEYSTROKE_MIN_ENROLLMENT_KEYSTROKES = enrollment
        Config.PRESENCE_FUSION_MODE = fusion
        Config.PRESENCE_PRIMARY_FACTOR = primary
        Config.PRESENCE_ON_FACE_LOST = on_face_lost
        Config.PRESENCE_ON_KEYSTROKE_INTRUDER = on_intruder
        Config.PRESENCE_ON_KEYSTROKE_LOST = on_ks_lost

        self.logger.info(
            "Tippmuster-Konfiguration aktualisiert: aktiv=%s fusion=%s primär=%s schwelle=%.2f alarm_conf=%.2f",
            Config.KEYSTROKE_DYNAMICS_ENABLED, fusion, primary, threshold, intruder_confidence,
        )
        self.ui.add_security_log("Tippmuster-Konfiguration aktualisiert")

        # Normalisierte Werte in die UI zurückspiegeln.
        self.ui.set_keystroke_settings(self._current_keystroke_settings())

        # Bei laufender Überwachung Monitor neu starten, damit Änderungen greifen.
        if self.monitoring_active:
            self._stop_keystroke_monitor()
            self._start_keystroke_monitor()

    def _train_keystrokes_prompt(self) -> None:
        """Öffnet eine Nutzerauswahl und startet danach das Tippmuster-Training."""
        users = self.db_manager.get_all_users()
        if not users:
            messagebox.showinfo(
                "Keine Benutzer",
                "Es sind keine Benutzer vorhanden. Bitte zuerst einen Benutzer anlegen.",
            )
            return
        names = [name for _, name in users]
        selected = self._prompt_user_selection(
            "Tippmuster trainieren",
            "Für welchen Benutzer soll das Tippmuster angelernt werden?",
            names,
        )
        if selected:
            self._train_keystrokes(selected)

    def _prompt_user_selection(self, title: str, prompt: str, names: list):
        """Kleiner modaler Auswahldialog für einen Benutzernamen."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        result = {"value": None}

        tk.Label(dialog, text=prompt, font=("Arial", 11)).pack(padx=20, pady=(16, 8))
        var = tk.StringVar(value=names[0])
        box = ttk.Combobox(dialog, textvariable=var, state="readonly", values=names, width=30)
        box.pack(padx=20, pady=6)

        btns = tk.Frame(dialog)
        btns.pack(pady=(10, 16))

        def _ok():
            result["value"] = var.get()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        tk.Button(btns, text="Trainieren", command=_ok, padx=14, pady=5).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Abbrechen", command=_cancel, padx=14, pady=5).pack(side=tk.LEFT, padx=6)

        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        dialog.update_idletasks()
        w = dialog.winfo_width()
        h = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f"+{x}+{y}")
        self.root.wait_window(dialog)
        return result["value"]

    def _refresh_user_list(self):
        """Aktualisiert die Benutzerliste"""
        try:
            users = self.db_manager.get_all_users()
            user_names = [name for _, name in users]
            self.ui.refresh_user_list(user_names)
            self.logger.info("Benutzerliste aktualisiert: %d Benutzer", len(user_names))
        except Exception as e:
            self.logger.error(f"Fehler beim Laden der Benutzerliste: {e}")
    
    # UI Callback Implementierungen
    def _test_camera(self):
        """Testet die Kamera"""
        self.camera_manager.test_camera()
    
    def _diagnose_camera(self):
        """Führt Kamera-Diagnose durch"""
        diagnosis = self.camera_manager.diagnose()
        messagebox.showinfo("Kamera-Diagnose", diagnosis)
    
    def _toggle_monitoring(self):
        """Schaltet Überwachung ein/aus"""
        if self.monitoring_active:
            self._stop_monitoring()
        else:
            self._start_monitoring()
    
    def _add_new_user(self):
        """Fügt einen neuen Benutzer hinzu"""
        # Name eingeben
        name = simpledialog.askstring("Name", 
                                     "Bitte geben Sie einen Namen für den neuen Benutzer ein:")
        if not name:
            return
        
        # PIN eingeben
        pin = simpledialog.askstring("PIN", 
                                   f"Bitte geben Sie eine PIN ein (mindestens {Config.MIN_PIN_LENGTH} Zeichen):", 
                                   show='*')
        if not pin or len(pin) < Config.MIN_PIN_LENGTH:
            messagebox.showerror("Fehler", 
                               f"PIN muss mindestens {Config.MIN_PIN_LENGTH} Zeichen lang sein.")
            return
        
        file_specs = self._collect_face_image_sources(f"Bilder für {name} hinzufügen")
        if not file_specs:
            messagebox.showerror("Fehler", "Keine Bilder ausgewählt.")
            return
        
        try:
            # Benutzer in Datenbank hinzufügen
            user_id = self.db_manager.add_user(name, pin)
            saved_count = self._store_face_images_for_user(user_id, name, file_specs)
            
            if saved_count > 0:
                messagebox.showinfo("Erfolg", 
                                  f"Benutzer '{name}' mit {saved_count} Gesichtsbild(ern) erstellt!")
                self._refresh_user_list()
                self.logger.info(f"Benutzer '{name}' mit {saved_count} Bildern erstellt")
                # Optionales Tippmuster-Training direkt nach der Anlage anbieten.
                self._enroll_keystrokes(user_id, name)
            else:
                # Benutzer löschen falls keine Bilder gespeichert
                self.db_manager.delete_user(name)
                messagebox.showerror("Fehler", "Kein gültiges Gesichtsbild gespeichert. Benutzer wurde nicht erstellt.")
        
        except ValueError as e:
            messagebox.showerror("Fehler", str(e))
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen des Benutzers: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Erstellen des Benutzers: {e}")
        finally:
            self._cleanup_temporary_image_files(file_specs)

    def _collect_face_image_sources(self, title: str) -> List[tuple[str, bool]]:
        """Sammelt Bildquellen aus Dateiauswahl und Webcam-Aufnahmen."""
        selected_specs: List[tuple[str, bool]] = []
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("460x280")
        dialog.minsize(420, 260)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(True, True)

        outer = ttk.Frame(dialog, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="Wie möchten Sie Bilder hinzufügen?",
            font=("Arial", 12, "bold"),
        ).pack(pady=(0, 8))

        count_label = ttk.Label(outer, text="Ausgewählte Bilder: 0")
        count_label.pack(pady=(0, 12))

        def update_count_label():
            count_label.config(text=f"Ausgewählte Bilder: {len(selected_specs)}")

        def add_files():
            file_paths = filedialog.askopenfilenames(
                title=title,
                filetypes=Config.IMAGE_FILE_TYPES
            )
            for file_path in file_paths:
                selected_specs.append((file_path, False))
            update_count_label()

        def add_webcam_photo():
            captured_path = self.camera_manager.capture_image()
            if captured_path:
                selected_specs.append((captured_path, True))
                update_count_label()

        button_frame = ttk.Frame(outer)
        button_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(button_frame, text="Dateien auswählen", command=add_files).pack(fill=tk.X, pady=4)

        webcam_state = tk.NORMAL if self.camera_manager and self.camera_manager.is_available else tk.DISABLED
        ttk.Button(
            button_frame,
            text="Mit Webcam aufnehmen",
            command=add_webcam_photo,
            state=webcam_state,
        ).pack(fill=tk.X, pady=4)

        ttk.Separator(button_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, expand=True, pady=(12, 8))

        bottom_frame = ttk.Frame(button_frame)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(bottom_frame, text="Fertig", command=dialog.destroy).pack(fill=tk.X, pady=(0, 4))
        ttk.Button(bottom_frame, text="Abbrechen", command=lambda: [selected_specs.clear(), dialog.destroy()]).pack(fill=tk.X)

        self.root.wait_window(dialog)
        return selected_specs

    def _cleanup_temporary_image_files(self, file_specs: List[tuple[str, bool]]):
        """Entfernt temporäre Webcam-Bilder nach dem Speichern."""
        for file_path, is_temporary in file_specs:
            if is_temporary and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    self.logger.warning(f"Temporäre Bilddatei konnte nicht gelöscht werden: {file_path} ({e})")

    def _store_face_images_for_user(self, user_id: int, user_name: str, file_specs) -> int:
        """Speichert mehrere Gesichtsbilder für einen Benutzer."""
        saved_count = 0
        new_geometries: List[np.ndarray] = []

        for file_path, _ in file_specs:
            try:
                enrollment = safe_face_enrollment_from_file(file_path)
                face_encodings = enrollment.get("encodings", [])
                geometries = enrollment.get("geometry", [])

                if not face_encodings:
                    messagebox.showwarning(
                        "Warnung",
                        f"Kein Gesicht erkannt in: {os.path.basename(file_path)}"
                    )
                    continue

                default_description = f"{user_name} - {os.path.basename(file_path)}"
                description = simpledialog.askstring(
                    "Beschreibung",
                    f"Optionale Beschreibung für {os.path.basename(file_path)}:",
                    initialvalue=default_description
                )
                if not description:
                    description = default_description

                with open(file_path, "rb") as image_file:
                    image_data = image_file.read()

                self.db_manager.add_face_encoding(
                    user_id,
                    face_encodings[0],
                    description,
                    image_data=image_data,
                    source_filename=os.path.basename(file_path),
                )
                # 3D-Geometrie des größten Gesichts für das Referenzmodell sammeln.
                if geometries:
                    new_geometries.append(geometries[0])
                saved_count += 1
                self.logger.info(
                    "Bild für Benutzer '%s' gespeichert: %s",
                    user_name,
                    os.path.basename(file_path),
                )

            except Exception as e:
                self.logger.error(f"Fehler beim Verarbeiten von {file_path}: {e}")
                messagebox.showerror(
                    "Fehler",
                    f"Fehler beim Verarbeiten von {os.path.basename(file_path)}: {e}"
                )

        if new_geometries:
            self._update_face_geometry_model(user_id, user_name, new_geometries)

        return saved_count

    def _update_face_geometry_model(
        self,
        user_id: int,
        user_name: str,
        new_geometries: List[np.ndarray],
    ) -> None:
        """Aktualisiert das aggregierte 3D-Referenzmodell des Benutzers.

        Aus den neu hochgeladenen Geometrien wird ein Aggregat gebildet und
        gewichtet mit einem evtl. bestehenden Modell verschmolzen. Dieses
        Modell dient der Kamera als Konsistenz-Check gegen 2D-Foto-Angriffe.
        """
        try:
            new_model = aggregate_geometries(new_geometries)
            if new_model is None:
                self.logger.warning(
                    "Keine gültige 3D-Geometrie für Benutzer '%s' – Modell unverändert.",
                    user_name,
                )
                return

            existing = self.db_manager.get_face_geometry_model(user_id)
            existing_model = deserialize_geometry(existing[0]) if existing else None
            existing_n = existing[1] if existing else 0

            combined, total = combine_geometry_models(
                existing_model, existing_n, new_model, len(new_geometries)
            )
            if combined is None:
                return

            self.db_manager.upsert_face_geometry_model(
                user_id, serialize_geometry(combined), total
            )
            self.logger.info(
                "3D-Referenzmodell für Benutzer '%s' aktualisiert (%s Stichproben).",
                user_name,
                total,
            )
        except Exception as e:
            self.logger.error(
                "Fehler beim Aktualisieren des 3D-Modells für '%s': %s", user_name, e
            )

    def _add_images_to_user(self, user_name: str):
        """Fügt einem bestehenden Benutzer weitere Trainingsbilder hinzu."""
        try:
            user_id = self.db_manager.get_user_id(user_name)
            if user_id is None:
                messagebox.showerror("Fehler", f"Benutzer '{user_name}' wurde nicht gefunden.")
                return

            file_specs = self._collect_face_image_sources(f"Weitere Bilder für {user_name} hinzufügen")
            if not file_specs:
                return

            saved_count = self._store_face_images_for_user(user_id, user_name, file_specs)
            if saved_count > 0:
                messagebox.showinfo(
                    "Erfolg",
                    f"Zu Benutzer '{user_name}' wurden {saved_count} weitere Bild(er) hinzugefügt."
                )
                self.logger.info(f"Benutzer '{user_name}': {saved_count} weitere Bilder hinzugefügt")
            else:
                messagebox.showwarning(
                    "Keine Bilder gespeichert",
                    f"Für Benutzer '{user_name}' konnte kein gültiges Gesichtsbild gespeichert werden."
                )

        except Exception as e:
            self.logger.error(f"Fehler beim Hinzufügen weiterer Bilder für {user_name}: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Hinzufügen weiterer Bilder: {e}")
        finally:
            if 'file_specs' in locals():
                self._cleanup_temporary_image_files(file_specs)
    
    def _show_user_images(self, user_name: str):
        """Zeigt Bilder eines Benutzers"""
        try:
            images = self.db_manager.get_user_face_records(user_name)
            if not images:
                messagebox.showinfo("Keine Bilder", 
                                  f"Für Benutzer '{user_name}' sind keine Bilder gespeichert.")
                return

            window = tk.Toplevel(self.root)
            window.title(f"Bilder von {user_name}")
            window.geometry("920x680")
            window.minsize(720, 520)
            window.resizable(True, True)
            window.transient(self.root)

            outer = ttk.Frame(window, padding=12)
            outer.pack(fill=tk.BOTH, expand=True)

            ttk.Label(
                outer,
                text=f"Gespeicherte Bilder für '{user_name}'",
                font=("Arial", 14, "bold"),
            ).pack(anchor="w", pady=(0, 10))

            canvas = tk.Canvas(outer, highlightthickness=0)
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            content = ttk.Frame(canvas)

            content.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            canvas.create_window((0, 0), window=content, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            window.image_refs = []

            for index, (face_id, desc, image_data, source_filename, created_at) in enumerate(images, 1):
                card = ttk.Frame(content, padding=10, relief="ridge")
                card.pack(fill=tk.X, expand=True, pady=6)

                if image_data:
                    pil_image = Image.open(io.BytesIO(image_data))
                    pil_image.thumbnail((220, 220), Image.Resampling.LANCZOS)
                    preview = ImageTk.PhotoImage(pil_image)
                    window.image_refs.append(preview)
                    ttk.Label(card, image=preview).pack(side=tk.LEFT, padx=(0, 12))
                else:
                    placeholder = ttk.Label(card, text="Kein Bild gespeichert", width=24)
                    placeholder.pack(side=tk.LEFT, padx=(0, 12))

                info_frame = ttk.Frame(card)
                info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                ttk.Label(info_frame, text=f"Bild {index}", font=("Arial", 12, "bold")).pack(anchor="w")
                ttk.Label(info_frame, text=f"Beschreibung: {desc or '-'}").pack(anchor="w", pady=(6, 0))
                ttk.Label(info_frame, text=f"Datei: {source_filename or '-'}").pack(anchor="w", pady=(4, 0))
                ttk.Label(info_frame, text=f"Gespeichert: {created_at or '-'}").pack(anchor="w", pady=(4, 0))

                button_frame = ttk.Frame(card)
                button_frame.pack(side=tk.RIGHT, padx=(12, 0))
                
                delete_btn = ttk.Button(
                    button_frame,
                    text="Löschen",
                    command=lambda fid=face_id: self._delete_user_image(user_name, fid, window)
                )
                delete_btn.pack(padx=4)

            self.logger.info("Bildübersicht für Benutzer '%s' geöffnet", user_name)
            
        except Exception as e:
            self.logger.error(f"Fehler beim Anzeigen der Bilder: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Laden der Bilder: {e}")
    
    def _delete_user_image(self, user_name: str, face_id: int, window: tk.Toplevel):
        """Löscht ein einzelnes Nutzerbild"""
        try:
            if not messagebox.askyesno(
                "Bild löschen",
                f"Dieses Bild wirklich löschen?\nDiese Aktion kann nicht rückgängig gemacht werden."
            ):
                return
            
            if self.db_manager.delete_face_encoding(face_id):
                messagebox.showinfo("Erfolg", "Bild wurde gelöscht.")
                self.logger.info(f"Bild {face_id} für Benutzer '{user_name}' gelöscht")
                
                # Fenster schließen und neu laden
                window.destroy()
                self._show_user_images(user_name)
            else:
                messagebox.showwarning("Warnung", "Bild konnte nicht gelöscht werden.")
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Bildes: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Löschen des Bildes: {e}")
    
    def _delete_user(self, user_name: str):
        """Löscht einen Benutzer"""
        try:
            if not self._require_admin_password(
                f"Das Löschen von Benutzer '{user_name}' erfordert ein Admin-Passwort."
            ):
                return

            if not messagebox.askyesno(
                "Benutzer löschen",
                f"Benutzer '{user_name}' wirklich löschen?\nDiese Aktion kann nicht rückgängig gemacht werden.",
            ):
                return

            if self.db_manager.delete_user(user_name):
                messagebox.showinfo("Erfolg", f"Benutzer '{user_name}' wurde gelöscht.")
                self._refresh_user_list()
                self.logger.info(f"Benutzer '{user_name}' gelöscht")

                if self.monitoring_active and not self._has_registered_users():
                    self._stop_monitoring()
                    self.ui.add_security_log(
                        "Alle Benutzer gelöscht - Überwachung gestoppt, Admin-Entsperrung erforderlich",
                        "ERROR",
                    )
                    self._activate_security_lock(
                        "Keine Benutzer mehr vorhanden. Entsperren nur mit Admin-Passwort.",
                        force_admin_password=True,
                    )
            else:
                messagebox.showwarning("Warnung", f"Benutzer '{user_name}' nicht gefunden.")
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Benutzers: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Löschen: {e}")
    
    # Kamera Callbacks
    def _on_user_recognized(self, user_name: str):
        """Wird thread-sicher auf den Tk-Hauptthread umgeleitet."""
        self.root.after(0, lambda: self._handle_user_recognized(user_name))

    def _on_user_seen(self, user_name: str):
        """Heartbeat: jeder Frame mit legitimem Nutzer setzt den Sperr-Timer
        sofort zurück. Wird auch ohne Statuswechsel und ohne Logging gefeuert,
        damit kurze Erkennungen den 10-Sekunden-Countdown neu starten.
        """
        now = time.time()
        self.last_face_seen_at = now
        # Bei aktiver Fusion entscheidet der Deadman-Loop über den Sperr-Timer;
        # andernfalls reicht der reine Gesichts-Heartbeat.
        if not self._fusion_active():
            self.last_authorized_seen_at = now
        if self.deadman_triggered:
            self.deadman_triggered = False

    def _on_camera_preview_updated(self, image: Image.Image, status_text: str, status_level: str):
        """Aktualisiert die kleine Monitoring-Vorschau im Hauptfenster."""
        try:
            preview = ImageTk.PhotoImage(image=image)
            self.root.after(
                0,
                lambda: self._handle_camera_preview_updated(preview, status_text, status_level),
            )
        except Exception as e:
            self.logger.debug("Monitoring-Vorschau konnte nicht aktualisiert werden: %s", e)

    def _handle_camera_preview_updated(self, preview, status_text: str, status_level: str):
        """Aktualisiert Vorschau und zeigt Liveness-Anweisungen im Lock-Screen."""
        self.ui.update_monitor_preview(preview, status_text, status_level)
        if not self.security_lock_active:
            return

        normalized_status = str(status_text or "").strip()
        normalized_level = str(status_level or "INFO").upper()
        if (
            normalized_status == self.security_lock_camera_status
            and normalized_level == self.security_lock_camera_status_level
        ):
            return
        self.security_lock_camera_status = normalized_status
        self.security_lock_camera_status_level = normalized_level
        self._update_security_lock_status()

    def _handle_user_recognized(self, user_name: str):
        """Verarbeitet erkannte Benutzer im Tk-Hauptthread.

        Dieser Callback wird erst nach einer bestätigten Liveness-Prüfung und
        stabilem Kamera-Status ausgelöst. Er ist daher der verbindliche Einstieg
        für PIN- und Gesichtsentsperrung.
        """
        self.last_face_seen_at = time.time()
        if not self._fusion_active():
            self.last_authorized_seen_at = time.time()
        self.deadman_triggered = False
        self.ui.add_security_log(f"Benutzer erkannt: {user_name}")
        self.logger.info(f"Autorisierter Zugriff: {user_name}")
        if not self.security_lock_active or self.force_admin_unlock_required:
            return
        self.security_lock_camera_status = f"Gesicht von {user_name} bestätigt."
        self.security_lock_camera_status_level = "SUCCESS"
        self._update_security_lock_status()
        if self.security_mode == "strict_pin":
            self._prompt_strict_unlock(user_name)
        elif self.security_mode == "self_unlock":
            self.logger.info("Gesichtsentsperrung angefordert: %s", user_name)
            self._schedule_self_unlock(user_name)
    
    def _on_unauthorized_access(self):
        """Wird thread-sicher auf den Tk-Hauptthread umgeleitet."""
        self.root.after(0, self._handle_unauthorized_access)

    def _on_emotion_alert(self, emotion: str, duration_seconds: float):
        """Wird thread-sicher auf den Tk-Hauptthread umgeleitet."""
        self.root.after(0, lambda: self._handle_emotion_alert(emotion, duration_seconds))

    def _handle_emotion_alert(self, emotion: str, duration_seconds: float):
        labels = {
            "angst": "Angst",
            "panik": "Panik",
            "unsicherheit": "Unsicherheit",
            "nervositaet": "Nervositaet",
        }
        label = labels.get(emotion, emotion)
        self.ui.add_security_log(
            f"Kritische Emotion erkannt ({label}) seit {duration_seconds:.1f}s - Sperrbildschirm aktiviert",
            "ERROR",
        )
        self.logger.warning(
            "Kritische Emotion erkannt: %s seit %.2fs - Sperrbildschirm wird aktiviert",
            label,
            duration_seconds,
        )
        self._activate_security_lock(
            f"Kritische Emotion erkannt ({label}) seit {duration_seconds:.1f}s"
        )

    def _handle_unauthorized_access(self):
        """
        Wird aufgerufen bei unerlaubtem Zugriff:
        - Unbekanntes Gesicht erkannt
        - Kamera abgedeckt (kein Gesicht erkannt)
        """
        if self.security_mode == "deadman":
            self.ui.add_security_log("Unbekannt oder kein Nutzer erkannt - Totmannschalter-Timer läuft", "WARNING")
            self.logger.warning("Unbekannt oder kein Nutzer erkannt - Totmannschalter-Timer läuft weiter")
        else:
            self.ui.add_security_log(
                f"Unbekannt oder kein Nutzer erkannt - Sperre nach {self.security_lock_delay_seconds}s ohne legitime Erkennung",
                "WARNING",
            )
            self.logger.warning(
                "Unbekannt oder kein Nutzer erkannt - Sperre erfolgt nach %ss ohne legitimen Nutzer",
                self.security_lock_delay_seconds,
            )
    
    # Überwachungsfunktionen
    def _start_monitoring(self):
        """Startet die Überwachung"""
        try:
            if not self._has_registered_users():
                self.monitoring_active = False
                self.ui.update_monitoring_button(False)
                self.ui.add_security_log("Überwachung nicht möglich: keine Benutzer vorhanden", "ERROR")
                messagebox.showwarning(
                    "Überwachung nicht möglich",
                    "Es sind keine Benutzer hinterlegt. Bitte zuerst mindestens einen Benutzer anlegen.",
                )
                return

            self.monitoring_active = True
            self.last_authorized_seen_at = time.time()
            self.last_face_seen_at = time.time()
            self.deadman_triggered = False
            self.ui.clear_monitor_preview("Kamera wird gestartet...")
            
            # Kamera starten
            if self.camera_manager.is_available:
                if self.camera_manager.start():
                    self.ui.add_security_log("Kamera-Überwachung gestartet")
                else:
                    self.ui.add_security_log("Kamera-Start fehlgeschlagen")

            # Tippmuster-Überwachung als zweiten Faktor starten.
            self._start_keystroke_monitor()

            if self.deadman_thread is None or not self.deadman_thread.is_alive():
                self.deadman_thread = threading.Thread(
                    target=self._deadman_monitor_loop,
                    daemon=True,
                    name="DeadmanMonitor",
                )
                self.deadman_thread.start()
            
            self.ui.add_security_log("Überwachung gestartet")
            self.ui.update_monitoring_button(True)

            self.logger.info("Überwachung gestartet")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Starten der Überwachung: {e}")
            messagebox.showerror("Fehler", f"Überwachung konnte nicht gestartet werden: {e}")
    
    def _stop_monitoring(self):
        """Stoppt die Überwachung"""
        try:
            self.monitoring_active = False
            self.deadman_triggered = False
            
            # Kamera stoppen
            self.camera_manager.stop()

            # Tippmuster-Überwachung stoppen.
            self._stop_keystroke_monitor()
            
            if self.security_lock_active:
                self._release_security_lock()

            self.ui.add_security_log("Überwachung gestoppt")
            self.ui.update_monitoring_button(False)
            self.ui.clear_monitor_preview()
            
            self.logger.info("Überwachung gestoppt")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Stoppen der Überwachung: {e}")
    
    # Tray-Funktionen
    def _minimize_to_tray(self):
        """Minimiert die Anwendung in die Systemleiste"""
        try:
            if self.tray_icon is not None:
                return

            # Verstecke Hauptfenster
            self.root.withdraw()
            
            # Erstelle Tray-Icon
            if Config.APP_ICON_PATH.exists():
                image = Image.open(Config.APP_ICON_PATH).convert("RGBA")
                image.thumbnail(Config.TRAY_ICON_SIZE, Image.Resampling.LANCZOS)
            else:
                image = Image.new('RGB', Config.TRAY_ICON_SIZE, color='white')
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0) + Config.TRAY_ICON_SIZE, fill=Config.TRAY_ICON_COLOR)
            
            menu = pystray.Menu(
                pystray.MenuItem("Öffnen", self._restore_from_tray),
                pystray.MenuItem("Überwachung stoppen" if self.monitoring_active else "Überwachung starten",
                               self._toggle_monitoring_from_tray),
                pystray.MenuItem("Beenden", self._quit_from_tray)
            )
            
            self.tray_icon = pystray.Icon(Config.APP_NAME, image, Config.APP_NAME, menu)
            
            # Starte Tray-Icon in separatem Thread
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True, name="TrayIcon")
            tray_thread.start()
            self.active_threads.append(tray_thread)
            
            self.logger.info("In Systemleiste minimiert")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Minimieren in Tray: {e}")
    
    def _restore_from_tray(self, icon=None, item=None):
        """Plant das Wiederherstellen aus der Systemleiste im Tk-Hauptthread."""
        self.root.after(0, self._show_restore_pin_dialog)

    def _show_restore_pin_dialog(self):
        """Stellt die Anwendung aus der Systemleiste wieder her – nur mit Admin-Passwort."""
        # Prüfe Session-Zeit
        if time.time() - self.session_start > Config.MAX_SESSION_DURATION:
            messagebox.showwarning("Session abgelaufen", 
                                 "Die Session ist abgelaufen. Bitte starten Sie TuxGuard neu.")
            self._quit_application()
            return
        
        if not self._require_admin_password(
            "Zum Öffnen aus der Systemleiste wird das Admin-Passwort benötigt."
        ):
            return

        self.root.deiconify()
        self.root.update_idletasks()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(200, lambda: self.root.attributes('-topmost', False))
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.logger.info("Anwendung aus Tray wiederhergestellt")
    
    def _toggle_monitoring_from_tray(self, icon=None, item=None):
        """Schaltet Überwachung aus Tray um"""
        self.root.after(0, self._toggle_monitoring)
    
    def _quit_from_tray(self, icon=None, item=None):
        """Beendet Anwendung aus Tray"""
        self.root.after(0, self._show_quit_pin_dialog)
    
    def _show_quit_pin_dialog(self):
        """Beendet TuxGuard – nur mit Admin-Passwort."""
        if self._require_admin_password("Zum Beenden von TuxGuard ist das Admin-Passwort erforderlich."):
            self._quit_application()
    
    # Anwendungsende
    def _on_closing(self):
        """Wird beim Schließen des Hauptfensters aufgerufen"""
        if self.close_behavior == "tray":
            self._minimize_to_tray()
            return
        if self.close_behavior == "quit":
            self._quit_application()
            return

        # close_behavior == "ask"
        decision = messagebox.askyesnocancel(
            "TuxGuard schließen",
            "Ja: Anwendung beenden\nNein: In die Systemleiste minimieren\nAbbrechen: Aktion abbrechen",
        )
        if decision is None:
            return
        if decision:
            self._quit_application()
        else:
            self._minimize_to_tray()
    
    def _quit_application(self):
        """Beendet die Anwendung"""
        try:
            self.logger.info("TuxGuard wird beendet...")
            
            # Überwachung stoppen
            if self.monitoring_active:
                self._stop_monitoring()
            
            # Tray-Icon stoppen
            if self.tray_icon:
                self.tray_icon.stop()
            
            # Datenbank schließen
            self.db_manager.disconnect()
            
            # Threads beenden
            for thread in self.active_threads:
                if thread.is_alive():
                    try:
                        thread.join(timeout=1.0)
                    except Exception:
                        pass
            
            # Tkinter beenden
            self.root.quit()
            self.root.destroy()
            
            self.logger.info("TuxGuard erfolgreich beendet")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Beenden: {e}")
        finally:
            sys.exit(0)
    
    def run(self):
        """Startet die Anwendung"""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.logger.info("Anwendung durch Benutzer unterbrochen")
            self._quit_application()
        except Exception as e:
            self.logger.error(f"Unerwarteter Fehler in Hauptschleife: {e}")
            self._quit_application()

def main():
    """Haupteinstiegspunkt"""
    # Display-Check für headless Umgebungen
    import os
    if not os.environ.get('DISPLAY'):
        print("⚠️  Kein Display erkannt - TuxGuard benötigt eine grafische Umgebung")
        print("💡 Starten Sie TuxGuard in einer Desktop-Umgebung mit:")
        print("   • Lokaler GUI-Session")
        print("   • X11-Forwarding über SSH (ssh -X)")
        print("   • VNC/Remote Desktop")
        print("   • WSL mit X-Server (Windows)")
        return
    
    try:
        # Test der GUI-Verfügbarkeit
        root_test = tk.Tk()
        root_test.withdraw()  # Verstecken
        root_test.destroy()   # Sofort wieder löschen
        
        print(f"🛡️  Starte {Config.APP_NAME} v{Config.APP_VERSION}...")
        print("⚡ GUI-System verfügbar - initialisiere Anwendung...")
        
        app = TuxGuardApplication()
        app.run()
        
    except tk.TclError as e:
        print("❌ GUI-Fehler - Grafische Umgebung nicht verfügbar")
        print(f"   Technischer Fehler: {e}")
        print("💡 Lösungsvorschläge:")
        print("   • Stellen Sie sicher, dass Sie sich in einer Desktop-Umgebung befinden")
        print("   • Verwenden Sie 'export DISPLAY=:0' falls nötig")
        print("   • Nutzen Sie SSH mit X11-Forwarding: ssh -X user@host")
        sys.exit(1)
        
    except ImportError as e:
        print("❌ Abhängigkeits-Fehler")
        print(f"   Fehlende Bibliothek: {e}")
        print("💡 Installieren Sie fehlende Abhängigkeiten:")
        print("   pip install -r requirements.txt")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Kritischer Fehler beim Starten von TuxGuard: {e}")
        print("🔍 Aktiviere Debug-Modus für weitere Informationen...")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

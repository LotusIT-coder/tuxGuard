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
import logging
from pathlib import Path
from typing import Optional, List, Dict

import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import numpy as np
import face_recognition
from PIL import Image, ImageDraw
import pystray

# Lokale Module
from config import Config
from logging_setup import setup_logging
from database import DatabaseManager, SecurityUtils
from camera import CameraManager
from simple_ui import MainUI, PinDialog
from mouse_monitor import (
    load_pattern_model, verify_mouse_pattern,
    start_mouse_monitoring, stop_mouse_monitoring,
    train_mouse_pattern, set_mouse_monitoring_callback
)

class TuxGuardApplication:
    """Hauptanwendungsklasse für TuxGuard"""
    
    def __init__(self):
        # Logging initialisieren
        self.logger = setup_logging()
        self.logger.info(f"TuxGuard {Config.APP_VERSION} wird gestartet...")
        
        # Verzeichnisse sicherstellen
        Config.ensure_directories()
        
        # Tkinter Root
        self.root = tk.Tk()
        self.root.withdraw()  # Verstecke zunächst
        
        # Komponenten
        self.db_manager = DatabaseManager()
        self.camera_manager = None
        self.ui = None
        self.tray_icon = None
        
        # Status
        self.monitoring_active = False
        self.session_start = time.time()
        self.pattern_model = None
        self.pattern_training_thread = None
        
        # Threads
        self.active_threads = []
        
        try:
            self._initialize_components()
            self._setup_callbacks()
            self.root.deiconify()
            self.logger.info("TuxGuard erfolgreich initialisiert")
            def _init_autostart_ui():
                autostart_enabled = self._is_autostart_enabled()
                if hasattr(self.ui, 'set_autostart_state'):
                    self.ui.set_autostart_state(autostart_enabled)
                if hasattr(self.ui, 'autostart_callback'):
                    self.ui.autostart_callback = self._on_autostart_checkbox
                # Autostart: Überwachungsmodus ggf. direkt aktivieren
                if autostart_enabled and self._has_registered_users():
                    self._start_monitoring()
            self.root.after(0, _init_autostart_ui)
        except Exception as e:
            self.root.deiconify()
            self.logger.error(f"Fehler bei der Initialisierung: {e}")
            messagebox.showerror("Initialisierungsfehler", f"Fehler beim Starten der Anwendung: {e}")
            sys.exit(1)
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

    def _is_autostart_enabled(self):
        import os
        service_path = self._get_systemd_user_service_path()
        return os.path.exists(service_path)

    def _on_autostart_checkbox(self, enabled: bool):
        if enabled:
            self._enable_autostart_service()
        else:
            self._disable_autostart_service()

    def _enable_autostart_service(self):
        import os, getpass
        service_path = self._get_systemd_user_service_path()
        os.makedirs(os.path.dirname(service_path), exist_ok=True)
        exec_path = os.path.abspath(__file__)
        user = getpass.getuser()
        service_content = f"""[Unit]\nDescription=TuxGuard Security Service\nAfter=graphical-session.target network.target\n\n[Service]\nType=simple\nExecStart={exec_path}\nRestart=on-failure\nUser={user}\n\n[Install]\nWantedBy=default.target\n"""
        with open(service_path, 'w') as f:
            f.write(service_content)
        # Enable the service
        os.system('systemctl --user daemon-reload')
        os.system('systemctl --user enable --now tuxguard.service')
        self.logger.info("Autostart als Systemdienst aktiviert.")

    def _disable_autostart_service(self):
        import os
        service_path = self._get_systemd_user_service_path()
        if os.path.exists(service_path):
            os.system('systemctl --user disable --now tuxguard.service')
            os.remove(service_path)
            os.system('systemctl --user daemon-reload')
            self.logger.info("Autostart als Systemdienst deaktiviert.")
        
        # Zeige UI
        self.root.deiconify()
        
        self.logger.info("TuxGuard erfolgreich initialisiert")
    
    def _initialize_components(self):
        """Initialisiert alle Komponenten"""
        try:
            # Datenbank verbinden
            self.db_manager.connect()
            
            # Kamera-Manager erstellen
            self.camera_manager = CameraManager(self.root, self.db_manager)
            
            # UI erstellen
            self.ui = MainUI(self.root)
            
            # Mustererkennungsmodell laden
            self._load_pattern_model()
            
            # Status aktualisieren
            self.ui.update_status(
                camera_available=self.camera_manager.is_available,
                mouse_available=self.pattern_model is not None
            )
            
            # Kamera-Buttons konfigurieren
            self.ui.configure_camera_buttons(self.camera_manager.is_available)
            
            # Benutzerliste laden
            self._refresh_user_list()
            
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
        self.ui.set_callback('train_pattern', self._train_pattern)
        self.ui.set_callback('toggle_monitoring', self._toggle_monitoring)
        self.ui.set_callback('add_new_user', self._add_new_user)
        
        # Kamera Callbacks
        self.camera_manager.set_callbacks(
            user_recognized=self._on_user_recognized,
            unauthorized_access=self._on_unauthorized_access
        )
        
        # Mausüberwachung Callback
        set_mouse_monitoring_callback(self._on_mouse_verification_failed)
        
        # User List Callbacks
        self.ui.user_list_widget.set_callbacks(
            show_images=self._show_user_images,
            delete_user=self._delete_user
        )
        
        # Window Callback
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _set_train_button_enabled(self, enabled: bool):
        """Aktiviert oder deaktiviert den Trainings-Button in der UI."""
        if not self.ui:
            return
        button = self.ui.control_buttons.get('train_pattern')
        if not button:
            return
        state = tk.NORMAL if enabled else tk.DISABLED
        self.root.after(0, lambda: button.config(state=state))

    def _load_pattern_model(self):
        """Lädt das Mustererkennungsmodell"""
        try:
            if Config.MOUSE_PATTERN_MODEL.exists():
                self.pattern_model = load_pattern_model()
                if self.pattern_model:
                    self.logger.info("Mustererkennungsmodell geladen")
                else:
                    self.logger.warning("Mustererkennungsmodell konnte nicht geladen werden")
            else:
                self.logger.info("Kein Mustererkennungsmodell gefunden")
        except Exception as e:
            self.logger.error(f"Fehler beim Laden des Mustererkennungsmodells: {e}")
    
    def _refresh_user_list(self):
        """Aktualisiert die Benutzerliste"""
        try:
            users = self.db_manager.get_all_users()
            user_names = [name for _, name in users]
            self.ui.refresh_user_list(user_names)
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
    
    def _train_pattern(self):
        """Startet das Training der Mausbewegungsmuster im Hintergrund."""
        if self.pattern_training_thread and self.pattern_training_thread.is_alive():
            messagebox.showinfo("Training läuft", "Das Muster-Training wird bereits ausgeführt.")
            return

        if not messagebox.askokcancel(
            "Mausbewegungen trainieren",
            "Während des Trainings werden Ihre aktuellen Mausbewegungen aufgezeichnet.\n"
            "Bitte bewegen Sie die Maus in Ihrem üblichen Arbeitsmuster."
        ):
            return

        self.ui.add_mouse_log("Muster-Training gestartet", "INFO")
        self._set_train_button_enabled(False)

        self.pattern_training_thread = threading.Thread(
            target=self._run_pattern_training,
            daemon=True,
            name="MousePatternTraining"
        )
        self.pattern_training_thread.start()

    def _run_pattern_training(self):
        """Führt das Mausmuster-Training aus und aktualisiert UI sowie Status."""

        def log_to_ui(message: str, level: str = "INFO"):
            self.root.after(0, lambda: self.ui.add_mouse_log(message, level))

        def report_progress(epoch: int, total: int, metrics: Dict[str, float]):
            parts = [f"Epoche {epoch}/{total}"]
            if metrics:
                metric_parts = [f"{key}: {value:.4f}" for key, value in metrics.items() if isinstance(value, (int, float))]
                if metric_parts:
                    parts.append(", ".join(metric_parts))
            log_to_ui(f"Training – {' | '.join(parts)}")

        try:
            result = train_mouse_pattern(
                duration=Config.MOUSE_TRAINING_DURATION,
                epochs=Config.MOUSE_TRAINING_EPOCHS,
                batch_size=Config.MOUSE_TRAINING_BATCH_SIZE,
                log_callback=log_to_ui,
                progress_callback=report_progress
            )

            self.logger.info("Muster-Training erfolgreich abgeschlossen: %s", result)
            self.pattern_model = load_pattern_model(force_reload=True)

            self.root.after(0, lambda: self.ui.update_status(mouse_available=self.pattern_model is not None))
            log_to_ui("Muster-Training erfolgreich abgeschlossen", "SUCCESS")
            self.root.after(0, lambda: messagebox.showinfo(
                "Training abgeschlossen",
                "Das Mausmuster-Modell wurde erfolgreich trainiert und gespeichert."
            ))

        except Exception as exc:
            self.logger.error("Muster-Training fehlgeschlagen: %s", exc, exc_info=True)
            log_to_ui(f"Training fehlgeschlagen: {exc}", "ERROR")
            self.root.after(0, lambda: messagebox.showerror("Training fehlgeschlagen", str(exc)))

        finally:
            self.pattern_training_thread = None
            self._set_train_button_enabled(True)
    
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
        
        # Bilder auswählen
        file_paths = filedialog.askopenfilenames(
            title="Bilder für Gesichtserkennung auswählen",
            filetypes=Config.IMAGE_FILE_TYPES
        )
        if not file_paths:
            messagebox.showerror("Fehler", "Keine Bilder ausgewählt.")
            return
        
        try:
            # Benutzer in Datenbank hinzufügen
            user_id = self.db_manager.add_user(name, pin)
            
            # Gesichtsbilder verarbeiten
            saved_count = 0
            for file_path in file_paths:
                try:
                    # Bild laden und Gesicht erkennen
                    image = face_recognition.load_image_file(file_path)
                    face_encodings = face_recognition.face_encodings(image)
                    
                    if not face_encodings:
                        messagebox.showwarning("Warnung", 
                                             f"Kein Gesicht erkannt in: {os.path.basename(file_path)}")
                        continue
                    
                    # Beschreibung eingeben
                    description = simpledialog.askstring("Beschreibung", 
                                                        f"Optionale Beschreibung für {os.path.basename(file_path)}:")
                    if not description:
                        description = f"Bild {saved_count + 1}"
                    
                    # Gesichtskodierung speichern
                    self.db_manager.add_face_encoding(user_id, face_encodings[0], description)
                    saved_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Fehler beim Verarbeiten von {file_path}: {e}")
                    messagebox.showerror("Fehler", 
                                       f"Fehler beim Verarbeiten von {os.path.basename(file_path)}: {e}")
            
            if saved_count > 0:
                messagebox.showinfo("Erfolg", 
                                  f"Benutzer '{name}' mit {saved_count} Gesichtsbild(ern) erstellt!")
                self._refresh_user_list()
                self.logger.info(f"Benutzer '{name}' mit {saved_count} Bildern erstellt")
            else:
                # Benutzer löschen falls keine Bilder gespeichert
                self.db_manager.delete_user(name)
                messagebox.showerror("Fehler", "Kein gültiges Gesichtsbild gespeichert. Benutzer wurde nicht erstellt.")
        
        except ValueError as e:
            messagebox.showerror("Fehler", str(e))
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen des Benutzers: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Erstellen des Benutzers: {e}")
    
    def _show_user_images(self, user_name: str):
        """Zeigt Bilder eines Benutzers"""
        try:
            images = self.db_manager.get_user_face_encodings(user_name)
            if not images:
                messagebox.showinfo("Keine Bilder", 
                                  f"Für Benutzer '{user_name}' sind keine Bilder gespeichert.")
                return
            
            # Einfaches Informationsfenster
            info_text = f"Gespeicherte Bilder für '{user_name}':\n\n"
            for i, (desc, _) in enumerate(images, 1):
                info_text += f"{i}. {desc}\n"
            
            messagebox.showinfo(f"Bilder von {user_name}", info_text)
            
        except Exception as e:
            self.logger.error(f"Fehler beim Anzeigen der Bilder: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Laden der Bilder: {e}")
    
    def _delete_user(self, user_name: str):
        """Löscht einen Benutzer"""
        try:
            if self.db_manager.delete_user(user_name):
                messagebox.showinfo("Erfolg", f"Benutzer '{user_name}' wurde gelöscht.")
                self._refresh_user_list()
                self.logger.info(f"Benutzer '{user_name}' gelöscht")
            else:
                messagebox.showwarning("Warnung", f"Benutzer '{user_name}' nicht gefunden.")
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Benutzers: {e}")
            messagebox.showerror("Fehler", f"Fehler beim Löschen: {e}")
    
    # Kamera Callbacks
    def _on_user_recognized(self, user_name: str):
        """Wird aufgerufen wenn ein Benutzer erkannt wurde"""
        self.ui.add_mouse_log(f"Benutzer erkannt: {user_name}")
        self.logger.info(f"Autorisierter Zugriff: {user_name}")
    
    def _on_unauthorized_access(self):
        """
        Wird aufgerufen bei unerlaubtem Zugriff:
        - Unbekanntes Gesicht erkannt
        - Kamera abgedeckt (kein Gesicht erkannt)
        
        Beide Fälle werden als Sicherheitsbedrohung behandelt und
        führen zu sofortigen Sicherheitsmaßnahmen (PIN-Dialog + Lock).
        """
        self.ui.add_mouse_log("⚠️ SICHERHEITSALARM: Unerlaubter Zugriff erkannt!")
        self.logger.warning("Unerlaubter Zugriff erkannt - Sicherheitsmaßnahmen werden eingeleitet")
        
        # Führe Sicherheitsmaßnahmen aus
        self._trigger_security_lock("Kamera: Unerlaubter Zugriff")
    
    def _on_mouse_verification_failed(self):
        """
        Wird aufgerufen wenn Mausmuster-Verifikation fehlschlägt.
        Dies deutet auf unautorisierten Zugriff hin (fremde Person am System).
        
        Führt zu sofortigen Sicherheitsmaßnahmen (PIN-Dialog + Lock).
        """
        self.ui.add_mouse_log("⚠️ SICHERHEITSALARM: Mausmuster nicht erkannt!")
        self.logger.warning("Mausmuster-Verifikation fehlgeschlagen - Sicherheitsmaßnahmen werden eingeleitet")
        
        # Führe Sicherheitsmaßnahmen aus
        self._trigger_security_lock("Mausmuster: Verifikation fehlgeschlagen")
    
    def _trigger_security_lock(self, reason: str):
        """Führt Sicherheitsmaßnahmen bei unerlaubtem Zugriff aus"""
        try:
            # Stoppe Überwachung temporär um Callback-Loop zu vermeiden
            was_monitoring = self.monitoring_active
            if was_monitoring:
                self._stop_monitoring()
            
            # Zeige Fenster wieder an
            self.root.after(0, self.root.deiconify)
            
            # Zeige kritischen Alarm-Dialog
            self.root.after(100, lambda: self._show_security_dialog(reason, was_monitoring))
            
        except Exception as e:
            self.logger.error(f"Fehler bei Sicherheitsmaßnahmen: {e}")
    
    def _show_security_dialog(self, reason: str, restart_monitoring: bool):
        """Zeigt Sicherheitsdialog mit PIN-Abfrage"""
        try:
            import subprocess as sp
            
            # Erstelle modalen Dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("🔒 SICHERHEITSALARM")
            dialog.geometry("500x300")
            dialog.attributes('-topmost', True)
            dialog.grab_set()
            dialog.protocol("WM_DELETE_WINDOW", lambda: None)  # Verhindere Schließen
            
            # Zentriere Dialog
            dialog.update_idletasks()
            x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
            y = (dialog.winfo_screenheight() // 2) - (300 // 2)
            dialog.geometry(f"500x300+{x}+{y}")
            
            # Inhalt
            tk.Label(dialog, text="⚠️ SICHERHEITSALARM ⚠️", 
                    font=('Arial', 16, 'bold'), fg='red').pack(pady=20)
            
            tk.Label(dialog, text=f"Grund: {reason}", 
                    font=('Arial', 11)).pack(pady=10)
            
            tk.Label(dialog, text="Geben Sie Ihre PIN ein, um fortzufahren:",
                    font=('Arial', 11)).pack(pady=10)
            
            pin_var = tk.StringVar()
            pin_entry = tk.Entry(dialog, textvariable=pin_var, show='*', 
                                font=('Arial', 14), width=20)
            pin_entry.pack(pady=10)
            pin_entry.focus_set()
            
            def verify_and_close():
                pin = pin_var.get()
                if not pin:
                    messagebox.showerror("Fehler", "Bitte geben Sie eine PIN ein!")
                    return
                
                # Prüfe PIN über DatabaseManager
                if self.db_manager.verify_user_pin(pin):
                    dialog.destroy()
                    self.logger.info("PIN korrekt - Zugriff gewährt")
                    
                    # Starte Überwachung neu wenn sie vorher aktiv war
                    if restart_monitoring:
                        self.root.after(1000, self._start_monitoring)
                    
                    messagebox.showinfo("Erfolg", "Authentifizierung erfolgreich!")
                else:
                    self.logger.warning("Falsche PIN eingegeben - System wird gesperrt")
                    messagebox.showerror("Fehler", 
                        "Falsche PIN!\n\nDas System wird jetzt gesperrt.")
                    dialog.destroy()
                    
                    # Sperre System mit i3lock
                    try:
                        sp.run(["i3lock", "-c", "000000"], check=False)
                    except FileNotFoundError:
                        self.logger.error("i3lock nicht gefunden - verwende systemctl suspend")
                        sp.run(["systemctl", "suspend"], check=False)
            
            tk.Button(dialog, text="✓ PIN bestätigen", 
                     command=verify_and_close,
                     font=('Arial', 12), bg='green', fg='white',
                     padx=20, pady=10).pack(pady=20)
            
            pin_entry.bind('<Return>', lambda e: verify_and_close())
            
            #Timeout-Counter (60 Sekunden)
            timeout_counter = [60]
            timeout_label = tk.Label(dialog, text=f"Timeout in {timeout_counter[0]}s",
                                    font=('Arial', 9), fg='gray')
            timeout_label.pack(pady=5)
            
            def update_timeout():
                timeout_counter[0] -= 1
                if timeout_counter[0] > 0:
                    timeout_label.config(text=f"Timeout in {timeout_counter[0]}s")
                    dialog.after(1000, update_timeout)
                else:
                    self.logger.warning("Timeout - System wird gesperrt")
                    messagebox.showerror("Timeout", "Zeit abgelaufen!\n\nDas System wird gesperrt.")
                    dialog.destroy()
                    try:
                        sp.run(["i3lock", "-c", "000000"], check=False)
                    except FileNotFoundError:
                        sp.run(["systemctl", "suspend"], check=False)
            
            dialog.after(1000, update_timeout)
            
        except Exception as e:
            self.logger.error(f"Fehler beim Anzeigen des Sicherheitsdialogs: {e}")
    
    # Überwachungsfunktionen
    def _start_monitoring(self):
        """Startet die Überwachung"""
        try:
            self.monitoring_active = True
            
            # Kamera starten
            if self.camera_manager.is_available:
                if self.camera_manager.start():
                    self.ui.add_mouse_log("Kamera-Überwachung gestartet")
                else:
                    self.ui.add_mouse_log("Kamera-Start fehlgeschlagen")
            
            # Mausüberwachung starten
            if self.pattern_model:
                start_mouse_monitoring()
                self.ui.add_mouse_log("Maus-Überwachung gestartet")
            
            self.ui.add_mouse_log("Überwachung gestartet")
            self.ui.update_monitoring_button(True)
            
            # In Tray minimieren
            if not hasattr(self, '_test_mode'):
                self._minimize_to_tray()
            
            self.logger.info("Überwachung gestartet")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Starten der Überwachung: {e}")
            messagebox.showerror("Fehler", f"Überwachung konnte nicht gestartet werden: {e}")
    
    def _stop_monitoring(self):
        """Stoppt die Überwachung"""
        try:
            self.monitoring_active = False
            
            # Kamera stoppen
            self.camera_manager.stop()
            
            # Mausüberwachung stoppen
            stop_mouse_monitoring()
            
            self.ui.add_mouse_log("Überwachung gestoppt")
            self.ui.update_monitoring_button(False)
            
            self.logger.info("Überwachung gestoppt")
            
        except Exception as e:
            self.logger.error(f"Fehler beim Stoppen der Überwachung: {e}")
    
    # Tray-Funktionen
    def _minimize_to_tray(self):
        """Minimiert die Anwendung in die Systemleiste"""
        try:
            # Verstecke Hauptfenster
            self.root.withdraw()
            
            # Erstelle Tray-Icon
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
    
    def _restore_from_tray(self):
        """Stellt die Anwendung aus der Systemleiste wieder her"""
        # Prüfe Session-Zeit
        if time.time() - self.session_start > Config.MAX_SESSION_DURATION:
            messagebox.showwarning("Session abgelaufen", 
                                 "Die Session ist abgelaufen. Bitte starten Sie TuxGuard neu.")
            self._quit_application()
            return
        
        # PIN-Dialog anzeigen
        pin_dialog = PinDialog(self.root, "Anwendung wiederherstellen", 
                              "PIN eingeben um die Anwendung zu öffnen:")
        pin = pin_dialog.show()
        
        if pin and self.db_manager.verify_user_pin(pin):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if self.tray_icon:
                self.tray_icon.stop()
            self.logger.info("Anwendung aus Tray wiederhergestellt")
        else:
            messagebox.showerror("Fehler", "Falsche PIN!")
    
    def _toggle_monitoring_from_tray(self):
        """Schaltet Überwachung aus Tray um"""
        self.root.after(0, self._toggle_monitoring)
    
    def _quit_from_tray(self):
        """Beendet Anwendung aus Tray"""
        self.root.after(0, self._show_quit_pin_dialog)
    
    def _show_quit_pin_dialog(self):
        """Zeigt PIN-Dialog zum Beenden"""
        pin_dialog = PinDialog(self.root, "Anwendung beenden", 
                              "PIN eingeben um TuxGuard zu beenden:")
        pin = pin_dialog.show()
        
        if pin and self.db_manager.verify_user_pin(pin):
            self._quit_application()
        else:
            messagebox.showerror("Fehler", "Falsche PIN!")
    
    # Anwendungsende
    def _on_closing(self):
        """Wird beim Schließen des Hauptfensters aufgerufen"""
        if self.monitoring_active:
            # Bei aktiver Überwachung in Tray minimieren
            self._minimize_to_tray()
        else:
            # Sonst direkt beenden
            self._quit_application()
    
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
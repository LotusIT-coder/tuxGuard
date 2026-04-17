#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Camera Module
Kameraüberwachung und Gesichtserkennung
"""

import cv2
import os
import time
import threading
import subprocess as sp
import tempfile
import traceback
import logging
import numpy as np
from pathlib import Path
from typing import Optional, Callable, List, Tuple
from threading import Timer

import face_recognition
import tkinter as tk
from tkinter import messagebox, Toplevel, Label
from PIL import Image, ImageTk

from config import Config
from database import DatabaseManager

logger = logging.getLogger('TuxGuard.Camera')

class CameraError(Exception):
    """Benutzerdefinierte Exception für Kamerafehler"""
    pass

class CameraManager:
    """Verwaltet Kamerazugriff und Gesichtserkennung"""
    
    def __init__(self, parent_window: tk.Tk, database_manager: DatabaseManager):
        self.parent_window = parent_window
        self.db_manager = database_manager
        
        # Kamera-Status
        self.is_available = False
        self.is_active = False
        self.active_event = threading.Event()
        
        # Überwachung
        self.monitor_active = False
        self.monitor_thread = None
        
        # Kamera-Hardware
        self.video_capture = None
        self.camera_thread = None
        
        # Lock-Datei
        self.lock_file = Config.CAMERA_LOCK_FILE
        
        # Dialoge
        self.permission_dialog = None
        
        # Callbacks
        self.user_recognized_callback: Optional[Callable[[str], None]] = None
        self.unauthorized_access_callback: Optional[Callable[[], None]] = None
        
        # Initialisiere Kamera-Verfügbarkeit
        self.is_available = self._check_availability()
    
    def set_callbacks(self, user_recognized: Optional[Callable[[str], None]] = None,
                     unauthorized_access: Optional[Callable[[], None]] = None):
        """Setzt Callback-Funktionen für Ereignisse"""
        self.user_recognized_callback = user_recognized
        self.unauthorized_access_callback = unauthorized_access
    
    def _check_availability(self) -> bool:
        """Prüft, ob eine Kamera verfügbar ist"""
        try:
            for i in range(5):
                device_path = f"/dev/video{i}"
                if os.path.exists(device_path):
                    cap = cv2.VideoCapture(i)
                    if cap.isOpened():
                        ret, _ = cap.read()
                        cap.release()
                        if ret:
                            logger.info(f"Kamera gefunden: {device_path}")
                            return True
            logger.warning("Keine verfügbare Kamera gefunden")
            return False
        except Exception as e:
            logger.error(f"Fehler beim Prüfen der Kamera-Verfügbarkeit: {e}")
            return False
    
    def diagnose(self) -> str:
        """Führt eine Kamera-Diagnose durch und gibt den Bericht zurück"""
        report = ["=== KAMERA-DIAGNOSE ==="]
        
        # Verfügbare Geräte
        devices = [f'/dev/video{i}' for i in range(5) if os.path.exists(f'/dev/video{i}')]
        report.append(f"1. Verfügbare Geräte: {devices}")
        
        # v4l2-ctl Information
        try:
            result = sp.run(['v4l2-ctl', '--list-devices'], 
                          capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                report.append(f"2. v4l2-ctl Ausgabe:\n{result.stdout}")
            else:
                report.append("2. v4l2-ctl nicht verfügbar oder Fehler")
        except (sp.TimeoutExpired, FileNotFoundError):
            report.append("2. v4l2-ctl nicht installiert")
        
        # Prozesse die Kamera verwenden
        try:
            result = sp.run(['lsof', '/dev/video*'], 
                          capture_output=True, text=True, timeout=5)
            if result.stdout.strip():
                report.append(f"3. Kamera wird verwendet von:\n{result.stdout}")
            else:
                report.append("3. Kamera wird von keinem Prozess verwendet")
        except (sp.TimeoutExpired, FileNotFoundError):
            report.append("3. lsof nicht verfügbar")
        
        report.append("=== ENDE KAMERA-DIAGNOSE ===")
        
        diagnosis = "\n".join(report)
        logger.info(f"Kamera-Diagnose durchgeführt:\n{diagnosis}")
        return diagnosis
    
    def _create_lock(self) -> bool:
        """Erstellt eine Lock-Datei für die Kamera"""
        try:
            with open(self.lock_file, 'w') as f:
                f.write(f"TuxGuard Camera Lock - PID: {os.getpid()}\n")
                f.write(f"Timestamp: {time.time()}\n")
            logger.info(f"Kamera-Lock erstellt: {self.lock_file}")
            return True
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Kamera-Lock: {e}")
            return False
    
    def _remove_lock(self):
        """Entfernt die Kamera-Lock-Datei"""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
                logger.info(f"Kamera-Lock entfernt: {self.lock_file}")
        except Exception as e:
            logger.error(f"Fehler beim Entfernen der Kamera-Lock: {e}")
    
    def _check_access(self) -> bool:
        """Prüft, ob die Kamera zugänglich ist"""
        try:
            if os.path.exists(Config.CAMERA_DEVICE):
                fd = os.open(Config.CAMERA_DEVICE, os.O_RDWR | os.O_NONBLOCK)
                os.close(fd)
                return True
        except (OSError, IOError) as e:
            if getattr(e, "errno", None) == 16:  # EBUSY
                logger.warning(f"Kamera ist belegt: {e}")
                return False
            logger.error(f"Fehler beim Kamera-Zugriff: {e}")
            return False
        return True
    
    def _monitor_access(self):
        """Überwacht Kamera-Zugriff und zeigt Dialog bei Bedarf"""
        while self.monitor_active:
            try:
                time.sleep(2)
                if not self._check_access():
                    self.parent_window.after(0, self._show_permission_dialog)
            except Exception as e:
                logger.error(f"Fehler in Kameraüberwachung: {e}")
                time.sleep(5)
    
    def _show_permission_dialog(self):
        """Zeigt Dialog für Kamera-Berechtigung"""
        if self.permission_dialog and self.permission_dialog.winfo_exists():
            return
        
        self.permission_dialog = Toplevel(self.parent_window)
        dlg = self.permission_dialog
        dlg.title("Kamera-Zugriff erkannt")
        dlg.geometry(Config.CAMERA_PERMISSION_DIALOG_GEOMETRY)
        dlg.transient(self.parent_window)
        dlg.grab_set()
        
        # Zentriere Dialog
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        x = (sw - 400) // 2
        y = (sh - 250) // 2
        dlg.geometry(f"400x250+{x}+{y}")
        dlg.attributes('-topmost', True)
        dlg.focus_force()
        
        Label(dlg, text="Ein anderes Programm versucht,\ndie Kamera zu nutzen.",
              font=('Arial', 12, 'bold')).pack(pady=20)
        Label(dlg, text="Möchten Sie dies erlauben?\n\nTuxGuard gibt die Kamera\nvorübergehend frei.",
              font=('Arial', 10)).pack(pady=10)
        
        def allow_camera():
            dlg.destroy()
            self.permission_dialog = None
            self._temporarily_release_camera()
        
        def deny_camera():
            dlg.destroy()
            self.permission_dialog = None
        
        button_frame = tk.Frame(dlg)
        button_frame.pack(pady=20)
        tk.Button(button_frame, text="Erlauben", command=allow_camera).pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="Verweigern", command=deny_camera).pack(side=tk.LEFT, padx=10)
    
    def _temporarily_release_camera(self):
        """Gibt die Kamera temporär frei"""
        if self.video_capture and self.video_capture.isOpened():
            self.video_capture.release()
            logger.info("Kamera temporär freigegeben")
        
        # Wiederaufnahme nach 30 Sekunden
        Timer(30.0, self._resume_monitoring).start()
    
    def _resume_monitoring(self):
        """Nimmt Kamera-Überwachung wieder auf"""
        if self.active_event.is_set():
            self.start()
            logger.info("Kamera-Überwachung wieder aufgenommen")
    
    def start_monitoring(self):
        """Startet die Kamera-Zugriff-Überwachung"""
        if not self.monitor_active:
            self.monitor_active = True
            self._create_lock()
            self.monitor_thread = threading.Thread(
                target=self._monitor_access, 
                daemon=True, 
                name="CameraMonitor"
            )
            self.monitor_thread.start()
            logger.info("Kamera-Überwachung gestartet")
    
    def stop_monitoring(self):
        """Stoppt die Kamera-Zugriff-Überwachung"""
        self.monitor_active = False
        self._remove_lock()
        if self.permission_dialog:
            self.permission_dialog.destroy()
            self.permission_dialog = None
        logger.info("Kamera-Überwachung gestoppt")
    
    def start(self) -> bool:
        """Startet die Kamera-Aufnahme"""
        if not self.is_available:
            messagebox.showinfo(
                "Kamera nicht verfügbar",
                "Keine Kamera verfügbar.\nNur die Mausbewegungserkennung ist aktiv."
            )
            return False
        
        self.active_event.set()
        self.start_monitoring()
        
        # Initialisiere Kamera
        self.video_capture = cv2.VideoCapture(0)
        
        # Versuche Kamera zu öffnen
        for attempt in range(Config.CAMERA_RETRY_ATTEMPTS):
            if self.video_capture.open(0):
                logger.info(f"Kamera erfolgreich geöffnet (Versuch {attempt + 1})")
                break
            time.sleep(Config.CAMERA_RETRY_DELAY)
        else:
            logger.error("Kamera konnte nicht geöffnet werden")
            messagebox.showwarning(
                "Kamera-Warnung",
                "Kamera konnte nicht geöffnet werden. Überwachung läuft weiter."
            )
            return False
        
        # Starte Kamera-Thread
        self.camera_thread = threading.Thread(
            target=self._run_camera, 
            daemon=True, 
            name="CameraCapture"
        )
        self.camera_thread.start()
        self.is_active = True
        
        logger.info("Kamera-Aufnahme gestartet")
        return True
    
    def stop(self):
        """Stoppt die Kamera-Aufnahme"""
        self.active_event.clear()
        self.is_active = False
        
        if self.video_capture:
            try:
                self.video_capture.release()
                logger.info("Kamera freigegeben")
            except Exception as e:
                logger.error(f"Fehler beim Freigeben der Kamera: {e}")
        
        cv2.destroyAllWindows()
        self.stop_monitoring()
        
        logger.info("Kamera-Aufnahme gestoppt")
    
    def _run_camera(self):
        """Hauptschleife für Kamera-Aufnahme und Gesichtserkennung"""
        # Verwende separate DB-Verbindung für Thread
        with DatabaseManager() as db:
            try:
                last_state = None  # None, 'authorized', 'unauthorized'
                state_since = time.time()
                state_candidate = None
                GRACE_PERIOD = 1.0  # seconds (reduced for faster security response)
                while self.active_event.is_set():
                    ret, frame = self.video_capture.read()
                    if not ret:
                        logger.warning("Kein Frame von Kamera empfangen")
                        break
                    
                    # Konvertiere zu RGB für face_recognition
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    # Erkenne Gesichter
                    face_locations = face_recognition.face_locations(rgb_frame)
                    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                    
                    user_recognized = False
                    recognized_user = None

                    if face_encodings:
                        # Lade alle bekannten Gesichtskodierungen
                        known_encodings = db.get_all_face_encodings()

                        for face_encoding in face_encodings:
                            for name, known_encoding, desc in known_encodings:
                                # Vergleiche Gesichtskodierungen
                                matches = face_recognition.compare_faces([known_encoding], face_encoding)
                                if matches[0]:
                                    user_recognized = True
                                    recognized_user = name
                                    logger.info(f"Benutzer erkannt: {name}")
                                    break

                            if user_recognized:
                                break

                    # Debounce logic: only change state if new state persists for GRACE_PERIOD
                    current_state = 'authorized' if user_recognized else 'unauthorized'
                    if state_candidate is None or current_state != state_candidate:
                        state_candidate = current_state
                        state_since = time.time()
                    elif time.time() - state_since >= GRACE_PERIOD and last_state != state_candidate:
                        # State has been stable for GRACE_PERIOD, trigger callback
                        if state_candidate == 'authorized':
                            if self.user_recognized_callback:
                                self.user_recognized_callback(recognized_user)
                        else:
                            if self.unauthorized_access_callback:
                                if face_encodings:
                                    logger.warning("Unbekanntes Gesicht erkannt")
                                else:
                                    logger.warning("Kein Gesicht erkannt (Kamera abgedeckt oder niemand im Bild)")
                                self.unauthorized_access_callback()
                        last_state = state_candidate
                    
                    # Kleine Pause um CPU zu schonen
                    time.sleep(0.1)
            
            except Exception as e:
                logger.error(f"Fehler in Kamera-Thread: {e}\n{traceback.format_exc()}")
    
    def capture_image(self) -> Optional[str]:
        """Nimmt ein Bild mit der Webcam auf und gibt den Pfad zurück"""
        cam = cv2.VideoCapture(0)
        if not cam.isOpened():
            messagebox.showerror("Fehler", "Kamera konnte nicht geöffnet werden.")
            return None
        
        win = Toplevel(self.parent_window)
        win.title("Webcam - Foto aufnehmen")
        win.geometry("700x550")
        win.transient(self.parent_window)
        win.grab_set()
        
        label_main = Label(win)
        label_main.pack(pady=10)
        
        captured = {'img': None}
        closed = {'done': False}
        
        def show_frame():
            if closed['done']:
                return
            ret, frame = cam.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_tk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
                label_main.img_tk = img_tk
                label_main.configure(image=img_tk)
            if not closed['done']:
                label_main.after(20, show_frame)
        
        show_frame()
        
        def capture():
            ret, frame = cam.read()
            if ret:
                if cam.isOpened():
                    cam.release()
                closed['done'] = True
                win.destroy()
                
                # Speichere Bild in temporärer Datei
                tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                cv2.imwrite(tmp.name, frame)
                captured['img'] = tmp.name
                logger.info(f"Bild aufgenommen: {tmp.name}")
            else:
                messagebox.showerror("Fehler", "Foto konnte nicht aufgenommen werden.")
        
        def on_abort():
            if cam.isOpened():
                cam.release()
            closed['done'] = True
            win.destroy()
        
        tk.Button(win, text="Foto aufnehmen", command=capture).pack(pady=10)
        tk.Button(win, text="Abbrechen", command=on_abort).pack(pady=5)
        win.protocol("WM_DELETE_WINDOW", on_abort)
        
        self.parent_window.wait_window(win)
        
        if cam.isOpened():
            cam.release()
        
        return captured['img']
    
    def test_camera(self) -> bool:
        """Zeigt einen Live-Kamera-Test mit Benutzer-Erkennungsanzeige"""
        cap = None
        running = True

        def stop_test():
            nonlocal running, cap
            running = False
            if cap and cap.isOpened():
                cap.release()
            if preview_window.winfo_exists():
                preview_window.destroy()

        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                messagebox.showerror("Kamera-Test", "Kamera konnte nicht geöffnet werden.")
                return False

            preview_window = Toplevel(self.parent_window)
            preview_window.title("Kamera-Test")
            preview_window.geometry("800x600")
            preview_window.configure(bg="#1d1d1d")
            preview_window.protocol("WM_DELETE_WINDOW", stop_test)

            info_label = Label(
                preview_window,
                text="Kamera-Test läuft...",
                font=("Arial", 12, "bold"),
                fg="#ffffff",
                bg="#1d1d1d"
            )
            info_label.pack(pady=10)

            canvas = Label(preview_window, bg="#000000")
            canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            status_label = Label(
                preview_window,
                text="Keine Benutzer erkannt",
                font=("Arial", 11),
                fg="#ff9800",
                bg="#1d1d1d"
            )
            status_label.pack(pady=(0, 10))

            try:
                known_faces = self.db_manager.get_all_face_encodings()
                known_names = [name for name, _, _ in known_faces]
                known_encodings = [encoding for _, encoding, _ in known_faces]
            except Exception as e:
                known_faces = []
                known_names = []
                known_encodings = []
                logger.warning(f"Gesichtsdaten konnten nicht geladen werden: {e}")

            def update_frame():
                if not running:
                    return

                ret, frame = cap.read()
                if not ret:
                    status_label.config(text="Kein Kamerasignal", fg="#ff5252")
                    preview_window.after(100, update_frame)
                    return

                detection_text = "Keine Benutzer erkannt"
                detection_color = "#ff9800"

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_frame)
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                face_names = []

                if face_encodings and known_encodings:
                    face_names = []
                    for face_encoding in face_encodings:
                        matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.5)
                        name = "Unbekannt"
                        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                        if len(face_distances) > 0:
                            best_match_index = np.argmin(face_distances)
                            if matches[best_match_index]:
                                name = known_names[best_match_index]
                        face_names.append(name)

                    recognized = [n for n in face_names if n != "Unbekannt"]
                    if recognized:
                        detection_text = f"Erkannt: {', '.join(sorted(set(recognized)))}"
                        detection_color = "#4caf50"
                else:
                    face_names = ["Unbekannt"] * len(face_locations)

                for (top, right, bottom, left), name in zip(face_locations, face_names):
                    color = (76, 175, 80) if name != "Unbekannt" else (255, 82, 82)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, bottom - 20), (right, bottom), color, cv2.FILLED)
                    cv2.putText(frame, name, (left + 4, bottom - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                img.thumbnail((780, 500), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image=img)

                canvas.configure(image=photo)
                canvas.image = photo
                status_label.config(text=detection_text, fg=detection_color)

                preview_window.after(30, update_frame)

            update_frame()
            info_label.config(text="Kamera-Test läuft – Fenster schließen zum Beenden")
            preview_window.transient(self.parent_window)
            preview_window.grab_set()
            self.parent_window.wait_window(preview_window)

            logger.info("Kamera-Test gestartet")
            return True

        except Exception as e:
            logger.error(f"Kamera-Test fehlgeschlagen: {e}")
            messagebox.showerror("Kamera-Test", f"Kamera-Test fehlgeschlagen: {e}")
            return False
        finally:
            if cap and cap.isOpened():
                cap.release()
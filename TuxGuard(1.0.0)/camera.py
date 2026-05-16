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
from typing import Callable, Dict, List, Optional, Tuple
from threading import Timer

from face_mediapipe import (
    load_image_file,
    face_locations as mp_face_locations,
    face_encodings as mp_face_encodings,
    face_emotions as mp_face_emotions,
    compare_faces,
    face_distance,
)
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
        self.camera_after_id = None
        self.last_state = None
        self.state_since = 0.0
        self.state_candidate = None
        
        # Lock-Datei
        self.lock_file = Config.CAMERA_LOCK_FILE
        
        # Dialoge
        self.permission_dialog = None

        # Emotions-Overlay (rein visuell, keine Persistenz)
        self.emotion_overlay_enabled = bool(getattr(Config, "EMOTION_OVERLAY_ENABLED", True))
        self.emotion_min_confidence = float(getattr(Config, "EMOTION_MIN_CONFIDENCE", 0.35))
        self.emotion_smoothing_alpha = float(getattr(Config, "EMOTION_SMOOTHING_ALPHA", 0.35))
        self.emotion_track_max_distance = float(getattr(Config, "EMOTION_TRACK_MAX_DISTANCE", 90.0))
        self.emotion_track_ttl_seconds = float(getattr(Config, "EMOTION_TRACK_TTL_SECONDS", 1.5))
        self._emotion_tracks: Dict[int, Dict[str, object]] = {}
        self._next_emotion_track_id = 1
        
        # Callbacks
        self.user_recognized_callback: Optional[Callable[[str], None]] = None
        self.unauthorized_access_callback: Optional[Callable[[], None]] = None
        self.preview_updated_callback: Optional[Callable[[Image.Image, str, str], None]] = None
        # Wird auf JEDEM Frame mit erkanntem legitimen Nutzer ausgelöst (kein Logging,
        # nur Heartbeat zum Zurücksetzen des Sperr-Timers).
        self.user_seen_callback: Optional[Callable[[str], None]] = None
        
        # Initialisiere Kamera-Verfügbarkeit
        self.is_available = self._check_availability()
    
    def set_callbacks(self, user_recognized: Optional[Callable[[str], None]] = None,
                     unauthorized_access: Optional[Callable[[], None]] = None,
                     preview_updated: Optional[Callable[[Image.Image, str, str], None]] = None,
                     user_seen: Optional[Callable[[str], None]] = None):
        """Setzt Callback-Funktionen für Ereignisse.

        ``user_seen`` wird für jeden Frame ausgelöst, in dem ein legitimer Nutzer
        erkannt wurde (Heartbeat). ``user_recognized`` feuert weiterhin nur bei
        Statuswechseln (fürs Logging).
        """
        self.user_recognized_callback = user_recognized
        self.unauthorized_access_callback = unauthorized_access
        self.preview_updated_callback = preview_updated
        self.user_seen_callback = user_seen

    def set_emotion_overlay_enabled(self, enabled: bool):
        """Aktiviert/deaktiviert die Emotionsanzeige im Live-Overlay zur Laufzeit."""
        self.emotion_overlay_enabled = bool(enabled)
        self._emotion_tracks.clear()
        logger.info("Emotions-Overlay %s", "aktiv" if self.emotion_overlay_enabled else "inaktiv")
    
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
        dlg.minsize(380, 220)
        dlg.transient(self.parent_window)
        dlg.grab_set()
        
        # Zentriere Dialog
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        x = (sw - 400) // 2
        y = (sh - 250) // 2
        dlg.geometry(f"400x250+{x}+{y}")
        dlg.attributes('-topmost', True)
        dlg.focus_force()
        dlg.resizable(True, True)
        
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
                "Keine Kamera verfügbar."
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
        
        self.is_active = True
        self.last_state = None
        self.state_since = time.time()
        self.state_candidate = None
        self._emotion_tracks.clear()
        self._next_emotion_track_id = 1
        self.camera_after_id = self.parent_window.after(0, self._run_camera_step)
        
        logger.info("Kamera-Aufnahme gestartet")
        return True
    
    def stop(self):
        """Stoppt die Kamera-Aufnahme"""
        self.active_event.clear()
        self.is_active = False
        if self.camera_after_id is not None:
            try:
                self.parent_window.after_cancel(self.camera_after_id)
            except Exception:
                pass
            self.camera_after_id = None
        
        if self.video_capture:
            try:
                self.video_capture.release()
                logger.info("Kamera freigegeben")
            except Exception as e:
                logger.error(f"Fehler beim Freigeben der Kamera: {e}")
        
        cv2.destroyAllWindows()
        self.stop_monitoring()
        self._emotion_tracks.clear()
        
        logger.info("Kamera-Aufnahme gestoppt")

    def _build_preview_image(
        self,
        frame: np.ndarray,
        face_locations: List[Tuple[int, int, int, int]],
        face_names: List[str],
        face_emotions: Optional[List[Dict[str, object]]] = None,
    ) -> Image.Image:
        """Erstellt eine annotierte Vorschau für die Monitoring-UI."""
        preview_frame = frame.copy()
        emotions = face_emotions or []

        for index, (top, right, bottom, left) in enumerate(face_locations):
            name = face_names[index] if index < len(face_names) else "Unbekannt"
            emotion_text = self._format_emotion_label(
                emotions[index] if index < len(emotions) else None
            )
            display_name = name if not emotion_text else f"{name} | {emotion_text}"
            color = (76, 175, 80) if name != "Unbekannt" else (255, 82, 82)
            cv2.rectangle(preview_frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(
                preview_frame,
                (left, max(bottom - 24, top)),
                (right, bottom),
                color,
                cv2.FILLED,
            )
            cv2.putText(
                preview_frame,
                display_name,
                (left + 4, max(bottom - 7, top + 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                1,
            )

        display_rgb = cv2.cvtColor(preview_frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(display_rgb)
        image.thumbnail((360, 220), Image.Resampling.LANCZOS)
        return image

    @staticmethod
    def _bbox_center(box: Tuple[int, int, int, int]) -> Tuple[float, float]:
        top, right, bottom, left = box
        return ((left + right) / 2.0, (top + bottom) / 2.0)

    @staticmethod
    def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    def _summarize_votes(self, votes: Dict[str, float]) -> Tuple[str, float]:
        if not votes:
            return "unknown", 0.0
        filtered = {label: max(0.0, float(value)) for label, value in votes.items() if label != "unknown"}
        if not filtered:
            return "unknown", 0.0
        total = float(sum(filtered.values()))
        if total <= 1e-8:
            return "unknown", 0.0
        label, value = max(filtered.items(), key=lambda item: item[1])
        confidence = float(max(0.0, min(1.0, value / total)))
        if confidence < self.emotion_min_confidence:
            return "unknown", confidence
        return label, confidence

    def _smooth_emotions(
        self,
        face_locations: List[Tuple[int, int, int, int]],
        raw_emotions: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        if not self.emotion_overlay_enabled:
            return [{"label": "unknown", "confidence": 0.0, "source": "disabled"} for _ in face_locations]

        now = time.time()
        alpha = float(max(0.0, min(1.0, self.emotion_smoothing_alpha)))
        ttl = float(max(0.1, self.emotion_track_ttl_seconds))
        max_distance = float(max(10.0, self.emotion_track_max_distance))

        stale_ids = [
            track_id
            for track_id, track in self._emotion_tracks.items()
            if now - float(track.get("last_seen", 0.0)) > ttl
        ]
        for track_id in stale_ids:
            self._emotion_tracks.pop(track_id, None)

        used_track_ids = set()
        smoothed: List[Dict[str, object]] = []

        for index, box in enumerate(face_locations):
            center = self._bbox_center(box)

            selected_track_id = None
            selected_distance = float("inf")
            for track_id, track in self._emotion_tracks.items():
                if track_id in used_track_ids:
                    continue
                track_center = track.get("center")
                if not isinstance(track_center, tuple) or len(track_center) != 2:
                    continue
                dist = self._distance(center, track_center)
                if dist <= max_distance and dist < selected_distance:
                    selected_distance = dist
                    selected_track_id = track_id

            if selected_track_id is None:
                selected_track_id = self._next_emotion_track_id
                self._next_emotion_track_id += 1
                self._emotion_tracks[selected_track_id] = {
                    "center": center,
                    "last_seen": now,
                    "votes": {},
                }

            track = self._emotion_tracks[selected_track_id]
            used_track_ids.add(selected_track_id)
            track["center"] = center
            track["last_seen"] = now

            votes: Dict[str, float] = dict(track.get("votes", {}))
            for label in list(votes.keys()):
                votes[label] = float(votes[label]) * (1.0 - alpha)
                if votes[label] < 1e-5:
                    votes.pop(label, None)

            raw = raw_emotions[index] if index < len(raw_emotions) else {}
            label = str(raw.get("label", "unknown") or "unknown")
            confidence = float(raw.get("confidence", 0.0) or 0.0)
            if label != "unknown" and confidence > 0.0:
                votes[label] = votes.get(label, 0.0) + alpha * confidence

            track["votes"] = votes
            smoothed_label, smoothed_confidence = self._summarize_votes(votes)
            smoothed.append(
                {
                    "label": smoothed_label,
                    "confidence": smoothed_confidence,
                    "source": "smoothed",
                }
            )

        return smoothed

    def _format_emotion_label(self, emotion: Optional[Dict[str, object]]) -> str:
        if not emotion:
            return ""
        label = str(emotion.get("label", "unknown") or "unknown")
        confidence = float(emotion.get("confidence", 0.0) or 0.0)
        if label == "unknown" or confidence < self.emotion_min_confidence:
            return ""
        german_labels = {
            "happy": "Freude",
            "sad": "Traurig",
            "angry": "Wuetend",
            "surprised": "Ueberrascht",
            "fearful": "Aengstlich",
            "disgusted": "Angeekelt",
            "neutral": "Neutral",
        }
        label = german_labels.get(label, label)
        percent = int(round(confidence * 100.0))
        return f"{label} {percent}%"
    
    def _run_camera_step(self):
        """Verarbeitet einen Kamera-Schritt im Tk-Hauptthread."""
        if not self.active_event.is_set() or not self.video_capture:
            self.camera_after_id = None
            return

        try:
            ret, frame = self.video_capture.read()
            if not ret:
                logger.warning("Kein Frame von Kamera empfangen")
                self.camera_after_id = self.parent_window.after(250, self._run_camera_step)
                return

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = mp_face_locations(rgb_frame)
            face_encodings = mp_face_encodings(rgb_frame, face_locations)
            raw_emotions = (
                mp_face_emotions(rgb_frame, min_confidence=self.emotion_min_confidence)
                if self.emotion_overlay_enabled
                else []
            )
            face_emotions = self._smooth_emotions(face_locations, raw_emotions)

            user_recognized = False
            recognized_user = None
            face_names: List[str] = []

            if face_encodings:
                known_encodings = self.db_manager.get_all_face_encodings()

                for face_encoding in face_encodings:
                    current_name = "Unbekannt"
                    for name, known_encoding, desc in known_encodings:
                        matches = compare_faces([known_encoding], face_encoding)
                        if matches and matches[0]:
                            user_recognized = True
                            recognized_user = name
                            current_name = name
                            logger.info(f"Benutzer erkannt: {name}")
                            break
                    face_names.append(current_name)

                    if user_recognized:
                        break

            current_state = 'authorized' if user_recognized else 'unauthorized'
            grace_period = 1.0

            if face_locations:
                if user_recognized and recognized_user:
                    preview_status = f"Legitimer Nutzer erkannt: {recognized_user}"
                    preview_level = "SUCCESS"
                elif face_names:
                    preview_status = "Gesicht erkannt: Unbekannt"
                    preview_level = "ERROR"
                else:
                    preview_status = "Gesicht erkannt"
                    preview_level = "INFO"
            else:
                preview_status = "Kein Gesicht erkannt"
                preview_level = "WARNING"

            if self.preview_updated_callback:
                preview_image = self._build_preview_image(
                    frame,
                    face_locations,
                    face_names,
                    face_emotions=face_emotions,
                )
                self.preview_updated_callback(preview_image, preview_status, preview_level)

            # Heartbeat: jeder Frame mit legitimem Nutzer setzt den Sperr-Timer zurück,
            # auch wenn die Erkennung nur kurz war (kein Warten auf Grace-Period).
            if user_recognized and recognized_user and self.user_seen_callback:
                try:
                    self.user_seen_callback(recognized_user)
                except Exception as cb_exc:
                    logger.debug("user_seen_callback fehlgeschlagen: %s", cb_exc)

            if self.state_candidate is None or current_state != self.state_candidate:
                self.state_candidate = current_state
                self.state_since = time.time()
            elif time.time() - self.state_since >= grace_period and self.last_state != self.state_candidate:
                if self.state_candidate == 'authorized':
                    if self.user_recognized_callback:
                        self.user_recognized_callback(recognized_user)
                else:
                    if self.unauthorized_access_callback:
                        if face_encodings:
                            logger.warning("Unbekanntes Gesicht erkannt")
                        else:
                            logger.warning("Kein Gesicht erkannt (Kamera abgedeckt oder niemand im Bild)")
                        self.unauthorized_access_callback()
                self.last_state = self.state_candidate

        except Exception as e:
            logger.error(f"Fehler in Kameraüberwachung: {e}\n{traceback.format_exc()}")

        self.camera_after_id = self.parent_window.after(100, self._run_camera_step)
    
    def capture_image(self) -> Optional[str]:
        """Nimmt ein Bild mit der Webcam auf und gibt den Pfad zurück.

        Während der Vorschau wird live angezeigt, ob ein Gesicht erkannt wird,
        damit der Nutzer das Foto erst auslöst, wenn die Erkennung stabil ist.
        """
        cam = cv2.VideoCapture(0)
        if not cam.isOpened():
            messagebox.showerror("Fehler", "Kamera konnte nicht geöffnet werden.")
            return None

        win = Toplevel(self.parent_window)
        win.title("Webcam - Foto aufnehmen")
        win.geometry("760x620")
        win.minsize(560, 460)
        win.resizable(True, True)
        win.transient(self.parent_window)
        win.grab_set()
        win.configure(bg="#1d1d1d")

        content = tk.Frame(win, bg="#1d1d1d")
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        Label(
            content,
            text="Positionieren Sie Ihr Gesicht im Bild (frontal oder seitlich).",
            font=("Arial", 11, "bold"),
            fg="#ffffff",
            bg="#1d1d1d",
        ).pack(anchor="w")

        label_main = Label(content, bg="#000000")
        label_main.pack(fill=tk.BOTH, expand=True, pady=(8, 4))

        status_label = Label(
            content,
            text="Suche Gesicht …",
            font=("Arial", 11, "bold"),
            fg="#ff9800",
            bg="#1d1d1d",
        )
        status_label.pack(anchor="w", pady=(0, 6))

        captured = {"img": None}
        closed = {"done": False}
        last_state = {"face_found": False}
        # Button-Referenz wird unten gesetzt; type-loose zur Vermeidung von Forward-Refs.
        capture_button: dict = {"btn": None}

        def show_frame():
            if closed["done"]:
                return
            ret, frame = cam.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                try:
                    locations = mp_face_locations(rgb)
                except Exception as exc:
                    locations = []
                    logger.debug("Live-Gesichtssuche fehlgeschlagen: %s", exc)

                # Boxen einzeichnen
                for (top, right, bottom, left) in locations:
                    color = (76, 175, 80)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

                if locations:
                    status_label.config(
                        text=f"✓ Gesicht erkannt ({len(locations)})",
                        fg="#4caf50",
                    )
                    if capture_button["btn"] is not None:
                        capture_button["btn"].config(state=tk.NORMAL)
                    last_state["face_found"] = True
                else:
                    status_label.config(
                        text="✗ Kein Gesicht erkannt – Position/Beleuchtung anpassen",
                        fg="#ff5252",
                    )
                    if capture_button["btn"] is not None:
                        capture_button["btn"].config(state=tk.NORMAL)  # Aufnahme bleibt möglich
                    last_state["face_found"] = False

                display_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(display_rgb)
                img.thumbnail((720, 460), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(image=img)
                label_main.img_tk = img_tk
                label_main.configure(image=img_tk)
            if not closed["done"]:
                label_main.after(80, show_frame)

        show_frame()

        def capture():
            ret, frame = cam.read()
            if not ret:
                messagebox.showerror("Fehler", "Foto konnte nicht aufgenommen werden.")
                return

            if not last_state["face_found"]:
                if not messagebox.askokcancel(
                    "Kein Gesicht erkannt",
                    "Im aktuellen Bild wurde kein Gesicht erkannt.\n"
                    "Foto trotzdem aufnehmen?",
                    parent=win,
                ):
                    return

            if cam.isOpened():
                cam.release()
            closed["done"] = True
            win.destroy()

            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            cv2.imwrite(tmp.name, frame)
            captured["img"] = tmp.name
            logger.info(f"Bild aufgenommen: {tmp.name}")

        def on_abort():
            if cam.isOpened():
                cam.release()
            closed["done"] = True
            win.destroy()

        button_frame = tk.Frame(content, bg="#1d1d1d")
        button_frame.pack(fill=tk.X, pady=(6, 0))
        capture_button["btn"] = tk.Button(
            button_frame, text="📷 Foto aufnehmen", command=capture
        )
        capture_button["btn"].pack(fill=tk.X, pady=(0, 6))
        tk.Button(button_frame, text="Abbrechen", command=on_abort).pack(fill=tk.X)
        win.protocol("WM_DELETE_WINDOW", on_abort)

        self.parent_window.wait_window(win)

        if cam.isOpened():
            cam.release()

        return captured["img"]
    
    def test_camera(self) -> bool:
        """Zeigt einen Live-Kamera-Test mit sichtbarer Gesichtserkennung"""
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
            preview_window.minsize(640, 480)
            preview_window.resizable(True, True)
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
                text="Kamerasignal wird geprüft",
                font=("Arial", 11),
                fg="#4caf50",
                bg="#1d1d1d"
            )
            status_label.pack(pady=(0, 10))

            try:
                known_faces = self.db_manager.get_all_face_encodings()
                known_names = [name for name, _, _ in known_faces]
                known_encodings = [encoding for _, encoding, _ in known_faces]
            except Exception as e:
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

                detection_text = "Kein Gesicht erkannt"
                detection_color = "#ff9800"

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = mp_face_locations(frame_rgb)
                face_encodings = mp_face_encodings(frame_rgb, face_locations)
                raw_emotions = (
                    mp_face_emotions(frame_rgb, min_confidence=self.emotion_min_confidence)
                    if self.emotion_overlay_enabled
                    else []
                )
                face_emotions = self._smooth_emotions(face_locations, raw_emotions)
                face_names = []

                for face_encoding in face_encodings:
                    name = "Unbekannt"
                    if known_encodings:
                        matches = compare_faces(known_encodings, face_encoding, tolerance=0.9)
                        face_distances = face_distance(known_encodings, face_encoding)
                        if len(face_distances) > 0:
                            best_match_index = int(np.argmin(face_distances))
                            if matches[best_match_index]:
                                name = known_names[best_match_index]
                    face_names.append(name)

                if face_locations:
                    if any(name != "Unbekannt" for name in face_names):
                        recognized = sorted({name for name in face_names if name != "Unbekannt"})
                        detection_text = f"Erkannt: {', '.join(recognized)}"
                        detection_color = "#4caf50"
                    elif face_names:
                        detection_text = "Gesicht erkannt: Unbekannt"
                        detection_color = "#ff5252"

                for index, (top, right, bottom, left) in enumerate(face_locations):
                    name = face_names[index] if index < len(face_names) else "Unbekannt"
                    emotion_text = self._format_emotion_label(
                        face_emotions[index] if index < len(face_emotions) else None
                    )
                    display_name = name if not emotion_text else f"{name} | {emotion_text}"
                    color = (76, 175, 80) if name != "Unbekannt" else (255, 82, 82)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    cv2.rectangle(frame, (left, max(bottom - 24, top)), (right, bottom), color, cv2.FILLED)
                    cv2.putText(
                        frame,
                        display_name,
                        (left + 4, max(bottom - 7, top + 15)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (0, 0, 0),
                        1,
                    )

                display_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(display_rgb)
                img.thumbnail((780, 500), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image=img)

                canvas.configure(image=photo)
                canvas.image = photo
                status_label.config(text=detection_text, fg=detection_color)

                preview_window.after(30, update_frame)

            update_frame()
            info_label.config(text="Kamera-Test mit Live-Gesichtserkennung")
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

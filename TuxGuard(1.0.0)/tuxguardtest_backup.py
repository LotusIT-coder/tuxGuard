
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import threading
import sqlite3
import hashlib
import hmac
import numpy as np
import cv2
import tempfile
import traceback
import subprocess as sp
from pathlib import Path
from threading import Timer

import tkinter as tk
from tkinter import simpledialog, filedialog, messagebox, Toplevel, Label, Entry, Button, Text, ttk

from PIL import Image, ImageDraw, ImageTk
import pystray

from pynput.mouse import Listener
import face_recognition
from tensorflow import keras

# externe Datei laut Projekt (nicht geändert)
from mouse_movement_recognition import (
    collect_data, preprocess_data, build_model, real_time_classification
)

# ----------------------------------------------------------------------
# Hilfsfunktionen: PIN-Hashing (vereinheitlicht)
# Format: "pbkdf2_sha256$ITER$SALT_HEX$HASH_HEX"
# Legacy-Support: falls in DB noch reiner SHA256 liegt, wird das erkannt.
# ----------------------------------------------------------------------



def hash_pin_pbkdf2(pin: str, iterations: int = 100_000) -> str:
    salt = os.urandom(32).hex()
    dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"

def verify_pin(pin: str, stored: str) -> bool:
    """Akzeptiert neues PBKDF2-Format und legacy reinen SHA256-Hash (Upgrade beim Erfolg empfohlen)."""
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iters_str, salt_hex, hash_hex = stored.split("$", 3)
            iters = int(iters_str)
            dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), bytes.fromhex(salt_hex), iters).hex()
            # constant-time Vergleich
            return hmac.compare_digest(dk, hash_hex)
        except Exception:
            return False
    # Legacy: nackter sha256
    return hmac.compare_digest(hashlib.sha256(pin.encode('utf-8')).hexdigest(), stored)

def maybe_upgrade_pin_hash(cursor: sqlite3.Cursor, pin: str, stored: str) -> None:
    """Wenn legacy-Hash, auf PBKDF2-Format upgraden (nur ein User-Szenario in DB angenommen)."""
    if stored.startswith("pbkdf2_sha256$"):
        return
    new_val = hash_pin_pbkdf2(pin)
    cursor.execute("UPDATE users SET pin_hash=? WHERE pin_hash=?", (new_val, stored))


# ----------------------------------------------------------------------
# Hauptklasse
# ----------------------------------------------------------------------

class TuxGuard:
    # ---------------------------- Init/Setup ----------------------------

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TuxGuard")

        # Sitzungs- & Statusflags
        self.lockout_until = 0
        self.session_start = time.time()
        self.max_session_duration = 12 * 3600
        self.threads = []
        self.test_flag = False
        self.monitoring_active = False

        # Kamera
        self.camera_active_event = threading.Event()
        self.camera_monitor_active = False
        self.camera_monitor_thread = None
        self.camera_device = "/dev/video0"
        self.camera_lock_file = "/tmp/tuxguard_camera.lock"
        self.camera_permission_dialog = None
        self.camera_available = self.check_camera_availability()

        # Maus / Mustererkennung
        self.mouse_monitor_active = False
        self.mouse_monitor_thread = None
        self.mouse_monitor_interval = 5
        self.mouse_data = []
        self.recording = False
        self.pattern_model = None
        self.pattern_recording_event = threading.Event()

        # Adaptives Lernen
        self.adaptive_positive_samples = []
        self.adaptive_auth_success_count = 0
        self.adaptive_retrain_interval = 10
        self.adaptive_learning_enabled = True

        # Fensterverwaltung
        self.active_windows = {
            'pin_dialog': None,
            'test_window': None,
            'permission_dialog': None,
            'training_window': None
        }

        # DB & Daten
        self.setup_database()
        self.load_image_names()

        # Grund-UI
        self._build_ui()

        # Modus & Modell (erst nach UI, damit status_label existiert)
        self.configure_security_mode()
        self.load_pattern_model()

    # ---------------------------- UI ----------------------------
    def _refresh_user_listbox(self):
        if hasattr(self, 'user_listbox'):
            self.user_listbox.delete(0, tk.END)
            self.cursor.execute("SELECT name FROM users ORDER BY name")
            for row in self.cursor.fetchall():
                self.user_listbox.insert(tk.END, row[0])



    def _build_ui(self):
        # Top bar: Kamera, Status, Mustererkennung, Überwachung
        top_frame = ttk.Frame(self.root)
        top_frame.pack(pady=5, padx=10, fill=tk.X)

        camera_frame = ttk.LabelFrame(top_frame, text="Kamera-Steuerung")
        camera_frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        self.test_camera_button = ttk.Button(camera_frame, text="Kamera testen", command=self.test_camera)
        self.test_camera_button.pack(pady=5, padx=5, fill=tk.X)
        self.diagnose_camera_button = ttk.Button(camera_frame, text="Kamera-Diagnose", command=self.diagnose_camera)
        self.diagnose_camera_button.pack(pady=5, padx=5, fill=tk.X)

        status_frame = ttk.LabelFrame(top_frame, text="System-Status")
        status_frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        self.status_label = Label(status_frame, text="Initialisiere...", font=('Arial', 10))
        self.status_label.pack(pady=5)

        pattern_frame = ttk.LabelFrame(top_frame, text="Mustererkennung")
        pattern_frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        self.train_pattern_button = ttk.Button(pattern_frame, text="Mausbewegungen trainieren",
                            command=self.start_pattern_training)
        self.train_pattern_button.pack(pady=5, padx=5, fill=tk.X)

        monitor_frame = ttk.LabelFrame(top_frame, text="Überwachung")
        monitor_frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)

        self.start_monitoring_button = ttk.Button(monitor_frame, text="Überwachung starten",
                            command=self.toggle_monitoring)
        self.start_monitoring_button.pack(pady=5, padx=5, fill=tk.X)

        # Tabs für Maus-Logs und Benutzer/Bilder
        tab_control = ttk.Notebook(self.root)
        tab_control.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Tab: Maus-Logs
        logs_tab = ttk.Frame(tab_control)
        tab_control.add(logs_tab, text="Maus-Logs")

        # Tab: Benutzer/Bilder
        users_tab = ttk.Frame(tab_control)
        tab_control.add(users_tab, text="Benutzer/Bilder")

        # --- Inhalt Maus-Logs-Tab ---
        self.mouse_logs_frame = ttk.LabelFrame(logs_tab, text="Mausbewegungs-Logs")
        self.mouse_logs_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        self.mouse_logs_text = Text(self.mouse_logs_frame, height=8)
        self.mouse_logs_text.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        mouse_logs_button_frame = ttk.Frame(self.mouse_logs_frame)
        mouse_logs_button_frame.pack(pady=10, fill=tk.X)
        ttk.Button(mouse_logs_button_frame, text="Logs löschen",
            command=self.clear_mouse_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(mouse_logs_button_frame, text="Logs exportieren",
            command=self.export_mouse_logs).pack(side=tk.LEFT, padx=5)

        # --- Inhalt Benutzer/Bilder-Tab ---
        user_frame = ttk.LabelFrame(users_tab, text="Benutzer/Gesichtsbilder")
        user_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        self.upload_user_button = ttk.Button(user_frame, text="Neuen Benutzer anlegen (Bilder hochladen)",
                            command=self.add_new_user)
        self.upload_user_button.pack(pady=5, padx=5, fill=tk.X)

        # User-Liste
        self.user_listbox = tk.Listbox(user_frame)
        self.user_listbox.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        self.user_listbox.bind('<Button-3>', self._show_user_context_menu)

        # Kontextmenü für User-Liste
        self.user_context_menu = tk.Menu(self.root, tearoff=0)
        self.user_context_menu.add_command(label="Bilder anzeigen", command=self._show_user_images)

        # Bildanzeige-Fenster (wird nur bei Bedarf geöffnet)
        self.image_window = None

        # Initiales Laden der User-Liste
        self._refresh_user_listbox()
        self.user_listbox.delete(0, tk.END)
        self.cursor.execute("SELECT name FROM users ORDER BY name")
        for row in self.cursor.fetchall():
            self.user_listbox.insert(tk.END, row[0])

    def toggle_monitoring(self):
        if self.monitoring_active:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def stop_monitoring(self):
        self.monitoring_active = False
        self.stop_mouse_monitoring_only()
        self.stop_camera()
        self.add_mouse_log("Überwachung gestoppt.")
        self.start_monitoring_button.config(text="Überwachung starten")

    def _show_user_context_menu(self, event):
        try:
            index = self.user_listbox.nearest(event.y)
            self.user_listbox.selection_clear(0, tk.END)
            self.user_listbox.selection_set(index)
            self.user_listbox.activate(index)
            self.user_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.user_context_menu.grab_release()


    def _show_user_images(self):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        user_name = self.user_listbox.get(selection[0])
        self.cursor.execute("SELECT fe.description, fe.face_encoding FROM face_encodings fe JOIN users u ON fe.user_id = u.id WHERE u.name=?", (user_name,))
        images = self.cursor.fetchall()
        if not images:
            messagebox.showinfo("Keine Bilder", f"Für Benutzer '{user_name}' sind keine Bilder gespeichert.")
            return
        # Fenster für Bildanzeige
        if self.image_window and self.image_window.winfo_exists():
            self.image_window.destroy()
        self.image_window = tk.Toplevel(self.root)
        self.image_window.title(f"Bilder von {user_name}")
        self.image_window.geometry("600x400")
        frame = ttk.Frame(self.image_window)
        frame.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(frame, bg="white")
        canvas.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner_frame = ttk.Frame(canvas)
        canvas.create_window((0,0), window=inner_frame, anchor='nw')
        # Bilder anzeigen
        self._user_images_refs = []
        for i, (desc, enc_blob) in enumerate(images):
            arr = np.frombuffer(enc_blob, dtype=np.float64)
            # Dummy-Bild: Zeige nur Beschreibung, da Encoding kein Bild ist
            label = ttk.Label(inner_frame, text=f"Bild {i+1}: {desc}")
            label.pack(pady=10)
        inner_frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"))

    # ---------------------------- Fensterverwaltung ----------------------------

    def close_window(self, window_name: str):
        if self.active_windows[window_name] and self.active_windows[window_name].winfo_exists():
            self.active_windows[window_name].destroy()
        self.active_windows[window_name] = None

    def ensure_single_window(self, window_name: str) -> bool:
        if self.active_windows[window_name] and self.active_windows[window_name].winfo_exists():
            self.active_windows[window_name].lift()
            self.active_windows[window_name].focus_force()
            return False
        return True

    # ---------------------------- DB ----------------------------

    def setup_database(self):
        self.conn = sqlite3.connect('face_recognition.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                pin_hash TEXT NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_encodings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                face_encoding BLOB NOT NULL,
                description TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        self.conn.commit()

    def thread_db(self):
        """Neue DB-Connection pro Thread (SQLite ist in Threads heikel)."""
        c = sqlite3.connect('face_recognition.db')
        return c, c.cursor()

    # ---------------------------- Kamera: Verfügbarkeit & Diagnose ----------------------------

    def check_camera_availability(self) -> bool:
        try:
            for i in range(5):
                device_path = f"/dev/video{i}"
                if os.path.exists(device_path):
                    cap = cv2.VideoCapture(i)
                    if cap.isOpened():
                        ret, _ = cap.read()
                        cap.release()
                        if ret:
                            print(f"Kamera gefunden: {device_path}")
                            return True
            return False
        except Exception as e:
            print(f"Fehler beim Prüfen der Kamera-Verfügbarkeit: {e}")
            return False

    def diagnose_camera(self):
        print("=== KAMERA-DIAGNOSE ===")
        print(f"1. Geräte: {[p for p in [f'/dev/video{i}' for i in range(5)] if os.path.exists(p)]}")
        try:
            result = sp.run(['v4l2-ctl', '--list-devices'], capture_output=True, text=True, timeout=5)
            print("\n2. v4l2-ctl:", result.stdout if result.returncode == 0 else "v4l2-ctl nicht verfügbar")
        except (sp.TimeoutExpired, FileNotFoundError):
            print("\n2. v4l2-ctl nicht verfügbar")
        try:
            result = sp.run(['lsof', '/dev/video*'], capture_output=True, text=True, timeout=5)
            print("\n3. Prozesse:", result.stdout.strip() or "Keine")
        except (sp.TimeoutExpired, FileNotFoundError):
            print("\n3. lsof nicht verfügbar")
        print("=== ENDE KAMERA-DIAGNOSE ===")

    # ---------------------------- Kamera: Lock/Überwachung ----------------------------

    def create_camera_lock(self):
        try:
            with open(self.camera_lock_file, 'w') as f:
                f.write(f"TuxGuard Camera Lock - PID: {os.getpid()}\nTimestamp: {time.time()}\n")
            print(f"Kamera-Lock erstellt: {self.camera_lock_file}")
            return True
        except Exception as e:
            print(f"Fehler beim Erstellen der Kamera-Lock: {e}")
            return False

    def remove_camera_lock(self):
        try:
            if os.path.exists(self.camera_lock_file):
                os.remove(self.camera_lock_file)
                print(f"Kamera-Lock entfernt: {self.camera_lock_file}")
        except Exception as e:
            print(f"Fehler beim Entfernen der Kamera-Lock: {e}")

    def check_camera_access(self) -> bool:
        # EBUSY (16) => busy
        try:
            if os.path.exists(self.camera_device):
                fd = os.open(self.camera_device, os.O_RDWR | os.O_NONBLOCK)
                os.close(fd)
                return True
        except (OSError, IOError) as e:
            if getattr(e, "errno", None) == 16:
                print(f"Kamera busy: {e}")
                return False
            print(f"Fehler beim Kamera-Check: {e}")
            return False
        return True

    def monitor_camera_access(self):
        while self.camera_monitor_active:
            try:
                time.sleep(2)
                if not self.check_camera_access():
                    self.root.after(0, self.show_camera_permission_dialog)
            except Exception as e:
                print(f"Fehler in Kameraüberwachung: {e}")
                time.sleep(5)

    def show_camera_permission_dialog(self):
        if not self.ensure_single_window('permission_dialog'):
            return
        self.active_windows['permission_dialog'] = Toplevel(self.root)
        dlg = self.active_windows['permission_dialog']
        dlg.title("Kamera-Zugriff erkannt")
        dlg.geometry("400x250")
        dlg.transient(self.root)
        dlg.grab_set()

        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"400x250+{(sw-400)//2}+{(sh-250)//2}")
        dlg.attributes('-topmost', True)
        dlg.focus_force()

        Label(dlg, text="Ein anderes Programm versucht,\ndie Kamera zu nutzen.",
              font=('Arial', 12, 'bold')).pack(pady=20)
        Label(dlg, text="Möchten Sie dies erlauben?\n\nTuxGuard gibt die Kamera\nvorübergehend frei.",
              font=('Arial', 10)).pack(pady=10)

        def allow_camera():
            dlg.destroy()
            self.active_windows['permission_dialog'] = None
            self.temporarily_release_camera()

        def deny_camera():
            dlg.destroy()
            self.active_windows['permission_dialog'] = None

        btnf = ttk.Frame(dlg); btnf.pack(pady=20)
        ttk.Button(btnf, text="Erlauben", command=allow_camera).pack(side=tk.LEFT, padx=10)
        ttk.Button(btnf, text="Verweigern", command=deny_camera).pack(side=tk.LEFT, padx=10)

    def temporarily_release_camera(self):
        if hasattr(self, 'video_capture') and self.video_capture.isOpened():
            self.video_capture.release()
        Timer(30.0, self.resume_camera_monitoring).start()

    def resume_camera_monitoring(self):
        if self.camera_active_event.is_set():
            self.start_camera()

    def start_camera_monitoring(self):
        if not self.camera_monitor_active:
            self.camera_monitor_active = True
            self.create_camera_lock()
            self.camera_monitor_thread = threading.Thread(target=self.monitor_camera_access, daemon=True)
            self.camera_monitor_thread.start()

    def stop_camera_monitoring(self):
        self.camera_monitor_active = False
        self.remove_camera_lock()
        if self.camera_permission_dialog:
            self.camera_permission_dialog.destroy()
            self.camera_permission_dialog = None

    # ---------------------------- Kamera: Start/Stop/Loop ----------------------------

    def start_camera(self):
        if not self.camera_available:
            messagebox.showinfo("Kamera nicht verfügbar",
                                "Keine Kamera verfügbar.\nNur die Mausbewegungserkennung ist aktiv.")
            return

        self.camera_active_event.set()
        self.start_camera_monitoring()

        self.video_capture = cv2.VideoCapture(0)
        for attempt in range(3):
            if self.video_capture.open(0):
                print(f"Kamera geöffnet (Versuch {attempt + 1})")
                break
            time.sleep(1)
        else:
            self.diagnose_camera()
            messagebox.showwarning("Kamera-Warnung",
                                   "Kamera konnte nicht geöffnet werden. Überwachung läuft weiter.")

        self.camera_thread = threading.Thread(target=self.run_camera, daemon=True, name="CameraLoop")
        self.camera_thread.start()
        if not self.test_flag:
            self.minimize_to_tray()

    def stop_camera(self):
        self.camera_active_event.clear()
        if hasattr(self, 'video_capture'):
            try:
                self.video_capture.release()
            except Exception:
                pass
        cv2.destroyAllWindows()
        self.stop_camera_monitoring()

    def run_camera(self):
        conn, cursor = self.thread_db()
        try:
            while self.camera_active_event.is_set():
                ret, frame = self.video_capture.read()
                if not ret:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb)
                face_encodings = face_recognition.face_encodings(rgb, face_locations)

                user_recognized = False
                if face_encodings:
                    cursor.execute("""
                        SELECT u.name, fe.face_encoding, fe.description 
                        FROM users u 
                        JOIN face_encodings fe ON u.id = fe.user_id
                    """)
                    for name, enc_blob, _desc in cursor.fetchall():
                        db_enc = np.frombuffer(enc_blob, dtype=np.float64)
                        for enc in face_encodings:
                            if face_recognition.compare_faces([db_enc], enc)[0]:
                                user_recognized = True
                                break
                        if user_recognized:
                            break

                # … hier kannst du je nach Logik Aktionen setzen (Alarm/Lock/Log etc.)

        except Exception as e:
            print(f"Fehler in run_camera: {e}\n{traceback.format_exc()}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---------------------------- Tray ----------------------------

    def minimize_to_tray(self):
        if hasattr(self, 'icon'):
            self.icon.stop()
        self.root.withdraw()
        image = Image.new('RGB', (64, 64), color='white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 64, 64), fill='blue')
        self.icon = pystray.Icon("TuxGuard", image, "TuxGuard", self.create_menu())
        tray_thread = threading.Thread(target=self.icon.run, daemon=True, name="TrayIcon")
        tray_thread.start()
        self.threads.append(tray_thread)

    def create_menu(self):
        items = [pystray.MenuItem("Öffnen", self.restore_window)]
        if not self.monitoring_active:
            items.append(pystray.MenuItem("Überwachung starten",
                          lambda: self.root.after(0, self.start_monitoring)))
        items.append(pystray.MenuItem("Beenden",
                          lambda: self.root.after(0, lambda: self.close_app(from_tray=True))))
        return pystray.Menu(*items)

    def restore_window(self):
        if time.time() - self.session_start > self.max_session_duration:
            messagebox.showwarning("Session abgelaufen", "Bitte TuxGuard neu starten.")
            self.close_app(from_tray=True)
            return
        self.root.after(0, self._show_restore_pin_dialog)

    def _show_restore_pin_dialog(self, reason="Fenster maximieren"):
        if not self.ensure_single_window('pin_dialog'):
            return
        dlg = Toplevel(self.root)
        self.active_windows['pin_dialog'] = dlg
        dlg.title("PIN Eingabe erforderlich")
        dlg.geometry("300x220")
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"300x220+{(sw-300)//2}+{(sh-220)//2}")
        dlg.attributes('-topmost', True)
        dlg.focus_force()
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

        Label(dlg, text=f"Grund: {reason}", font=('Arial', 10, 'bold')).pack(pady=5)
        Label(dlg, text="Bitte geben Sie Ihre PIN ein:").pack(pady=5)
        pin_entry = Entry(dlg, show='*'); pin_entry.pack(pady=10)

        def ok():
            pin = pin_entry.get()
            pin_entry.delete(0, tk.END)  # sensiblen Inhalt räumen
            if self._verify_pin_against_db(pin):
                dlg.destroy()
                self.root.deiconify()
            else:
                messagebox.showerror("Fehler", "Falsche PIN."); pin_entry.focus_set()

        Button(dlg, text="Bestätigen", command=ok).pack(pady=10)
        pin_entry.focus_set()

    # ---------------------------- Maus / Mustererkennung ----------------------------

    def collect_mouse_data(self, duration=10):
        return collect_data(duration)

    def preprocess_mouse_data(self, data):
        return preprocess_data(data)

    def build_pattern_model(self, input_shape):
        return build_model(input_shape)

    def load_pattern_model(self):
        model_path = Path("models/mouse_pattern_model.keras")
        if model_path.exists():
            try:
                self.pattern_model = keras.models.load_model(str(model_path))
                print(f"Mausmuster-Modell geladen: {model_path}")
            except Exception as e:
                print(f"Fehler beim Laden des Mausmuster-Modells: {e}")
                self.pattern_model = None
        else:
            print("Kein Mausmuster-Modell gefunden.")
            self.pattern_model = None

    def start_pattern_training(self):
        # Trainingslogik liegt extern; hier nur UI-/Startpunkt belassen
        messagebox.showinfo("Training", "Das Training wird in der externen Trainingsroutine gestartet.")

    def verify_mouse_pattern(self, duration=5):
        if self.pattern_model is None:
            self.add_mouse_log("Kein Mustererkennungsmodell geladen, Zugriff erlaubt.")
            return True
        data = self.collect_mouse_data(duration=duration)
        if len(data) < 2:
            self.add_mouse_log("Zu wenig Mausdaten für Mustererkennung, Zugriff erlaubt.")
            return True
        try:
            features = self.preprocess_mouse_data(data)
            predictions = self.pattern_model.predict(features, verbose=0)
            avg_pred = predictions.mean()
            logmsg = f"Verifikation Modell-Score: {avg_pred:.3f} (Schwelle: 0.5)"
            print("[TuxGuard] " + logmsg)
            self.add_mouse_log(logmsg)
            is_auth = avg_pred > 0.5
            if is_auth and self.adaptive_learning_enabled:
                self.adaptive_positive_samples.append(features)
                self.adaptive_auth_success_count += 1
                self.add_mouse_log(f"Adaptives Lernen: Erfolg #{self.adaptive_auth_success_count}, neue Daten gespeichert.")
                if self.adaptive_auth_success_count % self.adaptive_retrain_interval == 0:
                    self.add_mouse_log("Adaptives Lernen: Starte automatisches Nachtraining…")
                    self.retrain_pattern_model_adaptive()
            return is_auth
        except Exception as e:
            self.add_mouse_log(f"Fehler bei Modell-Verifikation: {e}")
            return True  # im Zweifel nicht sperren

    def retrain_pattern_model_adaptive(self):
        if not self.adaptive_positive_samples:
            self.add_mouse_log("Adaptives Lernen: Keine neuen Daten zum Nachtrainieren.")
            return
        try:
            model_dir = Path("models"); model_dir.mkdir(parents=True, exist_ok=True)
            neg_path = model_dir / "mouse_pattern_negatives.npy"
            if neg_path.exists():
                X_neg = np.load(neg_path); y_neg = np.zeros(len(X_neg))
            else:
                self.add_mouse_log("Warnung: Keine negativen Beispiele gefunden. Nur positives Nachtraining.")
                X_neg = np.empty((0, self.adaptive_positive_samples[0].shape[1])); y_neg = np.zeros(0)

            X_pos = np.vstack(self.adaptive_positive_samples); y_pos = np.ones(len(X_pos))
            X_train = np.vstack([X_pos, X_neg]) if len(X_neg) > 0 else X_pos
            y_train = np.concatenate([y_pos, y_neg]) if len(y_neg) > 0 else y_pos

            idx = np.arange(len(X_train)); np.random.shuffle(idx)
            X_train, y_train = X_train[idx], y_train[idx]

            input_shape = (X_train.shape[1],)
            self.pattern_model = self.build_pattern_model(input_shape)
            self.pattern_model.fit(X_train, y_train, epochs=10, batch_size=32, verbose=0)

            model_path = model_dir / "mouse_pattern_model.keras"
            self.pattern_model.save(str(model_path))
            self.add_mouse_log(f"Adaptives Lernen: Modell nachtrainiert und gespeichert ({len(X_pos)} neue positive Beispiele)")
            self.adaptive_positive_samples.clear()
        except Exception as e:
            self.add_mouse_log(f"Fehler beim adaptiven Nachtraining: {e}")

    def mouse_monitor_loop(self):
        while self.mouse_monitor_active:
            try:
                self.add_mouse_log("Mausbewegungsüberwachung: Überprüfung läuft.")
                data = self.collect_mouse_data(duration=3)
                # Beispielhafte Verwendung des Modells; deine Logik hier andocken
                _ = len(data)  # Placeholder, um Lint zu beruhigen
            finally:
                time.sleep(self.mouse_monitor_interval)

    def start_mouse_monitoring(self):
        if not self.mouse_monitor_active:
            self.mouse_monitor_active = True
            self.mouse_monitor_thread = threading.Thread(target=self.mouse_monitor_loop, daemon=True, name="MouseLoop")
            self.mouse_monitor_thread.start()

    def stop_mouse_monitoring_only(self):
        self.mouse_monitor_active = False

    def add_mouse_log(self, message: str):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log = f"[{timestamp}] {message}\n"
        if hasattr(self, 'mouse_logs_text') and self.mouse_logs_text:
            self.mouse_logs_text.insert(tk.END, log)
            self.mouse_logs_text.see(tk.END)
        print(log, end='')

    def clear_mouse_logs(self):
        if messagebox.askyesno("Logs löschen", "Möchten Sie wirklich alle Mausbewegungslogs löschen?"):
            self.mouse_logs_text.delete("1.0", tk.END)
            self.add_mouse_log("Logs wurden gelöscht")

    def export_mouse_logs(self):
        try:
            filename = f"tuxguard_mouse_logs_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            path = filedialog.asksaveasfilename(defaultextension=".txt",
                                                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                                                initialfile=filename)
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.mouse_logs_text.get("1.0", tk.END))
                messagebox.showinfo("Export erfolgreich", f"Logs exportiert nach:\n{path}")
                self.add_mouse_log(f"Logs exportiert nach: {path}")
        except Exception as e:
            messagebox.showerror("Export fehlgeschlagen", f"Fehler beim Exportieren: {str(e)}")

    # ---------------------------- Benutzer/Gesichter ----------------------------

    def load_image_names(self):
        # Aktualisiere die User-Liste im Tab
        if hasattr(self, 'user_listbox'):
            self._refresh_user_listbox()

    def add_new_user(self):
        name = simpledialog.askstring("Name", "Bitte geben Sie einen Namen für den neuen Benutzer ein:")
        if not name:
            messagebox.showerror("Fehler", "Name-Eingabe erforderlich."); return
        pin = simpledialog.askstring("PIN", "Bitte geben Sie eine PIN ein (mindestens 6 Zeichen):", show='*')
        if not pin or len(pin) < 6:
            messagebox.showerror("Fehler", "PIN muss mindestens 6 Zeichen lang sein."); return

        file_paths = filedialog.askopenfilenames(title="Bilder für Gesichtserkennung auswählen", filetypes=[("Bilder", "*.jpg *.jpeg *.png")])
        if not file_paths:
            messagebox.showerror("Fehler", "Keine Bilder ausgewählt."); return

        pin_hash = hash_pin_pbkdf2(pin)
        try:
            self.cursor.execute("INSERT INTO users (name, pin_hash) VALUES (?, ?)", (name, pin_hash))
        except sqlite3.IntegrityError:
            messagebox.showerror("Fehler", f"Benutzername '{name}' existiert bereits. Bitte wählen Sie einen anderen Namen.")
            return
        user_id = self.cursor.lastrowid
        saved_count = 0
        for file_path in file_paths:
            image = face_recognition.load_image_file(file_path)
            encs = face_recognition.face_encodings(image)
            if not encs:
                messagebox.showwarning("Warnung", f"Kein Gesicht erkannt in: {os.path.basename(file_path)}. Überspringe.")
                continue
            description = simpledialog.askstring("Beschreibung", f"Optionale Beschreibung für {os.path.basename(file_path)}:")
            if not description: description = f"Bild {saved_count+1}"
            face_encoding_blob = sqlite3.Binary(np.array(encs[0]).tobytes())
            self.cursor.execute("INSERT INTO face_encodings (user_id, face_encoding, description) VALUES (?, ?, ?)",
                                (user_id, face_encoding_blob, description))
            saved_count += 1
        self.conn.commit()
        self.load_image_names()
        if saved_count:
            messagebox.showinfo("Erfolg", f"Neuer Benutzer und {saved_count} Gesichtsbild(er) gespeichert!")
        else:
            messagebox.showerror("Fehler", "Kein gültiges Gesichtsbild gespeichert.")

    def add_face_to_user(self, file_path: str, user_id: int):
        image = face_recognition.load_image_file(file_path)
        encs = face_recognition.face_encodings(image)
        if not encs:
            messagebox.showerror("Fehler", "Kein Gesicht im Bild erkannt."); return
        description = simpledialog.askstring("Beschreibung", "Optionale Beschreibung:")
        if not description: description = "Zusätzliches Bild"
        face_encoding_blob = sqlite3.Binary(np.array(encs[0]).tobytes())
        self.cursor.execute("INSERT INTO face_encodings (user_id, face_encoding, description) VALUES (?, ?, ?)",
                            (user_id, face_encoding_blob, description))
        self.conn.commit()
        messagebox.showinfo("Erfolg", "Zusätzliches Gesichtsbild gespeichert!")

    def delete_user_by_name(self, user_name: str):
        self.cursor.execute("DELETE FROM face_encodings WHERE user_id IN (SELECT id FROM users WHERE name=?)", (user_name,))
        self.cursor.execute("DELETE FROM users WHERE name=?", (user_name,))
        self.conn.commit()
        self.load_image_names()

    # ---------------------------- Webcam Schnellaufnahme (UI sicher freigeben) ----------------------------

    def capture_image_with_webcam(self):
        cam = cv2.VideoCapture(0)
        if not cam.isOpened():
            messagebox.showerror("Fehler", "Kamera konnte nicht geöffnet werden."); return None

        win = tk.Toplevel(self.root); win.title("Webcam - Foto aufnehmen")
        win.geometry("700x550"); win.transient(self.root); win.grab_set()
        lmain = tk.Label(win); lmain.pack(pady=10)
        captured = {'img': None}; closed = {'done': False}

        def show_frame():
            if closed['done']: return
            ret, frame = cam.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                imgtk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
                lmain.imgtk = imgtk; lmain.configure(image=imgtk)
            if not closed['done']:
                lmain.after(20, show_frame)
        show_frame()

        def capture():
            ret, frame = cam.read()
            if ret:
                if cam.isOpened(): cam.release()
                closed['done'] = True; win.destroy()
                tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                cv2.imwrite(tmp.name, frame); captured['img'] = tmp.name
            else:
                messagebox.showerror("Fehler", "Foto konnte nicht aufgenommen werden.")

        def on_abort():
            if cam.isOpened(): cam.release()
            closed['done'] = True; win.destroy()

        tk.Button(win, text="Foto aufnehmen", command=capture).pack(pady=10)
        tk.Button(win, text="Abbrechen", command=on_abort).pack(pady=5)
        win.protocol("WM_DELETE_WINDOW", on_abort)
        self.root.wait_window(win)
        if cam.isOpened(): cam.release()
        return captured['img']

    # ---------------------------- PIN-Dialoge / App-Ende ----------------------------

    def _verify_pin_against_db(self, pin: str) -> bool:
        try:
            self.cursor.execute("SELECT pin_hash FROM users LIMIT 1")
            row = self.cursor.fetchone()
            if not row: return False
            stored = row[0]
            ok = verify_pin(pin, stored)
            if ok and not stored.startswith("pbkdf2_sha256$"):
                # Upgrade (silent)
                maybe_upgrade_pin_hash(self.cursor, pin, stored)
                self.conn.commit()
            return ok
        except sqlite3.OperationalError:
            messagebox.showerror("Fehler", "Datenbankfehler")
            return False

    def stop_monitoring_with_pin(self, from_tray: bool = False):
        if not self.ensure_single_window('pin_dialog'): return
        dlg = Toplevel(self.root); self.active_windows['pin_dialog'] = dlg
        dlg.title("PIN zum Stoppen eingeben"); dlg.geometry("300x200")
        dlg.transient(self.root); dlg.grab_set(); dlg.attributes('-topmost', True); dlg.focus_force()
        Label(dlg, text="Bitte geben Sie Ihre PIN ein:").pack(pady=10)
        pin_entry = Entry(dlg, show='*'); pin_entry.pack(pady=10)

        def ok():
            pin = pin_entry.get(); pin_entry.delete(0, tk.END)
            if self._verify_pin_against_db(pin):
                dlg.destroy()
                self.stop_all_and_quit()
            else:
                messagebox.showerror("Fehler", "Falsche PIN."); pin_entry.focus_set()

        Button(dlg, text="Bestätigen", command=ok).pack(pady=10)
        pin_entry.focus_set()
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    def close_app(self, from_tray: bool = False):
        if from_tray:
            # Tray -> PIN verlangen
            self.stop_monitoring_with_pin(from_tray=True)
        else:
            # Direktes Schließen von Hauptfenster
            self.stop_all_and_quit()

    def stop_all_and_quit(self):
        self.stop_camera()
        self.camera_active_event.clear()
        self.stop_camera_monitoring()
        self.stop_mouse_monitoring_only()
        if hasattr(self, 'icon'):
            try: self.icon.stop()
            except Exception: pass
        self.root.quit()

    # ---------------------------- Überwachung Start/Stop ----------------------------

    def start_monitoring(self):
        self.monitoring_active = True
        self.start_mouse_monitoring()
        self.start_camera()
        self.add_mouse_log("Überwachung gestartet.")
        self.start_monitoring_button.config(text="Überwachung stoppen")

    # ---------------------------- Komfort/Debug ----------------------------

    def configure_security_mode(self):
        if self.camera_available:
            self.root.title("TuxGuard - Kamera + Mausbewegungserkennung")
            self.status_label.config(text="✓ Kamera verfügbar\n✓ Mausbewegungserkennung verfügbar", fg="green")
        else:
            self.root.title("TuxGuard - Mausbewegungserkennung")
            self.status_label.config(text="✗ Kamera nicht verfügbar\n✓ Mausbewegungserkennung verfügbar", fg="orange")
            # Kamera-Buttons ggf. deaktivieren
            try:
                self.test_camera_button.configure(state="disabled")
            except Exception:
                pass

    def test_camera(self):
        # Placeholder: Kameratest-UI oder kurzer Zugriff
        messagebox.showinfo("Kamera-Test", "Kamera-Test gestartet/OK (Platzhalter).")

    # Event-Hook in __main__
    def on_closing(self):
        self.close_app(from_tray=False)


# ----------------------------------------------------------------------
# __main__
# ----------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = TuxGuard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

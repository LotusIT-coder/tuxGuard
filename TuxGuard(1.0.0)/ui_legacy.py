#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard UI Module
Benutzeroberfläche und UI-Komponenten
"""

import tkinter as tk
from tkinter import ttk, Text, Listbox, Menu, messagebox, simpledialog, filedialog
from tkinter import Toplevel, Label, Entry, Button
import time
import logging
from typing import Optional, Callable, List
from pathlib import Path

from config import Config

logger = logging.getLogger('TuxGuard.UI')

class PinDialog:
    """Dialog für PIN-Eingabe"""
    
    def __init__(self, parent: tk.Tk, title: str = "PIN Eingabe", 
                 reason: str = "Bitte geben Sie Ihre PIN ein"):
        self.parent = parent
        self.title = title
        self.reason = reason
        self.result = None
        self.dialog = None
    
    def show(self) -> Optional[str]:
        """Zeigt den PIN-Dialog und gibt die eingegebene PIN zurück"""
        self.dialog = Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry(Config.PIN_DIALOG_GEOMETRY)
        
        # Zentriere Dialog
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 300) // 2
        y = (sh - 220) // 2
        self.dialog.geometry(f"300x220+{x}+{y}")
        
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        
        # UI Elemente
        Label(self.dialog, text=self.reason, font=('Arial', 10, 'bold')).pack(pady=10)
        
        self.pin_entry = Entry(self.dialog, show='*', font=('Arial', 12))
        self.pin_entry.pack(pady=10)
        self.pin_entry.focus_set()
        
        # Buttons
        button_frame = tk.Frame(self.dialog)
        button_frame.pack(pady=10)
        
        Button(button_frame, text="OK", command=self._ok).pack(side=tk.LEFT, padx=5)
        Button(button_frame, text="Abbrechen", command=self._cancel).pack(side=tk.LEFT, padx=5)
        
        # Enter-Taste binden
        self.pin_entry.bind('<Return>', lambda e: self._ok())
        
        # Warte auf Schließung
        self.parent.wait_window(self.dialog)
        
        return self.result
    
    def _ok(self):
        """OK-Button gedrückt"""
        self.result = self.pin_entry.get()
        self.pin_entry.delete(0, tk.END)  # Sicherheit: PIN löschen
        self.dialog.destroy()
    
    def _cancel(self):
        """Abbrechen-Button gedrückt"""
        self.result = None
        if hasattr(self, 'pin_entry'):
            self.pin_entry.delete(0, tk.END)  # Sicherheit: PIN löschen
        self.dialog.destroy()

class UserListWidget:
    """Widget für Benutzerliste mit Kontextmenü"""
    
    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.listbox = None
        self.context_menu = None
        self.show_images_callback: Optional[Callable[[str], None]] = None
        self.delete_user_callback: Optional[Callable[[str], None]] = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die UI-Widgets"""
        self.listbox = Listbox(self.parent)
        self.listbox.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Kontextmenü
        self.context_menu = Menu(self.parent, tearoff=0)
        self.context_menu.add_command(label="Bilder anzeigen", command=self._show_images)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Benutzer löschen", command=self._delete_user)
        
        # Events binden
        self.listbox.bind('<Button-3>', self._show_context_menu)
    
    def set_callbacks(self, show_images: Optional[Callable[[str], None]] = None,
                     delete_user: Optional[Callable[[str], None]] = None):
        """Setzt Callback-Funktionen"""
        self.show_images_callback = show_images
        self.delete_user_callback = delete_user
    
    def _show_context_menu(self, event):
        """Zeigt das Kontextmenü"""
        try:
            index = self.listbox.nearest(event.y)
            if index >= 0:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(index)
                self.listbox.activate(index)
                self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def _show_images(self):
        """Zeigt Bilder des ausgewählten Benutzers"""
        selection = self.listbox.curselection()
        if selection and self.show_images_callback:
            user_name = self.listbox.get(selection[0])
            self.show_images_callback(user_name)
    
    def _delete_user(self):
        """Löscht den ausgewählten Benutzer"""
        selection = self.listbox.curselection()
        if selection and self.delete_user_callback:
            user_name = self.listbox.get(selection[0])
            if messagebox.askyesno("Benutzer löschen", 
                                 f"Möchten Sie den Benutzer '{user_name}' wirklich löschen?"):
                self.delete_user_callback(user_name)
    
    def refresh(self, users: List[str]):
        """Aktualisiert die Benutzerliste"""
        self.listbox.delete(0, tk.END)
        for user in sorted(users):
            self.listbox.insert(tk.END, user)
    
    def get_selected_user(self) -> Optional[str]:
        """Gibt den ausgewählten Benutzer zurück"""
        selection = self.listbox.curselection()
        return self.listbox.get(selection[0]) if selection else None

class LogWidget:
    """Widget für Log-Anzeige"""
    
    def __init__(self, parent: tk.Widget, title: str = "Logs"):
        self.parent = parent
        self.title = title
        self.text_widget = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die UI-Widgets"""
        # Frame für das Log-Widget
        frame = ttk.LabelFrame(self.parent, text=self.title)
        frame.pack(pady=10, fill=tk.BOTH, expand=True)
        
        # Text-Widget für Logs
        self.text_widget = Text(frame, height=8, wrap=tk.WORD)
        self.text_widget.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        
        # Button-Frame
        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=10, fill=tk.X)
        
        ttk.Button(button_frame, text="Logs löschen", 
                  command=self.clear).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Logs exportieren", 
                  command=self.export).pack(side=tk.LEFT, padx=5)
    
    def add_log(self, message: str):
        """Fügt eine Log-Nachricht hinzu"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}\n"
        
        if self.text_widget:
            self.text_widget.insert(tk.END, log_entry)
            self.text_widget.see(tk.END)
        
        # Auch in Logger schreiben
        logger.info(message)
    
    def clear(self):
        """Löscht alle Logs"""
        if messagebox.askyesno("Logs löschen", 
                              "Möchten Sie wirklich alle Logs löschen?"):
            if self.text_widget:
                self.text_widget.delete("1.0", tk.END)
            self.add_log("Logs wurden gelöscht")
    
    def export(self):
        """Exportiert Logs in eine Datei"""
        try:
            filename = f"tuxguard_logs_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=Config.LOG_FILE_TYPES,
                initialfile=filename
            )
            
            if path and self.text_widget:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.text_widget.get("1.0", tk.END))
                
                messagebox.showinfo("Export erfolgreich", 
                                  f"Logs exportiert nach:\n{path}")
                self.add_log(f"Logs exportiert nach: {path}")
                
        except Exception as e:
            messagebox.showerror("Export fehlgeschlagen", 
                               f"Fehler beim Exportieren: {str(e)}")
            logger.error(f"Log-Export fehlgeschlagen: {e}")

class StatusWidget:
    """Widget für Status-Anzeige"""
    
    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.label = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die UI-Widgets"""
        frame = ttk.LabelFrame(self.parent, text="System-Status")
        frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)
        
        self.label = Label(frame, text="Initialisiere...", font=('Arial', 10))
        self.label.pack(pady=5)
    
    def update_status(self, camera_available: bool, mouse_available: bool = True):
        """Aktualisiert den Status"""
        if camera_available:
            text = "✓ Kamera verfügbar\n✓ Mausbewegungserkennung verfügbar"
            color = "green"
        else:
            text = "✗ Kamera nicht verfügbar\n✓ Mausbewegungserkennung verfügbar"
            color = "orange"
        
        if not mouse_available:
            text += "\n✗ Mausbewegungserkennung nicht verfügbar"
            color = "red"
        
        if self.label:
            self.label.config(text=text, fg=color)

class ControlWidget:
    """Widget für Steuerungsbuttons"""
    
    def __init__(self, parent: tk.Widget, title: str):
        self.parent = parent
        self.title = title
        self.frame = None
        self.buttons = {}
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die UI-Widgets"""
        self.frame = ttk.LabelFrame(self.parent, text=self.title)
        self.frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)
    
    def add_button(self, name: str, text: str, command: Callable, **kwargs):
        """Fügt einen Button hinzu"""
        button = ttk.Button(self.frame, text=text, command=command, **kwargs)
        button.pack(pady=5, padx=5, fill=tk.X)
        self.buttons[name] = button
        return button
    
    def get_button(self, name: str) -> Optional[ttk.Button]:
        """Gibt einen Button zurück"""
        return self.buttons.get(name)
    
    def configure_button(self, name: str, **kwargs):
        """Konfiguriert einen Button"""
        button = self.buttons.get(name)
        if button:
            button.configure(**kwargs)

class MainUI:
    """Hauptbenutzeroberfläche"""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(Config.WINDOW_TITLE)
        self.root.geometry(Config.WINDOW_GEOMETRY)
        
        # UI-Komponenten
        self.status_widget = None
        self.user_list_widget = None
        self.mouse_log_widget = None
        self.control_widgets = {}
        
        # Callbacks
        self.callbacks = {}
        
        self._build_ui()
    
    def _build_ui(self):
        """Erstellt die Hauptbenutzeroberfläche"""
        # Top-Frame für Steuerung
        top_frame = ttk.Frame(self.root)
        top_frame.pack(pady=5, padx=10, fill=tk.X)
        
        # Status-Widget
        self.status_widget = StatusWidget(top_frame)
        
        # Steuerungs-Widgets
        self._create_control_widgets(top_frame)
        
        # Tab-Control für Hauptinhalte
        tab_control = ttk.Notebook(self.root)
        tab_control.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Tab: Maus-Logs
        logs_tab = ttk.Frame(tab_control)
        tab_control.add(logs_tab, text="Maus-Logs")
        self.mouse_log_widget = LogWidget(logs_tab, "Mausbewegungs-Logs")
        
        # Tab: Benutzer/Bilder
        users_tab = ttk.Frame(tab_control)
        tab_control.add(users_tab, text="Benutzer/Bilder")
        self._create_users_tab(users_tab)
    
    def _create_control_widgets(self, parent: tk.Widget):
        """Erstellt die Steuerungs-Widgets"""
        # Kamera-Steuerung
        camera_widget = ControlWidget(parent, "Kamera-Steuerung")
        camera_widget.add_button("test", "Kamera testen", 
                                lambda: self._call_callback('test_camera'))
        camera_widget.add_button("diagnose", "Kamera-Diagnose", 
                                lambda: self._call_callback('diagnose_camera'))
        self.control_widgets['camera'] = camera_widget
        
        # Mustererkennung
        pattern_widget = ControlWidget(parent, "Mustererkennung")
        pattern_widget.add_button("train", "Mausbewegungen trainieren", 
                                 lambda: self._call_callback('train_pattern'))
        self.control_widgets['pattern'] = pattern_widget
        
        # Überwachung
        monitor_widget = ControlWidget(parent, "Überwachung")
        monitor_widget.add_button("toggle", "Überwachung starten", 
                                 lambda: self._call_callback('toggle_monitoring'))
        self.control_widgets['monitor'] = monitor_widget
    
    def _create_users_tab(self, parent: tk.Widget):
        """Erstellt den Benutzer-Tab"""
        # Frame für Benutzer-Verwaltung
        user_frame = ttk.LabelFrame(parent, text="Benutzer/Gesichtsbilder")
        user_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        
        # Button für neuen Benutzer
        add_user_button = ttk.Button(
            user_frame, 
            text="Neuen Benutzer anlegen (Bilder hochladen)",
            command=lambda: self._call_callback('add_new_user')
        )
        add_user_button.pack(pady=5, padx=5, fill=tk.X)
        
        # Benutzer-Liste
        self.user_list_widget = UserListWidget(user_frame)
    
    def set_callback(self, name: str, callback: Callable):
        """Setzt einen Callback"""
        self.callbacks[name] = callback
    
    def _call_callback(self, name: str, *args, **kwargs):
        """Ruft einen Callback auf"""
        callback = self.callbacks.get(name)
        if callback:
            try:
                return callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Fehler beim Ausführen von Callback '{name}': {e}")
                messagebox.showerror("Fehler", f"Fehler beim Ausführen von '{name}': {e}")
        else:
            logger.warning(f"Callback '{name}' nicht gefunden")
    
    def update_monitoring_button(self, is_active: bool):
        """Aktualisiert den Überwachungsbutton"""
        text = "Überwachung stoppen" if is_active else "Überwachung starten"
        self.control_widgets['monitor'].configure_button('toggle', text=text)
    
    def update_status(self, camera_available: bool, mouse_available: bool = True):
        """Aktualisiert den Status"""
        if self.status_widget:
            self.status_widget.update_status(camera_available, mouse_available)
    
    def refresh_user_list(self, users: List[str]):
        """Aktualisiert die Benutzerliste"""
        if self.user_list_widget:
            self.user_list_widget.refresh(users)
    
    def add_mouse_log(self, message: str):
        """Fügt einen Maus-Log hinzu"""
        if self.mouse_log_widget:
            self.mouse_log_widget.add_log(message)
    
    def configure_camera_buttons(self, enabled: bool):
        """Aktiviert/Deaktiviert Kamera-Buttons"""
        state = "normal" if enabled else "disabled"
        camera_widget = self.control_widgets.get('camera')
        if camera_widget:
            camera_widget.configure_button('test', state=state)
            camera_widget.configure_button('diagnose', state=state)
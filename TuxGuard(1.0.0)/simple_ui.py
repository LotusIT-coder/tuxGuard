#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Simplified Modern UI
Stabile, vereinfachte Version ohne komplexe verschachtelte Frames
"""

import tkinter as tk
from tkinter import ttk, Text, Listbox, Menu, messagebox, filedialog, Frame, Label, Entry, Button, Canvas
import time
import logging
from typing import Optional, Callable, List

from config import Config

logger = logging.getLogger('TuxGuard.SimpleUI')

# Moderne Farbpalette
class ModernColors:
    PRIMARY = "#2C3E50"
    PRIMARY_LIGHT = "#34495E"
    PRIMARY_DARK = "#1A252F"
    SECONDARY = "#27AE60"
    SECONDARY_LIGHT = "#2ECC71"
    ACCENT = "#3498DB"
    ACCENT_LIGHT = "#5DADE2"
    BACKGROUND = "#ECF0F1"
    SURFACE = "#FFFFFF"
    SURFACE_DARK = "#BDC3C7"
    TEXT_PRIMARY = "#2C3E50"
    TEXT_SECONDARY = "#7F8C8D"
    TEXT_ON_PRIMARY = "#FFFFFF"
    SUCCESS = "#27AE60"
    WARNING = "#F39C12"
    ERROR = "#E74C3C"
    INFO = "#3498DB"

class SimplePinDialog:
    """Vereinfachter PIN-Dialog"""
    
    def __init__(self, parent: tk.Tk, title: str = "Sicherheitsprüfung", 
                 reason: str = "Bitte geben Sie Ihre PIN ein"):
        self.parent = parent
        self.title = title
        self.reason = reason
        self.result = None
        self.dialog = None
    
    def show(self) -> Optional[str]:
        """Zeigt den PIN-Dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry("350x200")
        self.dialog.configure(bg=ModernColors.SURFACE)
        
        # Zentrieren
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 350) // 2
        y = (sh - 200) // 2
        self.dialog.geometry(f"350x200+{x}+{y}")
        
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        self.dialog.resizable(False, False)
        
        # Icon und Titel
        Label(self.dialog, text="🔒", font=("Arial", 32),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(20, 5))
        
        Label(self.dialog, text=self.title, font=("Arial", 14, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack()
        
        Label(self.dialog, text=self.reason, font=("Arial", 9),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY).pack(pady=10)
        
        # PIN-Eingabe
        self.pin_entry = Entry(self.dialog, show='●', font=("Arial", 12),
                              bg=ModernColors.BACKGROUND, justify='center', bd=2)
        self.pin_entry.pack(pady=10, padx=30, fill=tk.X)
        self.pin_entry.focus_set()
        
        # Buttons
        button_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        button_frame.pack(pady=15)
        
        Button(button_frame, text="✓ OK", command=self._ok,
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=20, pady=5, bd=0).pack(side=tk.LEFT, padx=5)
        
        Button(button_frame, text="✕ Abbrechen", command=self._cancel,
               bg=ModernColors.ERROR, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=20, pady=5, bd=0).pack(side=tk.LEFT, padx=5)
        
        self.pin_entry.bind('<Return>', lambda e: self._ok())
        self.pin_entry.bind('<Escape>', lambda e: self._cancel())
        
        self.parent.wait_window(self.dialog)
        return self.result
    
    def _ok(self):
        self.result = self.pin_entry.get()
        self.pin_entry.delete(0, tk.END)
        self.dialog.destroy()
    
    def _cancel(self):
        self.result = None
        if hasattr(self, 'pin_entry'):
            self.pin_entry.delete(0, tk.END)
        self.dialog.destroy()

class SimpleUserListWidget:
    """Vereinfachtes Benutzer-Listen-Widget"""
    
    def __init__(self, parent):
        self.parent = parent
        self.listbox = None
        self.show_images_callback = None
        self.delete_user_callback = None
        self._create_widgets()
    
    def _create_widgets(self):
        container = Frame(self.parent, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        Label(container, text="👥 Registrierte Benutzer", font=("Arial", 11, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(pady=10)
        
        self.listbox = Listbox(container, font=("Arial", 10),
                              bg=ModernColors.BACKGROUND, selectmode=tk.SINGLE)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Kontext-Menü
        self.context_menu = Menu(container, tearoff=0)
        self.context_menu.add_command(label="Bilder anzeigen", command=self._show_images)
        self.context_menu.add_command(label="Benutzer löschen", command=self._delete_user)
        
        self.listbox.bind("<Button-3>", self._show_context_menu)
    
    def _show_context_menu(self, event):
        try:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(self.listbox.nearest(event.y))
            self.context_menu.post(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def _show_images(self):
        selection = self.listbox.curselection()
        if selection and self.show_images_callback:
            self.show_images_callback(self.listbox.get(selection[0]))
    
    def _delete_user(self):
        selection = self.listbox.curselection()
        if selection and self.delete_user_callback:
            self.delete_user_callback(self.listbox.get(selection[0]))
    
    def refresh(self, users: List[str]):
        self.listbox.delete(0, tk.END)
        for user in users:
            self.listbox.insert(tk.END, f"👤 {user}")
    
    def set_callbacks(self, show_images=None, delete_user=None):
        if show_images:
            self.show_images_callback = show_images
        if delete_user:
            self.delete_user_callback = delete_user

class SimpleLogWidget:
    """Vereinfachtes Log-Widget"""
    
    def __init__(self, parent, title="📋 Logs"):
        self.title = title
        self.log_text = None
        self._create_widgets(parent)
    
    def _create_widgets(self, parent):
        container = Frame(parent, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Header
        header = Frame(container, bg=ModernColors.SURFACE)
        header.pack(fill=tk.X, padx=10, pady=10)
        
        Label(header, text=self.title, font=("Arial", 10, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        Button(header, text="🧹 Löschen", command=self.clear_logs,
               bg=ModernColors.WARNING, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 8), bd=0).pack(side=tk.RIGHT)
        
        # Text-Widget
        text_container = Frame(container, bg=ModernColors.PRIMARY_DARK, bd=1, relief=tk.SUNKEN)
        text_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.log_text = Text(text_container, wrap=tk.WORD,
                            bg=ModernColors.PRIMARY_DARK,
                            fg=ModernColors.TEXT_ON_PRIMARY,
                            font=("Consolas", 9), bd=0, padx=5, pady=5,
                            state=tk.DISABLED)
        
        scrollbar = ttk.Scrollbar(text_container, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Tags für Farben
        self.log_text.tag_configure("INFO", foreground=ModernColors.INFO)
        self.log_text.tag_configure("WARNING", foreground=ModernColors.WARNING)
        self.log_text.tag_configure("ERROR", foreground=ModernColors.ERROR)
        self.log_text.tag_configure("SUCCESS", foreground=ModernColors.SUCCESS)
    
    def add_log(self, message: str, level: str = "INFO"):
        if not self.log_text:
            return
        
        self.log_text.configure(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "SUCCESS": "✅"}
        icon = icons.get(level, "ℹ️")
        
        self.log_text.insert(tk.END, f"[{timestamp}] {icon} {message}\n", level)
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see(tk.END)
    
    def clear_logs(self):
        if self.log_text:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.configure(state=tk.DISABLED)

class SimpleMainUI:
    """Vereinfachte Haupt-UI ohne komplexe Custom-Widgets"""
    
    def __init__(self, parent: tk.Tk):
        self.parent = parent
        self.callbacks = {}
        self.control_buttons = {}
        self.status_indicators = {}
        self.user_list_widget = None
        self.mouse_log_widget = None
        
        self._setup_window()
        self._create_widgets()
    
    def _setup_window(self):
        self.parent.title(f"🛡️ {Config.APP_NAME} v{Config.APP_VERSION}")
        self.parent.geometry("900x700")
        self.parent.configure(bg=ModernColors.BACKGROUND)
        self.parent.minsize(800, 600)
    
    def _create_widgets(self):
        # Hauptcontainer
        main_container = Frame(self.parent, bg=ModernColors.BACKGROUND)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header
        self._create_header(main_container)
        
        # Notebook für Tabs
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Tabs
        self._create_monitoring_tab()
        self._create_users_tab()
        self._create_logs_tab()
    
    def _create_header(self, parent):
        header = Frame(parent, bg=ModernColors.PRIMARY, relief=tk.RAISED, bd=2)
        header.pack(fill=tk.X, pady=(0, 10))
        
        # Titel
        title_frame = Frame(header, bg=ModernColors.PRIMARY)
        title_frame.pack(side=tk.LEFT, padx=20, pady=10)
        
        Label(title_frame, text="[*]", font=("Arial", 20, "bold"),
              bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY).pack(side=tk.LEFT, padx=(0, 10))
        
        Label(title_frame, text=f"{Config.APP_NAME} v{Config.APP_VERSION}",
              font=("Arial", 16, "bold"),
              bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY).pack(side=tk.LEFT)
        
        # Status
        status_frame = Frame(header, bg=ModernColors.SURFACE, relief=tk.SUNKEN, bd=1)
        status_frame.pack(side=tk.RIGHT, padx=20, pady=10)
        
        status_container = Frame(status_frame, bg=ModernColors.SURFACE, padx=10, pady=5)
        status_container.pack()
        
        for key, label in [("camera", "[CAM]"), ("mouse", "[MSE]"), ("monitoring", "[MON]")]:
            frame = Frame(status_container, bg=ModernColors.SURFACE)
            frame.pack(side=tk.LEFT, padx=5)
            
            indicator = Label(frame, text="●", font=("Arial", 10),
                            bg=ModernColors.SURFACE, fg=ModernColors.ERROR)
            indicator.pack(side=tk.LEFT)
            
            Label(frame, text=label, font=("Arial", 8),
                 bg=ModernColors.SURFACE).pack(side=tk.LEFT)
            
            self.status_indicators[key] = indicator
    
    def _create_monitoring_tab(self):
        frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(frame, text="🖥️ Überwachung")

        # Autostart-Checkbox oben platzieren
        autostart_frame = Frame(frame, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        autostart_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.autostart_var = tk.BooleanVar(value=False)
        autostart_cb = tk.Checkbutton(
            autostart_frame,
            text="TuxGuard beim Systemstart automatisch als Dienst starten",
            variable=self.autostart_var,
            command=self._on_autostart_changed,
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_PRIMARY,
            selectcolor=ModernColors.SECONDARY_LIGHT,
            font=("Arial", 10)
        )
        autostart_cb.pack(anchor="w", padx=10, pady=5)

        # Kamera-Kontrollen
        self._create_control_section(frame, "Kamera-Überwachung", [
            ("test_camera", "📷 Kamera testen", self._call_callback),
            ("diagnose_camera", "🔍 Kamera-Diagnose", self._call_callback)
        ])

        # Muster-Erkennung
        self._create_control_section(frame, "Muster-Erkennung", [
            ("train_pattern", "🎯 Mausbewegungen trainieren", self._call_callback)
        ])

        # Überwachung
        self._create_control_section(frame, "System-Überwachung", [
            ("toggle_monitoring", "▶️ Überwachung starten", self._call_callback)
        ])

        # Log-Widget
        self.mouse_log_widget = SimpleLogWidget(frame, "🖱️ Maus-Aktivitäten")

    def _on_autostart_changed(self):
        if hasattr(self, 'autostart_callback') and callable(self.autostart_callback):
            self.autostart_callback(self.autostart_var.get())

    def set_autostart_state(self, enabled: bool):
        if hasattr(self, 'autostart_var'):
            self.autostart_var.set(enabled)
    
    def _create_control_section(self, parent, title, buttons):
        container = Frame(parent, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        container.pack(fill=tk.X, padx=10, pady=5)
        
        Label(container, text=f"⚙️ {title}", font=("Arial", 10, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(pady=8)
        
        btn_frame = Frame(container, bg=ModernColors.SURFACE)
        btn_frame.pack(padx=10, pady=(0, 10))
        
        for key, text, callback in buttons:
            btn = Button(btn_frame, text=text,
                        command=lambda k=key: callback(k),
                        bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY,
                        font=("Arial", 9), padx=15, pady=5, bd=0, relief=tk.RAISED)
            btn.pack(fill=tk.X, pady=2)
            self.control_buttons[key] = btn
    
    def _create_users_tab(self):
        frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(frame, text="👥 Benutzer")
        
        # Neuer Benutzer
        add_frame = Frame(frame, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        add_frame.pack(fill=tk.X, padx=10, pady=10)
        
        Button(add_frame, text="➕ Neuen Benutzer hinzufügen",
               command=lambda: self._call_callback('add_new_user'),
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=20, pady=10, bd=0).pack(pady=15)
        
        # Benutzer-Liste
        self.user_list_widget = SimpleUserListWidget(frame)
    
    def _create_logs_tab(self):
        frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(frame, text="📋 Logs")
        
        self.system_log_widget = SimpleLogWidget(frame, "📋 System-Protokolle")
    
    def set_callback(self, name: str, callback: Callable):
        self.callbacks[name] = callback
        
        if name == 'show_user_images' and self.user_list_widget:
            self.user_list_widget.show_images_callback = callback
        elif name == 'delete_user' and self.user_list_widget:
            self.user_list_widget.delete_user_callback = callback
    
    def _call_callback(self, name: str, *args, **kwargs):
        callback = self.callbacks.get(name)
        if callback:
            try:
                return callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback-Fehler '{name}': {e}")
                messagebox.showerror("Fehler", str(e))
    
    def update_monitoring_button(self, is_active: bool):
        text = "⏹️ Überwachung stoppen" if is_active else "▶️ Überwachung starten"
        if 'toggle_monitoring' in self.control_buttons:
            self.control_buttons['toggle_monitoring'].config(text=text)
    
    def update_status(self, camera_available=None, mouse_available=None, monitoring_active=None):
        if camera_available is not None and 'camera' in self.status_indicators:
            color = ModernColors.SUCCESS if camera_available else ModernColors.ERROR
            self.status_indicators['camera'].config(fg=color)
        if mouse_available is not None and 'mouse' in self.status_indicators:
            color = ModernColors.SUCCESS if mouse_available else ModernColors.ERROR
            self.status_indicators['mouse'].config(fg=color)
        if monitoring_active is not None and 'monitoring' in self.status_indicators:
            color = ModernColors.SUCCESS if monitoring_active else ModernColors.ERROR
            self.status_indicators['monitoring'].config(fg=color)
    
    def refresh_user_list(self, users: List[str]):
        if self.user_list_widget:
            self.user_list_widget.refresh(users)
    
    def add_mouse_log(self, message: str, level: str = "INFO"):
        if self.mouse_log_widget:
            self.mouse_log_widget.add_log(message, level)
    
    def add_system_log(self, message: str, level: str = "INFO"):
        if hasattr(self, 'system_log_widget'):
            self.system_log_widget.add_log(message, level)
    
    def configure_camera_buttons(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for key in ['test_camera', 'diagnose_camera']:
            if key in self.control_buttons:
                self.control_buttons[key].config(state=state)

# Export für Kompatibilität
PinDialog = SimplePinDialog
UserListWidget = SimpleUserListWidget
LogWidget = SimpleLogWidget
StatusWidget = None  # Wird nicht mehr separat benötigt
MainUI = SimpleMainUI
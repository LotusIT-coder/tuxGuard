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

class ScrollFrame(Frame):
    """Ein Frame mit automatischem Scrollbar wenn Content zu groß ist"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        # Canvas mit Scrollbar
        self.canvas = Canvas(self, highlightthickness=0, bg=kwargs.get('bg', ModernColors.BACKGROUND))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        # Content Frame
        self.content_frame = Frame(self.canvas, bg=kwargs.get('bg', ModernColors.BACKGROUND))
        
        # Window im Canvas
        self.window = self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        
        # Scrollbar verbinden
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mousewheel Scrolling
        self.content_frame.bind("<MouseWheel>", self._on_mousewheel)
        self.content_frame.bind("<Button-4>", self._on_mousewheel)
        self.content_frame.bind("<Button-5>", self._on_mousewheel)
        
        # Update scroll region wenn Content ändert
        self.content_frame.bind("<Configure>", self._on_frame_configure)
        
        # Packing
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def _on_frame_configure(self, event=None):
        """Update scroll region wenn Frame ändert"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # Canvas width = content width
        self.canvas.itemconfigure(self.window, width=self.canvas.winfo_width())
    
    def _on_mousewheel(self, event):
        """Mousewheel Scrolling"""
        if event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(3, "units")
        elif event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-3, "units")

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
        self.dialog.geometry("420x280")
        self.dialog.configure(bg=ModernColors.SURFACE)
        self.dialog.transient(self.parent)
        
        # Zentrieren
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 420) // 2
        y = (sh - 280) // 2
        self.dialog.geometry(f"420x280+{x}+{y}")
        
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        # Wenn das Parent-Fenster bereits einen Grab hält (Sperr-Overlay),
        # darf hier kein zweiter Grab gesetzt werden.
        if self.parent.grab_current() is None:
            self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        self.dialog.minsize(380, 250)
        self.dialog.resizable(True, True)

        content = Frame(self.dialog, bg=ModernColors.SURFACE)
        content.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        # Icon und Titel
        Label(content, text="🔒", font=("Arial", 32),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(4, 2))

        Label(content, text=self.title, font=("Arial", 14, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack()

        Label(content, text=self.reason, font=("Arial", 9),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY,
              wraplength=360, justify="center").pack(pady=8)
        
        # PIN-Eingabe
        self.pin_entry = Entry(content, show='●', font=("Arial", 12),
                              bg=ModernColors.BACKGROUND, justify='center', bd=2)
        self.pin_entry.pack(pady=8, padx=18, fill=tk.X)
        self.pin_entry.focus_set()
        
        # Buttons
        button_frame = Frame(content, bg=ModernColors.SURFACE)
        button_frame.pack(side=tk.BOTTOM, pady=(10, 2))
        
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
        self.user_names = []
        self.show_images_callback = None
        self.add_images_callback = None
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
        self.context_menu.add_command(label="Bilder hinzufügen", command=self._add_images)
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
        user_name = self._selected_user_name()
        if user_name and self.show_images_callback:
            self.show_images_callback(user_name)

    def _add_images(self):
        user_name = self._selected_user_name()
        if user_name and self.add_images_callback:
            self.add_images_callback(user_name)
    
    def _delete_user(self):
        user_name = self._selected_user_name()
        if user_name and self.delete_user_callback:
            self.delete_user_callback(user_name)

    def _selected_user_name(self) -> Optional[str]:
        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if 0 <= index < len(self.user_names):
            return self.user_names[index]
        return None
    
    def refresh(self, users: List[str]):
        self.user_names = list(users)
        self.listbox.delete(0, tk.END)
        for user in users:
            self.listbox.insert(tk.END, f"👤 {user}")
    
    def set_callbacks(self, show_images=None, add_images=None, delete_user=None):
        if show_images:
            self.show_images_callback = show_images
        if add_images:
            self.add_images_callback = add_images
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

    def set_logs(self, lines: List[str]):
        if not self.log_text:
            return

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        for line in lines:
            self.log_text.insert(tk.END, line.rstrip() + "\n")
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
        self.security_log_widget = None
        self.security_mode_var = None
        self.deadman_timeout_var = None
        self.deadman_action_var = None
        self.deadman_timeout_row = None
        self.deadman_action_row = None
        self.minimize_behavior_var = None
        self.close_behavior_var = None
        self.monitor_preview_label = None
        self.monitor_preview_image = None
        self.monitor_preview_status_label = None
        
        self._setup_window()
        self._create_widgets()
    
    def _setup_window(self):
        self.parent.title(f"🛡️ {Config.APP_NAME} v{Config.APP_VERSION}")
        
        # Fenster aktualisieren um Bildschirmgröße zu ermitteln
        self.parent.update_idletasks()
        
        # Bildschirmdimensionen abrufen
        screen_width = self.parent.winfo_screenwidth()
        screen_height = self.parent.winfo_screenheight()
        
        # Optimale Fenstergröße: 85% der Bildschirmgröße, min 800x600, max 1400x900
        window_width = max(800, min(1400, int(screen_width * 0.85)))
        window_height = max(600, min(900, int(screen_height * 0.85)))
        
        # Fenster zentrieren
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        self.parent.geometry(f"{window_width}x{window_height}+{x}+{y}")
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
        
        for key, label in [("camera", "[CAM]"), ("monitoring", "[MON]")]:
            frame = Frame(status_container, bg=ModernColors.SURFACE)
            frame.pack(side=tk.LEFT, padx=5)
            
            indicator = Label(frame, text="●", font=("Arial", 10),
                            bg=ModernColors.SURFACE, fg=ModernColors.ERROR)
            indicator.pack(side=tk.LEFT)
            
            Label(frame, text=label, font=("Arial", 8),
                 bg=ModernColors.SURFACE).pack(side=tk.LEFT)
            
            self.status_indicators[key] = indicator
    
    def _create_monitoring_tab(self):
        scroll_frame = ScrollFrame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(scroll_frame, text="🖥️ Überwachung")
        frame = scroll_frame.content_frame

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

        # Überwachung
        self._create_control_section(frame, "System-Überwachung", [
            ("toggle_monitoring", "▶️ Überwachung starten", self._call_callback)
        ])

        self._create_monitor_preview_section(frame)
        self._create_security_settings_section(frame)

        # Log-Widget
        self.security_log_widget = SimpleLogWidget(frame, "🔐 Sicherheitsereignisse")

    def _on_autostart_changed(self):
        if hasattr(self, 'autostart_callback') and callable(self.autostart_callback):
            self.autostart_callback(self.autostart_var.get())

    def set_autostart_state(self, enabled: bool):
        if hasattr(self, 'autostart_var'):
            self.autostart_var.set(enabled)

    def set_security_settings(self, mode: str, deadman_timeout: int, deadman_action: str):
        if self.security_mode_var is not None:
            self.security_mode_var.set(mode)
        if self.deadman_timeout_var is not None:
            self.deadman_timeout_var.set(str(deadman_timeout))
        if self.deadman_action_var is not None:
            self.deadman_action_var.set(deadman_action)
        self._update_security_settings_visibility()

    def set_ui_behavior(self, minimize_behavior: str, close_behavior: str):
        if self.minimize_behavior_var is not None:
            self.minimize_behavior_var.set(minimize_behavior)
        if self.close_behavior_var is not None:
            self.close_behavior_var.set(close_behavior)
    
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

    def _create_security_settings_section(self, parent):
        container = Frame(parent, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        container.pack(fill=tk.X, padx=10, pady=5)

        Label(
            container,
            text="🛡️ Sicherheitsmodus",
            font=("Arial", 10, "bold"),
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_PRIMARY
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self.security_mode_var = tk.StringVar(value="strict_pin")
        self.deadman_timeout_var = tk.StringVar(value="60")
        self.deadman_action_var = tk.StringVar(value="suspend")

        mode_row = Frame(container, bg=ModernColors.SURFACE)
        mode_row.pack(fill=tk.X, padx=10, pady=4)
        Label(mode_row, text="Modus:", bg=ModernColors.SURFACE).pack(side=tk.LEFT)
        mode_box = ttk.Combobox(
            mode_row,
            textvariable=self.security_mode_var,
            state="readonly",
            values=["self_unlock", "strict_pin", "deadman"],
            width=18,
        )
        mode_box.pack(side=tk.LEFT, padx=10)
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._on_security_mode_changed())

        timeout_row = Frame(container, bg=ModernColors.SURFACE)
        timeout_row.pack(fill=tk.X, padx=10, pady=4)
        self.deadman_timeout_row = timeout_row
        Label(timeout_row, text="Totmannschalter (Sek.):", bg=ModernColors.SURFACE).pack(side=tk.LEFT)
        timeout_spin = tk.Spinbox(
            timeout_row,
            from_=10,
            to=3600,
            increment=10,
            textvariable=self.deadman_timeout_var,
            width=8,
            command=self._emit_security_settings,
        )
        timeout_spin.pack(side=tk.LEFT, padx=10)
        timeout_spin.bind("<FocusOut>", lambda _e: self._emit_security_settings())

        action_row = Frame(container, bg=ModernColors.SURFACE)
        action_row.pack(fill=tk.X, padx=10, pady=(4, 10))
        self.deadman_action_row = action_row
        Label(action_row, text="Aktion:", bg=ModernColors.SURFACE).pack(side=tk.LEFT)
        action_box = ttk.Combobox(
            action_row,
            textvariable=self.deadman_action_var,
            state="readonly",
            values=["suspend", "shutdown"],
            width=18,
        )
        action_box.pack(side=tk.LEFT, padx=10)
        action_box.bind("<<ComboboxSelected>>", lambda _e: self._emit_security_settings())

        ttk.Separator(container, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(6, 8))

        Label(
            container,
            text="🪟 UI-Verhalten",
            font=("Arial", 10, "bold"),
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_PRIMARY
        ).pack(anchor="w", padx=10, pady=(0, 4))

        self.minimize_behavior_var = tk.StringVar(value="tray")
        self.close_behavior_var = tk.StringVar(value="ask")

        minimize_row = Frame(container, bg=ModernColors.SURFACE)
        minimize_row.pack(fill=tk.X, padx=10, pady=4)
        Label(minimize_row, text="Beim Minimieren:", bg=ModernColors.SURFACE).pack(side=tk.LEFT)
        minimize_box = ttk.Combobox(
            minimize_row,
            textvariable=self.minimize_behavior_var,
            state="readonly",
            values=["tray", "normal"],
            width=18,
        )
        minimize_box.pack(side=tk.LEFT, padx=10)
        minimize_box.bind("<<ComboboxSelected>>", lambda _e: self._emit_ui_behavior_settings())

        close_row = Frame(container, bg=ModernColors.SURFACE)
        close_row.pack(fill=tk.X, padx=10, pady=4)
        Label(close_row, text="Beim Schließen:", bg=ModernColors.SURFACE).pack(side=tk.LEFT)
        close_box = ttk.Combobox(
            close_row,
            textvariable=self.close_behavior_var,
            state="readonly",
            values=["ask", "tray", "quit"],
            width=18,
        )
        close_box.pack(side=tk.LEFT, padx=10)
        close_box.bind("<<ComboboxSelected>>", lambda _e: self._emit_ui_behavior_settings())

        Button(
            container,
            text="🔐 Weiteres Admin-Passwort hinzufügen",
            command=lambda: self._call_callback('add_admin_password'),
            bg=ModernColors.PRIMARY,
            fg=ModernColors.TEXT_ON_PRIMARY,
            font=("Arial", 9, "bold"),
            padx=12,
            pady=5,
            bd=0,
        ).pack(anchor="w", padx=10, pady=(8, 10))

        self._update_security_settings_visibility()

    def _create_monitor_preview_section(self, parent):
        container = Frame(parent, bg=ModernColors.SURFACE, relief=tk.RIDGE, bd=2)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        Label(
            container,
            text="📹 Live-Vorschau",
            font=("Arial", 10, "bold"),
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_PRIMARY,
        ).pack(anchor="w", padx=10, pady=(8, 4))

        preview_frame = Frame(container, bg="#101820", height=220)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        preview_frame.pack_propagate(False)

        self.monitor_preview_label = Label(
            preview_frame,
            text="Überwachung nicht aktiv",
            font=("Arial", 11),
            bg="#101820",
            fg="#d0d7de",
            anchor="center",
            justify=tk.CENTER,
        )
        self.monitor_preview_label.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.monitor_preview_status_label = Label(
            container,
            text="Status: Warte auf Start der Überwachung",
            font=("Arial", 9),
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_SECONDARY,
            anchor="w",
        )
        self.monitor_preview_status_label.pack(fill=tk.X, padx=10, pady=(0, 10))

    def _on_security_mode_changed(self):
        self._update_security_settings_visibility()
        self._emit_security_settings()

    def _update_security_settings_visibility(self):
        is_deadman = self.security_mode_var is not None and self.security_mode_var.get() == "deadman"
        if self.deadman_timeout_row is not None:
            if is_deadman:
                self.deadman_timeout_row.pack(fill=tk.X, padx=10, pady=4)
            else:
                self.deadman_timeout_row.pack_forget()
        if self.deadman_action_row is not None:
            if is_deadman:
                self.deadman_action_row.pack(fill=tk.X, padx=10, pady=(4, 10))
            else:
                self.deadman_action_row.pack_forget()

    def _emit_security_settings(self):
        callback = self.callbacks.get("security_settings_changed")
        if callback:
            try:
                callback(
                    self.security_mode_var.get(),
                    self.deadman_timeout_var.get(),
                    self.deadman_action_var.get(),
                )
            except Exception as e:
                logger.error(f"Sicherheitsmodus-Callback fehlgeschlagen: {e}")

    def _emit_ui_behavior_settings(self):
        callback = self.callbacks.get("ui_behavior_changed")
        if callback:
            try:
                callback(
                    self.minimize_behavior_var.get(),
                    self.close_behavior_var.get(),
                )
            except Exception as e:
                logger.error(f"UI-Verhalten-Callback fehlgeschlagen: {e}")
    
    def _create_users_tab(self):
        scroll_frame = ScrollFrame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(scroll_frame, text="👥 Benutzer")
        frame = scroll_frame.content_frame
        
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
        scroll_frame = ScrollFrame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(scroll_frame, text="📋 Logs")
        frame = scroll_frame.content_frame
        
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
    
    def update_status(self, camera_available=None, monitoring_active=None):
        if camera_available is not None and 'camera' in self.status_indicators:
            color = ModernColors.SUCCESS if camera_available else ModernColors.ERROR
            self.status_indicators['camera'].config(fg=color)
        if monitoring_active is not None and 'monitoring' in self.status_indicators:
            color = ModernColors.SUCCESS if monitoring_active else ModernColors.ERROR
            self.status_indicators['monitoring'].config(fg=color)
    
    def refresh_user_list(self, users: List[str]):
        if self.user_list_widget:
            self.user_list_widget.refresh(users)
    
    def add_security_log(self, message: str, level: str = "INFO"):
        if self.security_log_widget:
            self.security_log_widget.add_log(message, level)

    def add_system_log(self, message: str, level: str = "INFO"):
        if hasattr(self, 'system_log_widget'):
            self.system_log_widget.add_log(message, level)

    def update_monitor_preview(self, photo_image=None, status_text: str = "", status_level: str = "INFO"):
        if self.monitor_preview_label is None:
            return

        level_colors = {
            "INFO": ModernColors.INFO,
            "SUCCESS": ModernColors.SUCCESS,
            "WARNING": ModernColors.WARNING,
            "ERROR": ModernColors.ERROR,
        }

        if photo_image is not None:
            self.monitor_preview_image = photo_image
            self.monitor_preview_label.config(image=photo_image, text="")
        else:
            self.monitor_preview_image = None
            self.monitor_preview_label.config(image="", text="Kein Kamerabild verfügbar")

        if self.monitor_preview_status_label is not None:
            self.monitor_preview_status_label.config(
                text=f"Status: {status_text or 'Keine Daten'}",
                fg=level_colors.get(status_level, ModernColors.TEXT_SECONDARY),
            )

    def clear_monitor_preview(self, message: str = "Überwachung nicht aktiv"):
        if self.monitor_preview_label is not None:
            self.monitor_preview_image = None
            self.monitor_preview_label.config(image="", text=message)
        if self.monitor_preview_status_label is not None:
            self.monitor_preview_status_label.config(
                text="Status: Warte auf Start der Überwachung",
                fg=ModernColors.TEXT_SECONDARY,
            )
    
    def configure_camera_buttons(self, enabled: bool):
        # Diagnose/Test sollen auch im Fehlerfall nutzbar bleiben.
        state = tk.NORMAL
        for key in ['test_camera', 'diagnose_camera']:
            if key in self.control_buttons:
                self.control_buttons[key].config(state=state)

# Export für Kompatibilität
PinDialog = SimplePinDialog
UserListWidget = SimpleUserListWidget
LogWidget = SimpleLogWidget
StatusWidget = None  # Wird nicht mehr separat benötigt
MainUI = SimpleMainUI


# ===========================================================================
# Login / Passwort-Dialoge & Erststart-Wizard
# ===========================================================================

class PasswordDialog:
    """Modaler Passwort-Dialog mit optionalem Benutzernamen-Hinweis."""

    def __init__(self, parent: tk.Tk, title: str = "Passwort erforderlich",
                 reason: str = "Bitte Passwort eingeben",
                 username: Optional[str] = None,
                 allow_cancel: bool = True):
        self.parent = parent
        self.title = title
        self.reason = reason
        self.username = username
        self.allow_cancel = allow_cancel
        self.result: Optional[str] = None
        self.dialog: Optional[tk.Toplevel] = None

    def show(self) -> Optional[str]:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry("380x240")
        self.dialog.configure(bg=ModernColors.SURFACE)
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 380) // 2
        y = (sh - 240) // 2
        self.dialog.geometry(f"380x240+{x}+{y}")
        self.dialog.attributes("-topmost", True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol(
            "WM_DELETE_WINDOW",
            self._cancel if self.allow_cancel else (lambda: None),
        )

        Label(self.dialog, text="🔑", font=("Arial", 28),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(15, 0))
        Label(self.dialog, text=self.title, font=("Arial", 13, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(pady=(4, 0))
        if self.username:
            Label(self.dialog, text=f"Benutzer: {self.username}",
                  font=("Arial", 10, "bold"),
                  bg=ModernColors.SURFACE, fg=ModernColors.ACCENT).pack()
        Label(self.dialog, text=self.reason, font=("Arial", 9),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY,
              wraplength=340, justify="center").pack(pady=(4, 6))

        self.password_entry = Entry(self.dialog, show="●", font=("Arial", 12),
                                    bg=ModernColors.BACKGROUND, justify="center", bd=2)
        self.password_entry.pack(padx=30, fill=tk.X)
        self.password_entry.focus_set()

        button_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        button_frame.pack(pady=14)

        Button(button_frame, text="✓ OK", command=self._ok,
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=22, pady=5, bd=0).pack(side=tk.LEFT, padx=5)
        if self.allow_cancel:
            Button(button_frame, text="✕ Abbrechen", command=self._cancel,
                   bg=ModernColors.ERROR, fg=ModernColors.TEXT_ON_PRIMARY,
                   font=("Arial", 10, "bold"), padx=18, pady=5, bd=0).pack(side=tk.LEFT, padx=5)

        self.password_entry.bind("<Return>", lambda _e: self._ok())
        if self.allow_cancel:
            self.password_entry.bind("<Escape>", lambda _e: self._cancel())

        self.parent.wait_window(self.dialog)
        return self.result

    def _ok(self):
        self.result = self.password_entry.get()
        self.password_entry.delete(0, tk.END)
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        if hasattr(self, "password_entry"):
            self.password_entry.delete(0, tk.END)
        self.dialog.destroy()


class LoginDialog:
    """Login-Dialog mit Benutzerauswahl + Passwort."""

    def __init__(self, parent: tk.Tk, users: List[str]):
        self.parent = parent
        self.users = users
        self.result: Optional[tuple] = None  # (username, password)
        self.dialog: Optional[tk.Toplevel] = None

    def show(self) -> Optional[tuple]:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("TuxGuard – Anmeldung")
        self.dialog.geometry("400x300")
        self.dialog.configure(bg=ModernColors.SURFACE)
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 400) // 2
        y = (sh - 300) // 2
        self.dialog.geometry(f"400x300+{x}+{y}")
        self.dialog.attributes("-topmost", True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)

        Label(self.dialog, text="🛡️", font=("Arial", 32),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(14, 0))
        Label(self.dialog, text="TuxGuard – Anmeldung",
              font=("Arial", 14, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack()

        Label(self.dialog, text="Benutzer:", bg=ModernColors.SURFACE,
              font=("Arial", 10)).pack(pady=(12, 0))
        self.user_var = tk.StringVar(value=self.users[0] if self.users else "")
        user_box = ttk.Combobox(self.dialog, textvariable=self.user_var,
                                values=self.users, state="readonly", width=30)
        user_box.pack(pady=4)

        Label(self.dialog, text="Passwort:", bg=ModernColors.SURFACE,
              font=("Arial", 10)).pack(pady=(8, 0))
        self.password_entry = Entry(self.dialog, show="●", font=("Arial", 12),
                                    bg=ModernColors.BACKGROUND, justify="center", bd=2)
        self.password_entry.pack(padx=40, fill=tk.X, pady=4)
        self.password_entry.focus_set()

        button_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        button_frame.pack(pady=14)
        Button(button_frame, text="✓ Anmelden", command=self._ok,
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=22, pady=5, bd=0).pack(side=tk.LEFT, padx=5)
        Button(button_frame, text="✕ Beenden", command=self._cancel,
               bg=ModernColors.ERROR, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10, "bold"), padx=18, pady=5, bd=0).pack(side=tk.LEFT, padx=5)

        self.password_entry.bind("<Return>", lambda _e: self._ok())
        self.dialog.bind("<Escape>", lambda _e: self._cancel())

        self.parent.wait_window(self.dialog)
        return self.result

    def _ok(self):
        username = self.user_var.get().strip()
        password = self.password_entry.get()
        if not username or not password:
            messagebox.showerror("Fehler", "Bitte Benutzer und Passwort angeben.",
                                 parent=self.dialog)
            return
        self.result = (username, password)
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()


class FirstRunWizard:
    """Erststart-Wizard zur Anlage des ersten Admin-Benutzers."""

    def __init__(self, parent: tk.Tk, capture_face_callback: Optional[Callable] = None):
        """``capture_face_callback`` wird aufgerufen, sobald der Benutzer
        ein Foto über die Webcam aufnehmen möchte. Es soll den Pfad zum
        gespeicherten Bild zurückgeben (oder ``None``).
        """
        self.parent = parent
        self.capture_face_callback = capture_face_callback
        self.result: Optional[dict] = None
        self.dialog: Optional[tk.Toplevel] = None
        self._captured_image_path: Optional[str] = None
        self._selected_image_paths: List[str] = []

    def show(self) -> Optional[dict]:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("TuxGuard – Erststart-Assistent")
        self.dialog.geometry("520x520")
        self.dialog.configure(bg=ModernColors.SURFACE)
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 520) // 2
        y = (sh - 520) // 2
        self.dialog.geometry(f"520x520+{x}+{y}")
        self.dialog.attributes("-topmost", True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)

        Label(self.dialog, text="🛡️ Willkommen bei TuxGuard",
              font=("Arial", 16, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(14, 4))
        Label(self.dialog,
              text="Bitte legen Sie den ersten Administrator an.\n"
                   "Diese Person darf später weitere Benutzer und Einstellungen verwalten.",
              font=("Arial", 10),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY,
              justify="center").pack(pady=(0, 10))

        form = Frame(self.dialog, bg=ModernColors.SURFACE)
        form.pack(fill=tk.X, padx=30)

        def add_row(label: str) -> Entry:
            Label(form, text=label, bg=ModernColors.SURFACE,
                  font=("Arial", 10)).pack(anchor="w", pady=(8, 0))
            entry = Entry(form, font=("Arial", 11),
                          bg=ModernColors.BACKGROUND, bd=2)
            entry.pack(fill=tk.X)
            return entry

        self.name_entry = add_row("Benutzername:")
        self.password_entry = add_row(
            f"Passwort (min. {Config.MIN_PASSWORD_LENGTH} Zeichen):"
        )
        self.password_entry.config(show="●")
        self.password_repeat_entry = add_row("Passwort wiederholen:")
        self.password_repeat_entry.config(show="●")
        self.pin_entry = add_row(
            f"PIN (für Schnellaktionen, min. {Config.MIN_PIN_LENGTH} Zeichen):"
        )
        self.pin_entry.config(show="●")

        # Gesichtsbild
        face_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        face_frame.pack(fill=tk.X, padx=30, pady=(14, 4))
        Label(face_frame, text="Gesichtsbild für Erkennung:",
              bg=ModernColors.SURFACE, font=("Arial", 10, "bold")).pack(anchor="w")
        self.face_status_label = Label(face_frame,
                                       text="Noch kein Bild ausgewählt.",
                                       bg=ModernColors.SURFACE,
                                       fg=ModernColors.TEXT_SECONDARY,
                                       font=("Arial", 9))
        self.face_status_label.pack(anchor="w", pady=(2, 4))

        face_buttons = Frame(face_frame, bg=ModernColors.SURFACE)
        face_buttons.pack(anchor="w")
        Button(face_buttons, text="📷 Webcam-Foto aufnehmen",
               command=self._capture_face,
               bg=ModernColors.ACCENT, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 9), bd=0, padx=10, pady=4).pack(side=tk.LEFT, padx=(0, 6))
        Button(face_buttons, text="📁 Bilddatei wählen",
               command=self._pick_face_files,
               bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 9), bd=0, padx=10, pady=4).pack(side=tk.LEFT)

        # Buttons
        button_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        button_frame.pack(side=tk.BOTTOM, pady=14)
        Button(button_frame, text="✓ Admin anlegen", command=self._submit,
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 11, "bold"), padx=22, pady=6, bd=0).pack(side=tk.LEFT, padx=6)
        Button(button_frame, text="✕ Abbrechen", command=self._cancel,
               bg=ModernColors.ERROR, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 10), padx=14, pady=6, bd=0).pack(side=tk.LEFT, padx=6)

        self.parent.wait_window(self.dialog)
        return self.result

    # -- internal handlers ------------------------------------------------

    def _capture_face(self):
        if not self.capture_face_callback:
            messagebox.showinfo("Webcam nicht verfügbar",
                                "Webcam-Aufnahme ist nicht verfügbar. Bitte Datei wählen.",
                                parent=self.dialog)
            return
        path = self.capture_face_callback()
        if path:
            self._captured_image_path = path
            self._selected_image_paths = [path]
            self.face_status_label.config(
                text=f"📷 Webcam-Aufnahme bereit: {path}",
                fg=ModernColors.SUCCESS,
            )

    def _pick_face_files(self):
        paths = filedialog.askopenfilenames(
            title="Gesichtsbild auswählen",
            filetypes=Config.IMAGE_FILE_TYPES,
            parent=self.dialog,
        )
        if paths:
            self._selected_image_paths = list(paths)
            self.face_status_label.config(
                text=f"📁 {len(paths)} Bild(er) ausgewählt",
                fg=ModernColors.SUCCESS,
            )

    def _submit(self):
        name = self.name_entry.get().strip()
        password = self.password_entry.get()
        password2 = self.password_repeat_entry.get()
        pin = self.pin_entry.get()

        if not name:
            messagebox.showerror("Fehler", "Benutzername darf nicht leer sein.",
                                 parent=self.dialog)
            return
        if len(password) < Config.MIN_PASSWORD_LENGTH:
            messagebox.showerror(
                "Fehler",
                f"Passwort muss mindestens {Config.MIN_PASSWORD_LENGTH} Zeichen lang sein.",
                parent=self.dialog)
            return
        if password != password2:
            messagebox.showerror("Fehler", "Passwörter stimmen nicht überein.",
                                 parent=self.dialog)
            return
        if len(pin) < Config.MIN_PIN_LENGTH:
            messagebox.showerror(
                "Fehler",
                f"PIN muss mindestens {Config.MIN_PIN_LENGTH} Zeichen lang sein.",
                parent=self.dialog)
            return
        if not self._selected_image_paths:
            messagebox.showerror(
                "Fehler",
                "Bitte mindestens ein Gesichtsbild bereitstellen.",
                parent=self.dialog)
            return

        self.result = {
            "name": name,
            "password": password,
            "pin": pin,
            "image_paths": list(self._selected_image_paths),
            "captured_image": self._captured_image_path,
        }
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()


class MasterPasswordSetupDialog:
    """Setzt das Master-Passwort, falls der Installer es nicht erledigt hat."""

    def __init__(self, parent: tk.Tk):
        self.parent = parent
        self.result: Optional[str] = None  # eingegebenes Passwort
        self.dialog: Optional[tk.Toplevel] = None

    def show(self) -> Optional[str]:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Master-Passwort festlegen")
        self.dialog.geometry("440x320")
        self.dialog.configure(bg=ModernColors.SURFACE)
        self.dialog.attributes("-topmost", True)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        Label(self.dialog, text="🔐 TuxGuard Master-Passwort",
              font=("Arial", 14, "bold"),
              bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(16, 6))
        Label(self.dialog,
              text=("Das Master-Passwort schützt zentrale Aktionen.\n"
                    "Es kann später NUR mit dem Recovery-Code geändert werden."),
              font=("Arial", 9),
              bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY,
              justify="center").pack(pady=(0, 10))

        form = Frame(self.dialog, bg=ModernColors.SURFACE)
        form.pack(padx=30, fill=tk.X)

        Label(form, text=f"Master-Passwort (min. {Config.MIN_PASSWORD_LENGTH} Zeichen):",
              bg=ModernColors.SURFACE, font=("Arial", 10)).pack(anchor="w", pady=(8, 0))
        self.pw1 = Entry(form, show="●", font=("Arial", 11),
                         bg=ModernColors.BACKGROUND, bd=2)
        self.pw1.pack(fill=tk.X)

        Label(form, text="Master-Passwort wiederholen:",
              bg=ModernColors.SURFACE, font=("Arial", 10)).pack(anchor="w", pady=(8, 0))
        self.pw2 = Entry(form, show="●", font=("Arial", 11),
                         bg=ModernColors.BACKGROUND, bd=2)
        self.pw2.pack(fill=tk.X)

        button_frame = Frame(self.dialog, bg=ModernColors.SURFACE)
        button_frame.pack(side=tk.BOTTOM, pady=18)
        Button(button_frame, text="✓ Festlegen", command=self._ok,
               bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
               font=("Arial", 11, "bold"), padx=22, pady=6, bd=0).pack(side=tk.LEFT, padx=6)

        self.pw1.focus_set()
        self.parent.wait_window(self.dialog)
        return self.result

    def _ok(self):
        a = self.pw1.get()
        b = self.pw2.get()
        if len(a) < Config.MIN_PASSWORD_LENGTH:
            messagebox.showerror(
                "Fehler",
                f"Passwort muss mindestens {Config.MIN_PASSWORD_LENGTH} Zeichen lang sein.",
                parent=self.dialog)
            return
        if a != b:
            messagebox.showerror("Fehler", "Passwörter stimmen nicht überein.",
                                 parent=self.dialog)
            return
        self.result = a
        self.dialog.destroy()


def show_recovery_code(parent: tk.Tk, code: str, title: str = "Recovery-Code") -> None:
    """Zeigt einen Recovery-Code modal an und erlaubt das Kopieren."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("460x260")
    win.configure(bg=ModernColors.SURFACE)
    win.attributes("-topmost", True)
    win.grab_set()

    Label(win, text="🔑 Recovery-Code", font=("Arial", 16, "bold"),
          bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY).pack(pady=(14, 4))
    Label(win,
          text=("Bewahren Sie diesen Code sicher auf!\n"
                "Er ist die EINZIGE Möglichkeit, das Master-Passwort zu ändern."),
          font=("Arial", 10), bg=ModernColors.SURFACE,
          fg=ModernColors.TEXT_SECONDARY, justify="center").pack(pady=(0, 10))

    code_entry = Entry(win, font=("Consolas", 16, "bold"),
                       justify="center", bd=2, bg=ModernColors.BACKGROUND)
    code_entry.insert(0, code)
    code_entry.config(state="readonly")
    code_entry.pack(padx=30, fill=tk.X, pady=(0, 10))

    def copy_to_clipboard():
        win.clipboard_clear()
        win.clipboard_append(code)
        messagebox.showinfo("Kopiert",
                            "Recovery-Code in Zwischenablage kopiert.",
                            parent=win)

    btns = Frame(win, bg=ModernColors.SURFACE)
    btns.pack(pady=10)
    Button(btns, text="📋 Kopieren", command=copy_to_clipboard,
           bg=ModernColors.ACCENT, fg=ModernColors.TEXT_ON_PRIMARY,
           font=("Arial", 10, "bold"), padx=16, pady=5, bd=0).pack(side=tk.LEFT, padx=6)
    Button(btns, text="✓ Ich habe den Code gespeichert", command=win.destroy,
           bg=ModernColors.SUCCESS, fg=ModernColors.TEXT_ON_PRIMARY,
           font=("Arial", 10, "bold"), padx=16, pady=5, bd=0).pack(side=tk.LEFT, padx=6)

    parent.wait_window(win)


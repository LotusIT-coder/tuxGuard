#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Modern UI Module
Modernes, ansprechendes UI mit 3D-Effekten und abgerundeten Ecken
"""

import tkinter as tk
from tkinter import ttk, Text, Listbox, Menu, messagebox, simpledialog, filedialog
from tkinter import Toplevel, Label, Entry, Button, Frame, Canvas
import time
import logging
from typing import Optional, Callable, List
from pathlib import Path
import math

from config import Config

logger = logging.getLogger('TuxGuard.ModernUI')

# Moderne Farbpalette
class ModernColors:
    """Moderne Farbpalette für TuxGuard"""
    # Primärfarben (Blau-Grau Palette)
    PRIMARY = "#2C3E50"          # Dunkelblau-Grau
    PRIMARY_LIGHT = "#34495E"     # Helles Dunkelblau-Grau
    PRIMARY_DARK = "#1A252F"      # Dunkles Blau-Grau
    
    # Sekundärfarben (Grün für Erfolg)
    SECONDARY = "#27AE60"         # Grün
    SECONDARY_LIGHT = "#2ECC71"   # Hellgrün
    SECONDARY_DARK = "#229954"    # Dunkelgrün
    
    # Akzentfarben
    ACCENT = "#3498DB"            # Blau
    ACCENT_LIGHT = "#5DADE2"      # Hellblau
    ACCENT_DARK = "#2980B9"       # Dunkelblau
    
    # Neutrale Farben
    BACKGROUND = "#ECF0F1"        # Hellgrau
    SURFACE = "#FFFFFF"           # Weiß
    SURFACE_DARK = "#BDC3C7"      # Mittelgrau
    
    # Text
    TEXT_PRIMARY = "#2C3E50"      # Dunkel
    TEXT_SECONDARY = "#7F8C8D"    # Grau
    TEXT_ON_PRIMARY = "#FFFFFF"   # Weiß auf Primärfarbe
    
    # Status-Farben
    SUCCESS = "#27AE60"           # Grün
    WARNING = "#F39C12"           # Orange
    ERROR = "#E74C3C"             # Rot
    INFO = "#3498DB"              # Blau

class RoundedFrame(Frame):
    """Frame mit abgerundeten Ecken und 3D-Effekt"""
    
    def __init__(self, parent, bg_color=ModernColors.SURFACE, 
                 border_color=ModernColors.SURFACE_DARK, 
                 shadow_color=ModernColors.PRIMARY_DARK,
                 corner_radius=15, elevation=5, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.bg_color = bg_color
        self.border_color = border_color
        self.shadow_color = shadow_color
        self.corner_radius = corner_radius
        self.elevation = elevation
        
        self.canvas = Canvas(self, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.inner_frame = Frame(self.canvas, bg=bg_color)
        self.canvas_frame = self.canvas.create_window(0, 0, anchor="nw", window=self.inner_frame)
        
        self.bind('<Configure>', self._on_configure)
        self.inner_frame.bind('<Configure>', self._on_frame_configure)
    
    def _on_configure(self, event):
        """Handle resize events"""
        self._draw_rounded_rect()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
        # Update inner frame size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        padding = self.corner_radius
        
        self.canvas.itemconfig(self.canvas_frame, 
                              width=canvas_width - 2 * padding,
                              height=canvas_height - 2 * padding)
        self.canvas.coords(self.canvas_frame, padding, padding)
    
    def _on_frame_configure(self, event):
        """Handle inner frame resize"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _draw_rounded_rect(self):
        """Zeichnet abgerundetes Rechteck mit 3D-Effekt"""
        self.canvas.delete("rounded_rect")
        
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        # Schatten (3D-Effekt)
        shadow_offset = self.elevation
        self._draw_rounded_rectangle(
            shadow_offset, shadow_offset, 
            width + shadow_offset, height + shadow_offset,
            self.corner_radius, fill="#9E9E9E",  # Gray shadow
            outline="", tags="rounded_rect"
        )
        
        # Hauptform
        self._draw_rounded_rectangle(
            0, 0, width, height,
            self.corner_radius, fill=self.bg_color,
            outline=self.border_color, width=2, tags="rounded_rect"
        )
    
    def _draw_rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
        """Zeichnet ein abgerundetes Rechteck"""
        points = []
        
        # Obere linke Ecke
        for i in range(0, 90, 5):
            angle = math.radians(i + 180)
            x = x1 + radius + radius * math.cos(angle)
            y = y1 + radius + radius * math.sin(angle)
            points.extend([x, y])
        
        # Obere rechte Ecke
        for i in range(0, 90, 5):
            angle = math.radians(i + 270)
            x = x2 - radius + radius * math.cos(angle)
            y = y1 + radius + radius * math.sin(angle)
            points.extend([x, y])
        
        # Untere rechte Ecke
        for i in range(0, 90, 5):
            angle = math.radians(i)
            x = x2 - radius + radius * math.cos(angle)
            y = y2 - radius + radius * math.sin(angle)
            points.extend([x, y])
        
        # Untere linke Ecke
        for i in range(0, 90, 5):
            angle = math.radians(i + 90)
            x = x1 + radius + radius * math.cos(angle)
            y = y2 - radius + radius * math.sin(angle)
            points.extend([x, y])
        
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

class ModernButton(Canvas):
    """Moderner Button mit 3D-Effekt und Hover-Animation"""
    
    def __init__(self, parent, text="Button", command=None, 
                 bg_color=ModernColors.PRIMARY, 
                 hover_color=ModernColors.PRIMARY_LIGHT,
                 text_color=ModernColors.TEXT_ON_PRIMARY,
                 disabled_color=ModernColors.SURFACE_DARK,
                 corner_radius=10, elevation=3, 
                 width=120, height=40, **kwargs):
        
        super().__init__(parent, width=width, height=height, 
                        highlightthickness=0, **kwargs)
        
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.disabled_color = disabled_color
        self.corner_radius = corner_radius
        self.elevation = elevation
        self.width = width
        self.height = height
        
        self.is_hovered = False
        self.is_pressed = False
        self.is_enabled = True
        
        self._setup_bindings()
        self.after(1, self._draw_button)
    
    def _setup_bindings(self):
        """Setup event bindings"""
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_configure)
    
    def _on_enter(self, event):
        """Mouse enter event"""
        if self.is_enabled:
            self.is_hovered = True
            self._draw_button()
    
    def _on_leave(self, event):
        """Mouse leave event"""
        self.is_hovered = False
        self.is_pressed = False
        self._draw_button()
    
    def _on_press(self, event):
        """Mouse press event"""
        if self.is_enabled:
            self.is_pressed = True
            self._draw_button()
    
    def _on_release(self, event):
        """Mouse release event"""
        if self.is_enabled and self.is_pressed:
            self.is_pressed = False
            self._draw_button()
            if self.command:
                self.command()
    
    def _on_configure(self, event):
        """Handle resize"""
        self.width = event.width
        self.height = event.height
        self._draw_button()
    
    def _draw_button(self):
        """Zeichnet den Button"""
        self.delete("all")
        
        # Farbe bestimmen
        if not self.is_enabled:
            bg = self.disabled_color
            text_color = ModernColors.TEXT_SECONDARY
        elif self.is_pressed:
            bg = self.bg_color
            text_color = self.text_color
        elif self.is_hovered:
            bg = self.hover_color
            text_color = self.text_color
        else:
            bg = self.bg_color
            text_color = self.text_color
        
        # Schatten (nur wenn nicht gedrückt)
        if self.is_enabled and not self.is_pressed:
            shadow_offset = self.elevation
            self._draw_rounded_rectangle(
                shadow_offset, shadow_offset,
                self.width + shadow_offset - 1, self.height + shadow_offset - 1,
                self.corner_radius, fill="#757575"  # Gray shadow
            )
        
        # Button-Körper
        offset = 2 if self.is_pressed else 0
        self._draw_rounded_rectangle(
            offset, offset, self.width - 1 + offset, self.height - 1 + offset,
            self.corner_radius, fill=bg, outline=ModernColors.SURFACE_DARK
        )
        
        # Text
        self.create_text(
            self.width // 2 + offset, self.height // 2 + offset,
            text=self.text, fill=text_color, font=("Arial", 10, "bold")
        )
    
    def _draw_rounded_rectangle(self, x1, y1, x2, y2, radius, **kwargs):
        """Zeichnet abgerundetes Rechteck"""
        points = []
        steps = 10
        
        # Ecken berechnen
        for corner, start_angle in [((x1 + radius, y1 + radius), 180),
                                   ((x2 - radius, y1 + radius), 270),
                                   ((x2 - radius, y2 - radius), 0),
                                   ((x1 + radius, y2 - radius), 90)]:
            for i in range(steps + 1):
                angle = math.radians(start_angle + (90 * i / steps))
                x = corner[0] + radius * math.cos(angle)
                y = corner[1] + radius * math.sin(angle)
                points.extend([x, y])
        
        return self.create_polygon(points, smooth=True, **kwargs)
    
    def configure_button(self, text=None, state=None, command=None):
        """Konfiguriert den Button"""
        if text is not None:
            self.text = text
        if state is not None:
            self.is_enabled = (state == "normal")
        if command is not None:
            self.command = command
        self._draw_button()

class ModernPinDialog:
    """Moderner PIN-Dialog mit 3D-Effekt"""
    
    def __init__(self, parent: tk.Tk, title: str = "Sicherheitsprüfung", 
                 reason: str = "Bitte geben Sie Ihre PIN ein"):
        self.parent = parent
        self.title = title
        self.reason = reason
        self.result = None
        self.dialog = None
    
    def show(self) -> Optional[str]:
        """Zeigt den modernen PIN-Dialog"""
        self.dialog = Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.geometry("400x300")
        self.dialog.configure(bg=ModernColors.BACKGROUND)
        
        # Zentrieren
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        x = (sw - 400) // 2
        y = (sh - 300) // 2
        self.dialog.geometry(f"400x300+{x}+{y}")
        
        self.dialog.attributes('-topmost', True)
        self.dialog.focus_force()
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        self.dialog.resizable(False, False)
        
        # Hauptcontainer
        main_frame = RoundedFrame(
            self.dialog, 
            bg_color=ModernColors.SURFACE,
            corner_radius=20,
            elevation=10
        )
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Icon und Titel
        title_frame = Frame(main_frame.inner_frame, bg=ModernColors.SURFACE)
        title_frame.pack(pady=(20, 10))
        
        # Security Icon (Unicode)
        icon_label = Label(
            title_frame, text="🔒", font=("Arial", 24),
            bg=ModernColors.SURFACE, fg=ModernColors.PRIMARY
        )
        icon_label.pack()
        
        title_label = Label(
            title_frame, text=self.title, font=("Arial", 16, "bold"),
            bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack(pady=(5, 0))
        
        # Beschreibung
        desc_label = Label(
            main_frame.inner_frame, text=self.reason, font=("Arial", 10),
            bg=ModernColors.SURFACE, fg=ModernColors.TEXT_SECONDARY,
            wraplength=300
        )
        desc_label.pack(pady=10)
        
        # PIN-Eingabe Container
        pin_frame = RoundedFrame(
            main_frame.inner_frame,
            bg_color=ModernColors.BACKGROUND,
            corner_radius=10,
            elevation=2
        )
        pin_frame.pack(pady=10, padx=40, fill=tk.X)
        
        self.pin_entry = Entry(
            pin_frame.inner_frame, show='●', font=("Arial", 14, "bold"),
            bg=ModernColors.BACKGROUND, fg=ModernColors.TEXT_PRIMARY,
            bd=0, justify='center'
        )
        self.pin_entry.pack(pady=15, padx=20, fill=tk.X)
        self.pin_entry.focus_set()
        
        # Buttons
        button_frame = Frame(main_frame.inner_frame, bg=ModernColors.SURFACE)
        button_frame.pack(pady=(20, 10))
        
        # OK Button
        ok_button = ModernButton(
            button_frame, text="✓ Bestätigen", command=self._ok,
            bg_color=ModernColors.SUCCESS, hover_color=ModernColors.SECONDARY_LIGHT,
            width=100, height=35
        )
        ok_button.pack(side=tk.LEFT, padx=10)
        
        # Cancel Button
        cancel_button = ModernButton(
            button_frame, text="✕ Abbrechen", command=self._cancel,
            bg_color=ModernColors.ERROR, hover_color="#EC7063",
            width=100, height=35
        )
        cancel_button.pack(side=tk.LEFT, padx=10)
        
        # Enter-Taste binden
        self.pin_entry.bind('<Return>', lambda e: self._ok())
        self.pin_entry.bind('<Escape>', lambda e: self._cancel())
        
        # Animation beim Öffnen
        self._animate_open()
        
        # Warte auf Schließung
        self.parent.wait_window(self.dialog)
        
        return self.result
    
    def _animate_open(self):
        """Öffnungsanimation"""
        self.dialog.attributes('-alpha', 0.0)
        self.dialog.update()
        
        for i in range(11):
            alpha = i / 10.0
            self.dialog.attributes('-alpha', alpha)
            self.dialog.update()
            time.sleep(0.02)
    
    def _ok(self):
        """OK-Button gedrückt"""
        self.result = self.pin_entry.get()
        self.pin_entry.delete(0, tk.END)
        self._animate_close()
    
    def _cancel(self):
        """Abbrechen-Button gedrückt"""
        self.result = None
        if hasattr(self, 'pin_entry'):
            self.pin_entry.delete(0, tk.END)
        self._animate_close()
    
    def _animate_close(self):
        """Schließungsanimation"""
        for i in range(10, -1, -1):
            alpha = i / 10.0
            self.dialog.attributes('-alpha', alpha)
            self.dialog.update()
            time.sleep(0.02)
        self.dialog.destroy()

class ModernStatusWidget:
    """Modernes Status-Widget mit animierten Indikatoren"""
    
    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.status_frame = None
        self.status_indicators = {}
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die Status-Widgets"""
        self.status_frame = RoundedFrame(
            self.parent,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        self.status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Titel
        title_label = Label(
            self.status_frame.inner_frame, 
            text="🛡️ System Status", 
            font=("Arial", 12, "bold"),
            bg=ModernColors.SURFACE, 
            fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack(pady=(10, 5))
        
        # Status-Container
        indicators_frame = Frame(self.status_frame.inner_frame, bg=ModernColors.SURFACE)
        indicators_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        # Kamera-Status
        self._create_status_indicator(
            indicators_frame, "camera", "📷 Kamera", False
        )
        
        # Maus-Status
        self._create_status_indicator(
            indicators_frame, "mouse", "🖱️ Maus-Erkennung", True
        )
        
        # Überwachung-Status
        self._create_status_indicator(
            indicators_frame, "monitoring", "👁️ Überwachung", False
        )
    
    def _create_status_indicator(self, parent, key, text, initial_status):
        """Erstellt einen Status-Indikator"""
        indicator_frame = Frame(parent, bg=ModernColors.SURFACE)
        indicator_frame.pack(fill=tk.X, pady=2)
        
        # Status-Punkt
        status_canvas = Canvas(
            indicator_frame, width=12, height=12, 
            highlightthickness=0, bg=ModernColors.SURFACE
        )
        status_canvas.pack(side=tk.LEFT, padx=(0, 10))
        
        # Text
        text_label = Label(
            indicator_frame, text=text, font=("Arial", 9),
            bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY
        )
        text_label.pack(side=tk.LEFT)
        
        self.status_indicators[key] = {
            'canvas': status_canvas,
            'label': text_label,
            'status': initial_status
        }
        
        self._update_indicator(key, initial_status)
    
    def _update_indicator(self, key, status):
        """Aktualisiert einen Status-Indikator"""
        if key not in self.status_indicators:
            return
        
        canvas = self.status_indicators[key]['canvas']
        canvas.delete("all")
        
        color = ModernColors.SUCCESS if status else ModernColors.ERROR
        
        # Äußerer Kreis (Glow-Effekt)
        canvas.create_oval(1, 1, 11, 11, fill="#E0E0E0", outline="")  # Light gray glow
        
        # Innerer Kreis
        canvas.create_oval(3, 3, 9, 9, fill=color, outline="")
        
        # Glanz-Effekt
        canvas.create_oval(4, 4, 7, 7, fill="#FFFFFF", outline="")  # White highlight
        
        self.status_indicators[key]['status'] = status
    
    def update_status(self, camera_available: bool = None, 
                     mouse_available: bool = None,
                     monitoring_active: bool = None):
        """Aktualisiert die Status-Anzeigen"""
        if camera_available is not None:
            self._update_indicator('camera', camera_available)
        if mouse_available is not None:
            self._update_indicator('mouse', mouse_available)
        if monitoring_active is not None:
            self._update_indicator('monitoring', monitoring_active)

class ModernControlWidget:
    """Modernes Kontroll-Widget mit Tabs und animierten Buttons"""
    
    def __init__(self, parent: tk.Widget, title: str):
        self.parent = parent
        self.title = title
        self.buttons = {}
        self.control_frame = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt das Kontroll-Widget"""
        self.control_frame = RoundedFrame(
            self.parent,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        self.control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Titel mit Icon
        title_label = Label(
            self.control_frame.inner_frame, 
            text=f"⚙️ {self.title}", 
            font=("Arial", 11, "bold"),
            bg=ModernColors.SURFACE, 
            fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack(pady=(10, 5))
        
        # Button-Container
        self.button_frame = Frame(self.control_frame.inner_frame, bg=ModernColors.SURFACE)
        self.button_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
    
    def add_button(self, key: str, text: str, command: Callable, 
                   bg_color=ModernColors.PRIMARY, icon=""):
        """Fügt einen Button hinzu"""
        button_text = f"{icon} {text}" if icon else text
        
        button = ModernButton(
            self.button_frame, 
            text=button_text, 
            command=command,
            bg_color=bg_color,
            width=200, 
            height=35
        )
        button.pack(pady=2, fill=tk.X)
        
        self.buttons[key] = button
    
    def configure_button(self, key: str, text: str = None, 
                        state: str = None, command: Callable = None):
        """Konfiguriert einen Button"""
        if key in self.buttons:
            self.buttons[key].configure_button(text=text, state=state, command=command)

class ModernUserListWidget:
    """Modernes Benutzer-Listen-Widget mit Karten-Design"""
    
    def __init__(self, parent: tk.Widget):
        self.parent = parent
        self.main_frame = None
        self.user_cards_frame = None
        self.users = []
        self.show_images_callback: Optional[Callable[[str], None]] = None
        self.delete_user_callback: Optional[Callable[[str], None]] = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt die Benutzer-Liste"""
        self.main_frame = RoundedFrame(
            self.parent,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Titel
        title_label = Label(
            self.main_frame.inner_frame, 
            text="👥 Registrierte Benutzer", 
            font=("Arial", 12, "bold"),
            bg=ModernColors.SURFACE, 
            fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack(pady=(15, 10))
        
        # Scrollable Frame für Benutzer-Karten
        self._create_scrollable_area()
    
    def _create_scrollable_area(self):
        """Erstellt scrollbaren Bereich für Benutzer-Karten"""
        # Canvas für Scrolling
        self.canvas = Canvas(
            self.main_frame.inner_frame, 
            bg=ModernColors.SURFACE,
            highlightthickness=0
        )
        
        scrollbar = ttk.Scrollbar(
            self.main_frame.inner_frame, 
            orient="vertical", 
            command=self.canvas.yview
        )
        
        self.user_cards_frame = Frame(self.canvas, bg=ModernColors.SURFACE)
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.create_window((0, 0), window=self.user_cards_frame, anchor="nw")
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 0), pady=(0, 20))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 20), pady=(0, 20))
        
        self.user_cards_frame.bind('<Configure>', self._on_cards_configure)
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        # Mouse wheel binding
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
    
    def _on_cards_configure(self, event):
        """Handle cards frame configure"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        """Handle canvas configure"""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas.create_window((0, 0), window=self.user_cards_frame, anchor="nw"), width=canvas_width)
    
    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def _create_user_card(self, username: str):
        """Erstellt eine Benutzer-Karte"""
        card_frame = RoundedFrame(
            self.user_cards_frame,
            bg_color=ModernColors.BACKGROUND,
            corner_radius=10,
            elevation=3
        )
        card_frame.pack(fill=tk.X, pady=5, padx=10)
        
        # Hauptinhalt der Karte
        content_frame = Frame(card_frame.inner_frame, bg=ModernColors.BACKGROUND)
        content_frame.pack(fill=tk.X, padx=15, pady=10)
        
        # Benutzer-Info
        info_frame = Frame(content_frame, bg=ModernColors.BACKGROUND)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Avatar-Placeholder
        avatar_label = Label(
            info_frame, text="👤", font=("Arial", 20),
            bg=ModernColors.BACKGROUND, fg=ModernColors.PRIMARY
        )
        avatar_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # Benutzer-Details
        details_frame = Frame(info_frame, bg=ModernColors.BACKGROUND)
        details_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        name_label = Label(
            details_frame, text=username, font=("Arial", 11, "bold"),
            bg=ModernColors.BACKGROUND, fg=ModernColors.TEXT_PRIMARY,
            anchor="w"
        )
        name_label.pack(fill=tk.X)
        
        status_label = Label(
            details_frame, text="✓ Aktiv", font=("Arial", 9),
            bg=ModernColors.BACKGROUND, fg=ModernColors.SUCCESS,
            anchor="w"
        )
        status_label.pack(fill=tk.X)
        
        # Aktions-Buttons
        actions_frame = Frame(content_frame, bg=ModernColors.BACKGROUND)
        actions_frame.pack(side=tk.RIGHT)
        
        # Bilder anzeigen Button
        show_button = ModernButton(
            actions_frame, text="👁️", command=lambda: self._show_images(username),
            bg_color=ModernColors.INFO, width=30, height=30,
            corner_radius=15
        )
        show_button.pack(side=tk.LEFT, padx=2)
        
        # Löschen Button
        delete_button = ModernButton(
            actions_frame, text="🗑️", command=lambda: self._delete_user(username),
            bg_color=ModernColors.ERROR, width=30, height=30,
            corner_radius=15
        )
        delete_button.pack(side=tk.LEFT, padx=2)
    
    def _show_images(self, username: str):
        """Zeigt Bilder eines Benutzers"""
        if self.show_images_callback:
            self.show_images_callback(username)
    
    def _delete_user(self, username: str):
        """Löscht einen Benutzer"""
        if self.delete_user_callback:
            self.delete_user_callback(username)
    
    def refresh(self, users: List[str]):
        """Aktualisiert die Benutzerliste"""
        # Alte Karten löschen
        for widget in self.user_cards_frame.winfo_children():
            widget.destroy()
        
        # Neue Karten erstellen
        self.users = users
        for user in users:
            self._create_user_card(user)
        
        # Falls keine Benutzer vorhanden
        if not users:
            no_users_label = Label(
                self.user_cards_frame, 
                text="Keine Benutzer registriert\n\n🔒 Fügen Sie den ersten Benutzer hinzu,\num TuxGuard zu verwenden",
                font=("Arial", 10), 
                bg=ModernColors.SURFACE,
                fg=ModernColors.TEXT_SECONDARY,
                justify=tk.CENTER
            )
            no_users_label.pack(pady=20)
    
    def set_callbacks(self, show_images: Callable[[str], None] = None,
                     delete_user: Callable[[str], None] = None):
        """Setzt die Callback-Funktionen"""
        if show_images:
            self.show_images_callback = show_images
        if delete_user:
            self.delete_user_callback = delete_user

class ModernLogWidget:
    """Modernes Log-Widget mit Syntax-Highlighting"""
    
    def __init__(self, parent: tk.Widget, title: str = "📋 System-Logs"):
        self.parent = parent
        self.title = title
        self.log_text = None
        self.main_frame = None
        self._create_widgets()
    
    def _create_widgets(self):
        """Erstellt das Log-Widget"""
        self.main_frame = RoundedFrame(
            self.parent,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Titel mit Clear-Button
        header_frame = Frame(self.main_frame.inner_frame, bg=ModernColors.SURFACE)
        header_frame.pack(fill=tk.X, padx=20, pady=(15, 5))
        
        title_label = Label(
            header_frame, text=self.title, font=("Arial", 11, "bold"),
            bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack(side=tk.LEFT)
        
        clear_button = ModernButton(
            header_frame, text="🧹 Löschen", command=self.clear_logs,
            bg_color=ModernColors.WARNING, width=80, height=25,
            corner_radius=12
        )
        clear_button.pack(side=tk.RIGHT)
        
        # Log-Text-Area
        text_frame = RoundedFrame(
            self.main_frame.inner_frame,
            bg_color=ModernColors.PRIMARY_DARK,
            corner_radius=10,
            elevation=2
        )
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 20))
        
        # Scrollable Text Widget
        self.log_text = Text(
            text_frame.inner_frame,
            wrap=tk.WORD,
            bg=ModernColors.PRIMARY_DARK,
            fg=ModernColors.TEXT_ON_PRIMARY,
            font=("Consolas", 9),
            bd=0,
            padx=10,
            pady=10,
            state=tk.DISABLED
        )
        
        scrollbar = ttk.Scrollbar(text_frame.inner_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Tags für Farb-Coding
        self._setup_text_tags()
    
    def _setup_text_tags(self):
        """Setup text tags for syntax highlighting"""
        self.log_text.tag_configure("INFO", foreground=ModernColors.INFO)
        self.log_text.tag_configure("WARNING", foreground=ModernColors.WARNING)
        self.log_text.tag_configure("ERROR", foreground=ModernColors.ERROR)
        self.log_text.tag_configure("SUCCESS", foreground=ModernColors.SUCCESS)
        self.log_text.tag_configure("TIMESTAMP", foreground=ModernColors.ACCENT_LIGHT)
    
    def add_log(self, message: str, level: str = "INFO"):
        """Fügt eine Log-Nachricht hinzu"""
        if not self.log_text:
            return
        
        self.log_text.configure(state=tk.NORMAL)
        
        # Timestamp
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "TIMESTAMP")
        
        # Level-Icon
        level_icons = {
            "INFO": "ℹ️",
            "WARNING": "⚠️", 
            "ERROR": "❌",
            "SUCCESS": "✅"
        }
        icon = level_icons.get(level, "ℹ️")
        self.log_text.insert(tk.END, f"{icon} ", level)
        
        # Message
        self.log_text.insert(tk.END, f"{message}\n", level)
        
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see(tk.END)
    
    def clear_logs(self):
        """Löscht alle Logs"""
        if self.log_text:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.configure(state=tk.DISABLED)
            self.add_log("Logs gelöscht", "INFO")

class ModernMainUI:
    """Moderne Haupt-UI mit Tabs und animierten Komponenten"""
    
    def __init__(self, parent: tk.Tk):
        self.parent = parent
        self.callbacks = {}
        self.control_widgets = {}
        self.status_widget = None
        self.user_list_widget = None
        self.mouse_log_widget = None
        
        self._setup_window()
        self._create_widgets()
    
    def _setup_window(self):
        """Setup des Hauptfensters"""
        self.parent.title(f"🛡️ {Config.APP_NAME} v{Config.APP_VERSION}")
        self.parent.geometry("900x700")
        self.parent.configure(bg=ModernColors.BACKGROUND)
        self.parent.minsize(800, 600)
        
        # Modernes Icon (falls verfügbar)
        try:
            # Hier könnte ein echtes Icon geladen werden
            pass
        except:
            pass
    
    def _create_widgets(self):
        """Erstellt die Haupt-UI"""
        # Hauptcontainer
        main_container = Frame(self.parent, bg=ModernColors.BACKGROUND)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header mit Logo und Status
        self._create_header(main_container)
        
        # Notebook für Tabs
        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Tab-Styles
        style = ttk.Style()
        style.configure('TNotebook.Tab', padding=[20, 10])
        
        # Tabs erstellen
        self._create_monitoring_tab()
        self._create_users_tab()
        self._create_logs_tab()
    
    def _create_header(self, parent):
        """Erstellt den Header-Bereich"""
        header_frame = Frame(
            parent,
            bg=ModernColors.PRIMARY,
            relief=tk.RAISED,
            bd=2
        )
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Logo und Titel
        title_frame = Frame(header_frame, bg=ModernColors.PRIMARY)
        title_frame.pack(side=tk.LEFT, padx=20, pady=15)
        
        logo_label = Label(
            title_frame, text="🛡️", font=("Arial", 24),
            bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY
        )
        logo_label.pack(side=tk.LEFT, padx=(0, 10))
        
        title_label = Label(
            title_frame, text=f"{Config.APP_NAME} v{Config.APP_VERSION}", 
            font=("Arial", 16, "bold"),
            bg=ModernColors.PRIMARY, fg=ModernColors.TEXT_ON_PRIMARY
        )
        title_label.pack(side=tk.LEFT)
        
        subtitle_label = Label(
            title_frame, text="Erweiterte Linux-Sicherheitsüberwachung", 
            font=("Arial", 10),
            bg=ModernColors.PRIMARY, fg=ModernColors.ACCENT_LIGHT
        )
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # Status Widget im Header (vereinfacht)
        status_frame = Frame(header_frame, bg=ModernColors.PRIMARY)
        status_frame.pack(side=tk.RIGHT, padx=20, pady=15)
        
        self.status_widget = self._create_simple_status_widget(status_frame)
    
    def _create_simple_status_widget(self, parent):
        """Erstellt vereinfachtes Status-Widget ohne verschachtelte RoundedFrames"""
        widget_frame = Frame(parent, bg=ModernColors.PRIMARY, relief=tk.RIDGE, bd=1)
        widget_frame.pack()
        
        # Container
        container = Frame(widget_frame, bg=ModernColors.SURFACE, padx=15, pady=10)
        container.pack()
        
        # Titel
        title_label = Label(
            container, 
            text="🛡️ System Status", 
            font=("Arial", 10, "bold"),
            bg=ModernColors.SURFACE, 
            fg=ModernColors.TEXT_PRIMARY
        )
        title_label.pack()
        
        # Status-Indikatoren speichern
        indicators = {}
        
        # Kamera-Status
        cam_frame = Frame(container, bg=ModernColors.SURFACE)
        cam_frame.pack(fill=tk.X, pady=2)
        
        cam_indicator = Label(cam_frame, text="●", font=("Arial", 10), 
                             bg=ModernColors.SURFACE, fg=ModernColors.ERROR)
        cam_indicator.pack(side=tk.LEFT, padx=(0, 5))
        
        Label(cam_frame, text="📷 Kamera", font=("Arial", 8),
             bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        indicators['camera'] = cam_indicator
        
        # Maus-Status
        mouse_frame = Frame(container, bg=ModernColors.SURFACE)
        mouse_frame.pack(fill=tk.X, pady=2)
        
        mouse_indicator = Label(mouse_frame, text="●", font=("Arial", 10),
                               bg=ModernColors.SURFACE, fg=ModernColors.SUCCESS)
        mouse_indicator.pack(side=tk.LEFT, padx=(0, 5))
        
        Label(mouse_frame, text="🖱️ Maus", font=("Arial", 8),
             bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        indicators['mouse'] = mouse_indicator
        
        # Überwachung-Status
        mon_frame = Frame(container, bg=ModernColors.SURFACE)
        mon_frame.pack(fill=tk.X, pady=2)
        
        mon_indicator = Label(mon_frame, text="●", font=("Arial", 10),
                             bg=ModernColors.SURFACE, fg=ModernColors.ERROR)
        mon_indicator.pack(side=tk.LEFT, padx=(0, 5))
        
        Label(mon_frame, text="👁️ Überwachung", font=("Arial", 8),
             bg=ModernColors.SURFACE, fg=ModernColors.TEXT_PRIMARY).pack(side=tk.LEFT)
        
        indicators['monitoring'] = mon_indicator
        
        # Erstelle ein einfaches Objekt zum Speichern der Indikatoren
        class SimpleStatusWidget:
            def __init__(self, indicators):
                self.indicators = indicators
            
            def update_status(self, camera_available=None, mouse_available=None, monitoring_active=None):
                if camera_available is not None:
                    color = ModernColors.SUCCESS if camera_available else ModernColors.ERROR
                    self.indicators['camera'].config(fg=color)
                if mouse_available is not None:
                    color = ModernColors.SUCCESS if mouse_available else ModernColors.ERROR
                    self.indicators['mouse'].config(fg=color)
                if monitoring_active is not None:
                    color = ModernColors.SUCCESS if monitoring_active else ModernColors.ERROR
                    self.indicators['monitoring'].config(fg=color)
        
        return SimpleStatusWidget(indicators)
    
    def _create_monitoring_tab(self):
        """Erstellt den Überwachungs-Tab"""
        monitoring_frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(monitoring_frame, text="🖥️ Überwachung")
        
        # Kamera-Kontrollen
        camera_widget = ModernControlWidget(monitoring_frame, "Kamera-Überwachung")
        camera_widget.add_button("test", "Kamera testen", 
                                lambda: self._call_callback('test_camera'),
                                ModernColors.INFO, "📷")
        camera_widget.add_button("diagnose", "Kamera-Diagnose", 
                                lambda: self._call_callback('diagnose_camera'),
                                ModernColors.WARNING, "🔍")
        self.control_widgets['camera'] = camera_widget
        
        # Muster-Erkennung
        pattern_widget = ModernControlWidget(monitoring_frame, "Muster-Erkennung")
        pattern_widget.add_button("train", "Mausbewegungen trainieren", 
                                 lambda: self._call_callback('train_pattern'),
                                 ModernColors.SECONDARY, "🎯")
        self.control_widgets['pattern'] = pattern_widget
        
        # Überwachung
        monitor_widget = ModernControlWidget(monitoring_frame, "System-Überwachung")
        monitor_widget.add_button("toggle", "Überwachung starten", 
                                 lambda: self._call_callback('toggle_monitoring'),
                                 ModernColors.SUCCESS, "▶️")
        self.control_widgets['monitor'] = monitor_widget
        
        # Log-Widget für Maus-Events
        self.mouse_log_widget = ModernLogWidget(monitoring_frame, "🖱️ Maus-Aktivitäten")
    
    def _create_users_tab(self):
        """Erstellt den Benutzer-Tab"""
        users_frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(users_frame, text="👥 Benutzer")
        
        # Neuer Benutzer Button
        add_user_frame = RoundedFrame(
            users_frame,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        add_user_frame.pack(fill=tk.X, padx=10, pady=10)
        
        add_user_button = ModernButton(
            add_user_frame.inner_frame,
            text="➕ Neuen Benutzer hinzufügen",
            command=lambda: self._call_callback('add_new_user'),
            bg_color=ModernColors.SUCCESS,
            width=250, height=40
        )
        add_user_button.pack(pady=20)
        
        # Benutzer-Liste
        self.user_list_widget = ModernUserListWidget(users_frame)
    
    def _create_logs_tab(self):
        """Erstellt den Log-Tab"""
        logs_frame = Frame(self.notebook, bg=ModernColors.BACKGROUND)
        self.notebook.add(logs_frame, text="📋 Logs")
        
        # System-Logs
        self.system_log_widget = ModernLogWidget(logs_frame, "📋 System-Protokolle")
    
    def set_callback(self, name: str, callback: Callable):
        """Setzt einen Callback"""
        self.callbacks[name] = callback
        
        # Spezielle Callbacks für User-Widget
        if name == 'show_user_images' and self.user_list_widget:
            self.user_list_widget.show_images_callback = callback
        elif name == 'delete_user' and self.user_list_widget:
            self.user_list_widget.delete_user_callback = callback
    
    def _call_callback(self, name: str, *args, **kwargs):
        """Ruft einen Callback auf"""
        callback = self.callbacks.get(name)
        if callback:
            try:
                return callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Fehler beim Ausführen von Callback '{name}': {e}")
                messagebox.showerror("Fehler", f"Fehler: {e}")
        else:
            logger.warning(f"Callback '{name}' nicht gefunden")
    
    def update_monitoring_button(self, is_active: bool):
        """Aktualisiert den Überwachungsbutton"""
        text = "⏹️ Überwachung stoppen" if is_active else "▶️ Überwachung starten"
        color = ModernColors.ERROR if is_active else ModernColors.SUCCESS
        
        monitor_widget = self.control_widgets.get('monitor')
        if monitor_widget and 'toggle' in monitor_widget.buttons:
            monitor_widget.buttons['toggle'].configure_button(text=text)
            monitor_widget.buttons['toggle'].bg_color = color
            monitor_widget.buttons['toggle']._draw_button()
    
    def update_status(self, camera_available: bool = None, 
                     mouse_available: bool = None,
                     monitoring_active: bool = None):
        """Aktualisiert den Status"""
        if self.status_widget:
            self.status_widget.update_status(camera_available, mouse_available, monitoring_active)
    
    def refresh_user_list(self, users: List[str]):
        """Aktualisiert die Benutzerliste"""
        if self.user_list_widget:
            self.user_list_widget.refresh(users)
    
    def add_mouse_log(self, message: str, level: str = "INFO"):
        """Fügt einen Maus-Log hinzu"""
        if self.mouse_log_widget:
            self.mouse_log_widget.add_log(message, level)
    
    def add_system_log(self, message: str, level: str = "INFO"):
        """Fügt einen System-Log hinzu"""
        if hasattr(self, 'system_log_widget') and self.system_log_widget:
            self.system_log_widget.add_log(message, level)
    
    def configure_camera_buttons(self, enabled: bool):
        """Aktiviert/Deaktiviert Kamera-Buttons"""
        state = "normal" if enabled else "disabled"
        camera_widget = self.control_widgets.get('camera')
        if camera_widget:
            for button_key in ['test', 'diagnose']:
                if button_key in camera_widget.buttons:
                    camera_widget.buttons[button_key].configure_button(state=state)

# Export der wichtigsten Klassen für Kompatibilität
PinDialog = ModernPinDialog
UserListWidget = ModernUserListWidget
LogWidget = ModernLogWidget
StatusWidget = ModernStatusWidget
MainUI = ModernMainUI
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Modern UI Demo
Demonstriert die neue moderne Benutzeroberfläche
"""

import tkinter as tk
from modern_ui import (
    ModernMainUI, ModernPinDialog, ModernButton, 
    RoundedFrame, ModernColors, ModernStatusWidget,
    ModernUserListWidget, ModernLogWidget
)
import time
import threading

class ModernUIDemo:
    """Demo der modernen TuxGuard UI"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🛡️ TuxGuard Modern UI Demo")
        self.root.geometry("1000x750")
        self.root.configure(bg=ModernColors.BACKGROUND)
        
        self.setup_demo()
    
    def setup_demo(self):
        """Setup der Demo"""
        # Hauptcontainer
        main_frame = tk.Frame(self.root, bg=ModernColors.BACKGROUND)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Titel
        title_frame = RoundedFrame(
            main_frame,
            bg_color=ModernColors.PRIMARY,
            corner_radius=15,
            elevation=8
        )
        title_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = tk.Label(
            title_frame.inner_frame,
            text="🛡️ TuxGuard Modern UI Demo",
            font=("Arial", 18, "bold"),
            bg=ModernColors.PRIMARY,
            fg=ModernColors.TEXT_ON_PRIMARY
        )
        title_label.pack(pady=20)
        
        # Demo-Bereiche
        demo_frame = tk.Frame(main_frame, bg=ModernColors.BACKGROUND)
        demo_frame.pack(fill=tk.BOTH, expand=True)
        
        # Linke Spalte - Buttons und Status
        left_column = tk.Frame(demo_frame, bg=ModernColors.BACKGROUND)
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Rechte Spalte - Logs
        right_column = tk.Frame(demo_frame, bg=ModernColors.BACKGROUND)
        right_column.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        self.setup_left_column(left_column)
        self.setup_right_column(right_column)
    
    def setup_left_column(self, parent):
        """Setup der linken Spalte"""
        # Status Widget
        self.status_widget = ModernStatusWidget(parent)
        
        # Button-Demo
        button_frame = RoundedFrame(
            parent,
            bg_color=ModernColors.SURFACE,
            corner_radius=15,
            elevation=5
        )
        button_frame.pack(fill=tk.X, pady=10)
        
        button_title = tk.Label(
            button_frame.inner_frame,
            text="🎛️ Modern Button Demo",
            font=("Arial", 12, "bold"),
            bg=ModernColors.SURFACE,
            fg=ModernColors.TEXT_PRIMARY
        )
        button_title.pack(pady=(15, 10))
        
        # Verschiedene Button-Styles
        button_container = tk.Frame(button_frame.inner_frame, bg=ModernColors.SURFACE)
        button_container.pack(pady=(0, 20), padx=20, fill=tk.X)
        
        # Primärer Button
        primary_btn = ModernButton(
            button_container, text="🔒 PIN Dialog", 
            command=self.show_pin_dialog,
            bg_color=ModernColors.PRIMARY,
            width=180, height=35
        )
        primary_btn.pack(pady=5, fill=tk.X)
        
        # Erfolg Button
        success_btn = ModernButton(
            button_container, text="✅ Status Update", 
            command=self.update_status,
            bg_color=ModernColors.SUCCESS,
            width=180, height=35
        )
        success_btn.pack(pady=5, fill=tk.X)
        
        # Info Button
        info_btn = ModernButton(
            button_container, text="ℹ️ System Info", 
            command=self.show_system_info,
            bg_color=ModernColors.INFO,
            width=180, height=35
        )
        info_btn.pack(pady=5, fill=tk.X)
        
        # Warning Button
        warning_btn = ModernButton(
            button_container, text="⚠️ Test Warning", 
            command=self.show_warning,
            bg_color=ModernColors.WARNING,
            width=180, height=35
        )
        warning_btn.pack(pady=5, fill=tk.X)
        
        # User List Demo
        self.user_list = ModernUserListWidget(parent)
        self.user_list.set_callbacks(
            show_images=self.show_user_images,
            delete_user=self.delete_user_demo
        )
        
        # Demo-Benutzer hinzufügen
        demo_users = ["admin", "user1", "guest", "developer"]
        self.user_list.refresh(demo_users)
    
    def setup_right_column(self, parent):
        """Setup der rechten Spalte"""
        # Log Widget
        self.log_widget = ModernLogWidget(parent, "📋 Demo Logs")
        
        # Automatische Log-Generierung
        self.start_auto_logging()
    
    def show_pin_dialog(self):
        """Zeigt PIN Dialog"""
        pin_dialog = ModernPinDialog(
            self.root, 
            title="🔐 Sicherheitsprüfung",
            reason="Demo: Geben Sie eine PIN ein\n(beliebige Eingabe möglich)"
        )
        pin = pin_dialog.show()
        
        if pin:
            self.log_widget.add_log(f"PIN eingegeben: {'*' * len(pin)}", "SUCCESS")
        else:
            self.log_widget.add_log("PIN-Eingabe abgebrochen", "WARNING")
    
    def update_status(self):
        """Aktualisiert Status"""
        import random
        camera = random.choice([True, False])
        monitoring = random.choice([True, False])
        
        self.status_widget.update_status(
            camera_available=camera,
            monitoring_active=monitoring
        )
        
        self.log_widget.add_log(
            f"Status aktualisiert - Kamera: {'✓' if camera else '✗'}, "
            f"Überwachung: {'✓' if monitoring else '✗'}",
            "INFO"
        )
    
    def show_system_info(self):
        """Zeigt System-Info"""
        import platform
        import psutil
        
        info = f"System: {platform.system()} {platform.release()}"
        self.log_widget.add_log(info, "INFO")
        
        try:
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            self.log_widget.add_log(
                f"CPU: {cpu_percent}%, RAM: {memory.percent}%", 
                "INFO"
            )
        except:
            self.log_widget.add_log("Systemdaten nicht verfügbar", "WARNING")
    
    def show_warning(self):
        """Zeigt Warning"""
        self.log_widget.add_log(
            "⚠️ Dies ist eine Demo-Warnung!", 
            "WARNING"
        )
    
    def show_user_images(self, username):
        """Demo: Benutzer-Bilder anzeigen"""
        self.log_widget.add_log(
            f"👁️ Bilder für Benutzer '{username}' anzeigen", 
            "INFO"
        )
    
    def delete_user_demo(self, username):
        """Demo: Benutzer löschen"""
        self.log_widget.add_log(
            f"🗑️ Demo: Benutzer '{username}' löschen", 
            "WARNING"
        )
    
    def start_auto_logging(self):
        """Startet automatische Log-Generierung"""
        def auto_log():
            messages = [
                ("Kamera-Überwachung gestartet", "SUCCESS"),
                ("Neue Bewegung erkannt", "INFO"),
                ("Gesicht nicht erkannt", "WARNING"),
                ("System-Check erfolgreich", "SUCCESS"),
                ("Maus-Muster analysiert", "INFO"),
                ("Unauthorized access detected", "ERROR"),
                ("Backup erstellt", "SUCCESS"),
                ("Update verfügbar", "INFO")
            ]
            
            import random
            while True:
                time.sleep(random.randint(3, 8))
                message, level = random.choice(messages)
                try:
                    self.root.after(0, lambda m=message, l=level: 
                                  self.log_widget.add_log(m, l))
                except:
                    break
        
        log_thread = threading.Thread(target=auto_log, daemon=True)
        log_thread.start()
        
        # Erste Logs
        self.log_widget.add_log("🛡️ TuxGuard Modern UI Demo gestartet", "SUCCESS")
        self.log_widget.add_log("Alle Komponenten geladen", "INFO")
    
    def run(self):
        """Startet die Demo"""
        self.root.mainloop()

if __name__ == "__main__":
    print("🛡️ Starte TuxGuard Modern UI Demo...")
    demo = ModernUIDemo()
    demo.run()
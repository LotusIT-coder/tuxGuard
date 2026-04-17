#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Headless Test
Testet TuxGuard-Komponenten ohne GUI
"""

import sys
import os
from pathlib import Path

def test_imports():
    """Testet alle wichtigen Imports"""
    print("🔍 Teste Imports...")
    
    try:
        from config import Config
        print(f"✅ Config: {Config.APP_NAME} v{Config.APP_VERSION}")
    except Exception as e:
        print(f"❌ Config-Import fehlgeschlagen: {e}")
        return False
    
    try:
        from logging_setup import setup_logging
        logger = setup_logging()
        logger.info("Logging-Test erfolgreich")
        print("✅ Logging-System funktioniert")
    except Exception as e:
        print(f"❌ Logging-Import fehlgeschlagen: {e}")
        return False
    
    try:
        from database import DatabaseManager
        print("✅ DatabaseManager importiert")
    except Exception as e:
        print(f"❌ Database-Import fehlgeschlagen: {e}")
        return False
    
    try:
        from camera import CameraManager
        print("✅ CameraManager importiert")
    except Exception as e:
        print(f"❌ Camera-Import fehlgeschlagen: {e}")
        return False
    
    try:
        from modern_ui import ModernColors, ModernButton
        print("✅ Modern UI importiert")
    except Exception as e:
        print(f"❌ Modern UI-Import fehlgeschlagen: {e}")
        return False
    
    return True

def test_database():
    """Testet Datenbankfunktionalität"""
    print("\n🔍 Teste Datenbank...")
    
    try:
        from database import DatabaseManager
        
        with DatabaseManager() as db:
            users = db.get_all_users()
            print(f"✅ Datenbank-Verbindung erfolgreich - {len(users)} Benutzer gefunden")
            
            # Test einer einfachen Abfrage
            if users:
                user = users[0]
                # Verwende korrekte Methode
                face_data = db.get_user_face_encodings(user)
                print(f"✅ Face-Encodings für '{user}' geladen: {len(face_data)} Einträge")
            else:
                print("ℹ️  Keine Benutzer in der Datenbank - das ist normal für eine neue Installation")
            
        return True
        
    except Exception as e:
        print(f"❌ Datenbank-Test fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_camera_manager():
    """Testet CameraManager (ohne echte Kamera)"""
    print("\n🔍 Teste CameraManager...")
    
    try:
        import tkinter as tk
        from camera import CameraManager
        from database import DatabaseManager
        
        # Dummy-Window für Test
        root = tk.Tk()
        root.withdraw()
        
        db = DatabaseManager()
        camera_mgr = CameraManager(root, db)
        
        print("✅ CameraManager erfolgreich initialisiert")
        
        # Diagnoseinformationen
        diag_info = camera_mgr.diagnose()
        print(f"ℹ️  Kamera-Diagnose: {diag_info[:100]}...")
        
        root.destroy()
        return True
        
    except Exception as e:
        print(f"❌ CameraManager-Test fehlgeschlagen: {e}")
        return False

def test_mouse_monitor():
    """Testet Mouse-Monitor"""
    print("\n🔍 Teste Mouse-Monitor...")
    
    try:
        from mouse_monitor import load_pattern_model
        
        model_path = Path("models/mouse_pattern_model.keras")
        if model_path.exists():
            model = load_pattern_model()
            if model:
                print("✅ Mouse-Pattern-Model erfolgreich geladen")
            else:
                print("⚠️  Mouse-Pattern-Model nicht gefunden")
        else:
            print("ℹ️  Mouse-Pattern-Model-Datei nicht vorhanden")
        
        return True
        
    except Exception as e:
        print(f"❌ Mouse-Monitor-Test fehlgeschlagen: {e}")
        return False

def test_configuration():
    """Testet Konfiguration"""
    print("\n🔍 Teste Konfiguration...")
    
    try:
        from config import Config
        
        print(f"📋 App-Name: {Config.APP_NAME}")
        print(f"📋 Version: {Config.APP_VERSION}")
        print(f"📋 Datenbank: {Config.get_database_path()}")
        print(f"📋 Kamera-Gerät: {Config.CAMERA_DEVICE}")
        print(f"📋 Models-Dir: {Config.MODELS_DIR}")
        
        print("✅ Konfiguration erfolgreich geladen")
        return True
        
    except Exception as e:
        print(f"❌ Konfigurations-Test fehlgeschlagen: {e}")
        return False

def check_files():
    """Prüft wichtige Dateien"""
    print("\n🔍 Prüfe wichtige Dateien...")
    
    important_files = [
        "config.py",
        "database.py", 
        "camera.py",
        "modern_ui.py",
        "logging_setup.py",
        "mouse_monitor.py",
        "tuxguard_refactored.py"
    ]
    
    missing_files = []
    for file in important_files:
        if Path(file).exists():
            print(f"✅ {file}")
        else:
            print(f"❌ {file} - FEHLT")
            missing_files.append(file)
    
    if missing_files:
        print(f"\n⚠️  Fehlende Dateien: {', '.join(missing_files)}")
        return False
    
    print("✅ Alle wichtigen Dateien vorhanden")
    return True

def check_display():
    """Prüft Display-Verfügbarkeit"""
    print("\n🔍 Prüfe Display-Umgebung...")
    
    display = os.environ.get('DISPLAY')
    if display:
        print(f"✅ DISPLAY verfügbar: {display}")
        
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            print("✅ Tkinter GUI funktioniert")
            return True
        except Exception as e:
            print(f"❌ GUI-Test fehlgeschlagen: {e}")
            return False
    else:
        print("❌ Kein DISPLAY erkannt - Headless-Umgebung")
        print("💡 Für GUI-Betrieb erforderlich:")
        print("   • Lokale Desktop-Umgebung")
        print("   • SSH mit X11-Forwarding: ssh -X")
        print("   • VNC/Remote Desktop")
        return False

def main():
    """Haupttest-Funktion"""
    print("🛡️  TuxGuard Headless Test")
    print("=" * 50)
    
    all_tests_passed = True
    
    # Test 1: Dateien prüfen
    if not check_files():
        all_tests_passed = False
    
    # Test 2: Imports prüfen  
    if not test_imports():
        all_tests_passed = False
    
    # Test 3: Konfiguration prüfen
    if not test_configuration():
        all_tests_passed = False
    
    # Test 4: Datenbank prüfen
    if not test_database():
        all_tests_passed = False
    
    # Test 5: Mouse-Monitor prüfen
    if not test_mouse_monitor():
        all_tests_passed = False
    
    # Test 6: Display prüfen
    gui_available = check_display()
    
    # Test 7: CameraManager (nur wenn GUI verfügbar)
    if gui_available:
        if not test_camera_manager():
            all_tests_passed = False
    else:
        print("\n⚠️  CameraManager-Test übersprungen (kein Display)")
    
    # Ergebnis
    print("\n" + "=" * 50)
    if all_tests_passed:
        print("✅ ALLE TESTS BESTANDEN!")
        if gui_available:
            print("🚀 TuxGuard ist bereit für den GUI-Betrieb!")
            print("   Starten mit: python3 tuxguard_refactored.py")
        else:
            print("⚠️  GUI nicht verfügbar - nur Backend-Komponenten funktional")
    else:
        print("❌ EINIGE TESTS FEHLGESCHLAGEN!")
        print("🔧 Beheben Sie die Probleme vor dem Produktiveinsatz")
    
    print("\n📋 Test-Protokoll:")
    print(f"   • Komponenten-Tests: {'✅' if all_tests_passed else '❌'}")
    print(f"   • GUI-Verfügbarkeit: {'✅' if gui_available else '❌'}")
    print(f"   • Bereit für Betrieb: {'✅' if (all_tests_passed and gui_available) else '❌'}")

if __name__ == "__main__":
    main()
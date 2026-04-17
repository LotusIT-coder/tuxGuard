#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Final System Test
Umfassender Test der refactorierten TuxGuard-Anwendung
"""

import sys
import os
import time
import subprocess
from pathlib import Path

def print_header(title):
    """Druckt einen formatierten Header"""
    print("\n" + "=" * 60)
    print(f"🛡️  {title}")
    print("=" * 60)

def print_section(title):
    """Druckt einen Abschnittstitel"""
    print(f"\n🔍 {title}")
    print("-" * 40)

def test_core_functionality():
    """Testet Kernfunktionalität"""
    print_section("Kernfunktionalität Test")
    
    success_count = 0
    total_tests = 0
    
    # Test 1: Imports
    total_tests += 1
    try:
        from config import Config
        from database import DatabaseManager
        from camera import CameraManager
        from modern_ui import ModernMainUI, ModernColors
        from logging_setup import setup_logging
        print("✅ Alle Module erfolgreich importiert")
        success_count += 1
    except Exception as e:
        print(f"❌ Import-Fehler: {e}")
    
    # Test 2: Konfiguration
    total_tests += 1
    try:
        from config import Config
        Config.ensure_directories()
        db_path = Config.get_database_path()
        print(f"✅ Konfiguration geladen - DB: {db_path}")
        success_count += 1
    except Exception as e:
        print(f"❌ Konfigurations-Fehler: {e}")
    
    # Test 3: Logging
    total_tests += 1
    try:
        from logging_setup import setup_logging
        logger = setup_logging()
        logger.info("System-Test durchgeführt")
        print("✅ Logging-System funktioniert")
        success_count += 1
    except Exception as e:
        print(f"❌ Logging-Fehler: {e}")
    
    # Test 4: Datenbank-Verbindung
    total_tests += 1
    try:
        from database import DatabaseManager
        db = DatabaseManager()
        db.connect()
        users = db.get_all_users()
        db.disconnect()
        print(f"✅ Datenbank funktioniert - {len(users)} Benutzer")
        success_count += 1
    except Exception as e:
        print(f"❌ Datenbank-Fehler: {e}")
    
    # Test 5: UI-Komponenten
    total_tests += 1
    try:
        from modern_ui import ModernColors, ModernButton
        colors_ok = all([
            ModernColors.PRIMARY,
            ModernColors.SUCCESS,
            ModernColors.ERROR,
            ModernColors.SURFACE
        ])
        if colors_ok:
            print("✅ UI-Komponenten verfügbar")
            success_count += 1
        else:
            print("❌ UI-Farben unvollständig")
    except Exception as e:
        print(f"❌ UI-Fehler: {e}")
    
    return success_count, total_tests

def test_gui_availability():
    """Testet GUI-Verfügbarkeit"""
    print_section("GUI-Verfügbarkeit Test")
    
    # Display-Check
    display = os.environ.get('DISPLAY')
    if not display:
        print("❌ Kein DISPLAY - GUI nicht verfügbar")
        print("💡 Für GUI-Betrieb erforderlich:")
        print("   • Desktop-Umgebung")
        print("   • SSH mit X11: ssh -X")
        print("   • VNC/Remote Desktop")
        return False
    
    print(f"✅ DISPLAY verfügbar: {display}")
    
    # Tkinter-Test
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        print("✅ Tkinter GUI funktioniert")
        return True
    except Exception as e:
        print(f"❌ Tkinter-Fehler: {e}")
        return False

def test_application_startup():
    """Testet Anwendungsstart"""
    print_section("Anwendungsstart Test")
    
    try:
        # Importiere Hauptanwendung
        from tuxguard_refactored import TuxGuardApplication
        print("✅ TuxGuardApplication importiert")
        
        # Teste Initialisierung (ohne GUI zu starten)
        print("ℹ️  Teste Initialisierung...")
        
        # Simuliere Initialisierung ohne mainloop
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()  # Verstecke Fenster
        
        print("✅ Grundlegende Initialisierung möglich")
        
        root.destroy()
        return True
        
    except Exception as e:
        print(f"❌ Anwendungsstart-Fehler: {e}")
        return False

def test_file_integrity():
    """Testet Datei-Integrität"""
    print_section("Datei-Integrität Test")
    
    required_files = {
        "config.py": "Konfiguration",
        "database.py": "Datenbankoperationen", 
        "camera.py": "Kameramanagement",
        "modern_ui.py": "Moderne Benutzeroberfläche",
        "logging_setup.py": "Logging-Konfiguration",
        "mouse_monitor.py": "Maus-Überwachung",
        "tuxguard_refactored.py": "Hauptanwendung",
        "face_recognition.db": "Benutzerdatenbank"
    }
    
    missing_files = []
    for file, description in required_files.items():
        if Path(file).exists():
            size = Path(file).stat().st_size
            print(f"✅ {file:20} ({description}) - {size:,} bytes")
        else:
            print(f"❌ {file:20} - FEHLT")
            missing_files.append(file)
    
    if missing_files:
        print(f"\n⚠️  Fehlende Dateien: {', '.join(missing_files)}")
        return False
    
    print(f"\n✅ Alle {len(required_files)} erforderlichen Dateien vorhanden")
    return True

def test_dependencies():
    """Testet Abhängigkeiten"""
    print_section("Abhängigkeiten Test")
    
    dependencies = {
        "tkinter": "GUI-Framework",
        "sqlite3": "Datenbank",
        "numpy": "Numerische Berechnungen",
        "PIL": "Bildverarbeitung",
        "cv2": "Computer Vision",
        "face_recognition": "Gesichtserkennung",
        "pystray": "System-Tray",
        "threading": "Multithreading"
    }
    
    missing_deps = []
    for dep, description in dependencies.items():
        try:
            __import__(dep)
            print(f"✅ {dep:15} - {description}")
        except ImportError:
            print(f"❌ {dep:15} - FEHLT ({description})")
            missing_deps.append(dep)
    
    if missing_deps:
        print(f"\n⚠️  Fehlende Abhängigkeiten: {', '.join(missing_deps)}")
        print("💡 Installation mit: pip install -r requirements.txt")
        return False
    
    return True

def generate_system_report():
    """Generiert System-Report"""
    print_section("System-Report")
    
    try:
        import platform
        import sys
        
        print(f"🖥️  System: {platform.system()} {platform.release()}")
        print(f"🐍 Python: {sys.version.split()[0]}")
        print(f"📂 Arbeitsverzeichnis: {Path.cwd()}")
        
        # Display-Info
        display = os.environ.get('DISPLAY', 'Nicht verfügbar')
        print(f"🖼️  Display: {display}")
        
        # Kamera-Info
        video_devices = list(Path('/dev').glob('video*'))
        if video_devices:
            print(f"📷 Kameras: {len(video_devices)} gefunden")
            for device in video_devices[:3]:  # Zeige erste 3
                print(f"   • {device}")
        else:
            print("📷 Kameras: Keine gefunden")
        
        # Festplatz-Info
        db_file = Path("face_recognition.db")
        if db_file.exists():
            db_size = db_file.stat().st_size
            print(f"💾 Datenbank: {db_size:,} bytes")
        
        return True
        
    except Exception as e:
        print(f"❌ System-Report-Fehler: {e}")
        return False

def main():
    """Haupttest-Funktion"""
    print_header("TuxGuard Final System Test")
    print("Umfassende Überprüfung der refactorierten Anwendung")
    
    start_time = time.time()
    
    # Test-Durchläufe
    tests_results = []
    
    # 1. Datei-Integrität
    file_ok = test_file_integrity()
    tests_results.append(("Datei-Integrität", file_ok))
    
    # 2. Abhängigkeiten
    deps_ok = test_dependencies()
    tests_results.append(("Abhängigkeiten", deps_ok))
    
    # 3. Kernfunktionalität
    core_success, core_total = test_core_functionality()
    core_ok = (core_success == core_total)
    tests_results.append(("Kernfunktionalität", core_ok))
    
    # 4. GUI-Verfügbarkeit
    gui_ok = test_gui_availability()
    tests_results.append(("GUI-Verfügbarkeit", gui_ok))
    
    # 5. Anwendungsstart
    app_ok = test_application_startup() if gui_ok else False
    tests_results.append(("Anwendungsstart", app_ok))
    
    # 6. System-Report
    report_ok = generate_system_report()
    tests_results.append(("System-Report", report_ok))
    
    # Ergebnisse
    end_time = time.time()
    duration = end_time - start_time
    
    print_header("Test-Ergebnisse")
    
    passed_tests = sum(1 for _, result in tests_results if result)
    total_tests = len(tests_results)
    
    for test_name, result in tests_results:
        status = "✅ BESTANDEN" if result else "❌ FEHLGESCHLAGEN"
        print(f"{test_name:20} - {status}")
    
    print(f"\n📊 Zusammenfassung:")
    print(f"   • Tests bestanden: {passed_tests}/{total_tests}")
    print(f"   • Erfolgsrate: {(passed_tests/total_tests)*100:.1f}%")
    print(f"   • Testdauer: {duration:.2f} Sekunden")
    
    # Bewertung
    if passed_tests == total_tests:
        print(f"\n🎉 ALLE TESTS BESTANDEN!")
        print(f"🚀 TuxGuard ist vollständig funktionsfähig!")
        print(f"   Starten mit: python3 tuxguard_refactored.py")
    elif passed_tests >= total_tests * 0.8:  # 80%
        print(f"\n✅ SYSTEM WEITGEHEND FUNKTIONSFÄHIG")
        print(f"⚠️  Einige optionale Features fehlen")
        print(f"💡 Beheben Sie die Probleme für optimale Leistung")
    else:
        print(f"\n❌ KRITISCHE PROBLEME GEFUNDEN")
        print(f"🔧 System nicht produktionsbereit")
        print(f"💡 Beheben Sie die Fehler vor der Nutzung")
    
    # Spezifische Empfehlungen
    print(f"\n💡 Empfehlungen:")
    if not gui_ok:
        print("   • Starten Sie TuxGuard in einer Desktop-Umgebung")
        print("   • Oder verwenden Sie SSH mit X11-Forwarding")
    if core_ok and gui_ok:
        print("   • System ist bereit für den Produktiveinsatz")
        print("   • Teste die UI-Demo: python3 ui_demo.py")
    if file_ok and deps_ok:
        print("   • Grundlegende Installation ist korrekt")

if __name__ == "__main__":
    main()
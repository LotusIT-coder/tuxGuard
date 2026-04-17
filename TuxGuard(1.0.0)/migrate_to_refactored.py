#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Migration Script
Hilfsskript für den Wechsel zur refactorierten Version
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

def check_requirements():
    """Prüft ob alle erforderlichen Module verfügbar sind"""
    required_modules = [
        'config', 'database', 'camera', 'ui', 
        'logging_setup', 'mouse_monitor', 'tuxguard_refactored'
    ]
    
    missing = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"✅ {module}.py - verfügbar")
        except ImportError:
            print(f"❌ {module}.py - FEHLT")
            missing.append(module)
    
    return len(missing) == 0

def backup_original():
    """Erstellt Backup der Original-Datei"""
    original = Path("tuxguardtest.py")
    backup = Path("tuxguardtest_backup.py")
    
    if original.exists() and not backup.exists():
        shutil.copy2(original, backup)
        print(f"✅ Backup erstellt: {backup}")
        return True
    elif backup.exists():
        print(f"ℹ️  Backup bereits vorhanden: {backup}")
        return True
    else:
        print("❌ Original-Datei nicht gefunden")
        return False

def test_refactored_version():
    """Testet die refactorierte Version"""
    try:
        # Import test
        from tuxguard_refactored import TuxGuardApplication
        print("✅ Import der refactorierten Version erfolgreich")
        
        # Basic functionality test
        app = TuxGuardApplication()
        print("✅ Initialisierung erfolgreich")
        
        # Clean up
        if hasattr(app, 'root'):
            app.root.quit()
        
        return True
    except Exception as e:
        print(f"❌ Test fehlgeschlagen: {e}")
        return False

def main():
    """Haupt-Migrationsprozess"""
    print("=" * 50)
    print("TuxGuard Migration zur refactorierten Version")
    print("=" * 50)
    
    # 1. Check requirements
    print("\n1. Überprüfung der Module...")
    if not check_requirements():
        print("\n❌ Migration abgebrochen - fehlende Module")
        return False
    
    # 2. Backup original
    print("\n2. Backup der Original-Version...")
    if not backup_original():
        print("\n❌ Migration abgebrochen - Backup fehlgeschlagen")
        return False
    
    # 3. Test refactored version
    print("\n3. Test der refactorierten Version...")
    if not test_refactored_version():
        print("\n❌ Migration abgebrochen - Test fehlgeschlagen")
        return False
    
    # 4. Migration instructions
    print("\n" + "=" * 50)
    print("✅ MIGRATION ERFOLGREICH!")
    print("=" * 50)
    print("\nNächste Schritte:")
    print("1. Verwende 'python3 tuxguard_refactored.py' für den Start")
    print("2. Die Original-Version liegt als Backup in 'tuxguardtest_backup.py'")
    print("3. Alle Daten und Einstellungen bleiben unverändert")
    print("4. Bei Problemen: Wechsel zurück zur Original-Version möglich")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
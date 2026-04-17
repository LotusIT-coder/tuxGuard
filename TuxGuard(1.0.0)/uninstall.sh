#!/bin/bash

# Prüfe ob Script mit sudo-Rechten ausgeführt wird
if [ "$EUID" -ne 0 ]; then 
    echo "Bitte führen Sie das Skript mit sudo aus"
    exit 1
fi

echo "Starte Deinstallation von TuxGuard..."

# Entferne Desktop-Datei
echo "Entferne Desktop-Starter..."
rm -f /usr/share/applications/tuxguard.desktop

# Entferne Programmdateien
echo "Entferne Programmdateien..."
rm -rf /opt/tuxguard

# Optional: Entferne Python-Pakete
# Hinweis: Diese Pakete könnten von anderen Programmen verwendet werden
read -p "Möchten Sie auch die installierten Python-Pakete entfernen? (j/N) " response
if [[ "$response" =~ ^[Jj]$ ]]; then
    echo "Entferne Python-Pakete..."
    pip3 uninstall -y opencv-python face_recognition numpy pillow pystray psutil
fi

# Optional: Entferne System-Pakete
read -p "Möchten Sie auch die installierten Systempakete entfernen (python3-pip python3-tk i3lock)? (j/N) " response
if [[ "$response" =~ ^[Jj]$ ]]; then
    echo "Entferne Systempakete..."
    apt-get remove -y python3-pip python3-tk i3lock
    apt-get autoremove -y
fi

# Entferne lokale Daten, falls vorhanden
read -p "Möchten Sie auch die lokalen Daten und Einstellungen entfernen? (j/N) " response
if [[ "$response" =~ ^[Jj]$ ]]; then
    echo "Entferne lokale Daten..."
    # Entferne .desktop Datei im Autostart-Verzeichnis für jeden Benutzer
    for userdir in /home/*; do
        if [ -d "$userdir" ]; then
            username=$(basename "$userdir")
            rm -f "$userdir/.config/autostart/tuxguard.desktop"
            echo "Autostart-Konfiguration für Benutzer $username entfernt"
        fi
    done
fi

echo "Deinstallation abgeschlossen!"

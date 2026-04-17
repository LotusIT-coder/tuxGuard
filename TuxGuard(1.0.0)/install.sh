#!/bin/bash

# Prüfe ob Script mit sudo-Rechten ausgeführt wird
if [ "$EUID" -ne 0 ]; then 
    echo "Bitte führen Sie das Skript mit sudo aus"
    exit 1
fi

# Installiere benötigte Pakete
echo "Installiere Abhängigkeiten..."
apt-get update
apt-get install -y python3-pip python3-tk i3lock

# Installiere Python-Pakete
echo "Installiere Python-Pakete..."
pip3 install opencv-python face_recognition numpy pillow pystray psutil

# Erstelle Programmverzeichnis
echo "Erstelle Programmverzeichnis..."
install -d /opt/tuxguard

# Kopiere Programmdateien
echo "Kopiere Programmdateien..."
install -m 755 tuxguardtest.py /opt/tuxguard/tuxguard.py
install -m 644 tux.ico /opt/tuxguard/

# Erstelle Desktop-Datei
echo "Erstelle Desktop-Starter..."
cat > /usr/share/applications/tuxguard.desktop << EOL
[Desktop Entry]
Version=1.0
Name=TuxGuard
Comment=Gesichtserkennung-Sicherheitssystem
Exec=/usr/bin/python3 /opt/tuxguard/tuxguard.py
Icon=/opt/tuxguard/tux.ico
Terminal=false
Type=Application
Categories=Utility;Security;
EOL

echo "Installation abgeschlossen!"
echo "Sie können TuxGuard jetzt über das Anwendungsmenü starten oder mit dem Befehl: python3 /opt/tuxguard/tuxguard.py"

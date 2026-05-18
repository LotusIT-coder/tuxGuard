#!/bin/bash

# Prüfe ob Script mit sudo-Rechten ausgeführt wird
if [ "$EUID" -ne 0 ]; then 
    echo "Bitte führen Sie das Skript mit sudo aus"
    exit 1
fi

# Installiere benötigte Systempakete
echo "Installiere Abhängigkeiten..."
apt-get update
apt-get install -y python3 python3-venv python3-tk git i3lock v4l-utils lsof

# Erstelle Programmverzeichnis
echo "Erstelle Programmverzeichnis..."
install -d /opt/tuxguard
install -d /opt/tuxguard/models

# Erstelle Log-Verzeichnis
echo "Erstelle Log-Verzeichnis..."
install -d -m 755 /var/log/tuxguard
if [ -n "$SUDO_USER" ]; then
    chown "$SUDO_USER:$SUDO_USER" /var/log/tuxguard
fi

# Hinweis: Die Gesichtserkennung läuft standardmäßig über die robusten
# OpenCV-Haar-Cascades (Frontal + Profil + Spiegel + Rotationen + CLAHE).
# Das frühere MediaPipe-Modell wird nicht mehr automatisch geladen, weil
# MediaPipe und TensorFlow im selben Prozess zu LLVM/TFLite-Symbolkonflikten
# ("PassRegistry") und Segfaults führen können. Wer MediaPipe optional
# nutzen will, kann es manuell installieren und über die Umgebungsvariable
# TUXGUARD_USE_MEDIAPIPE=1 im isolierten Worker-Subprozess aktivieren.

# Erstelle Python Virtual Environment
echo "Erstelle Virtual Environment..."
python3 -m venv /opt/tuxguard/.venv

# Aktualisiere Paketwerkzeuge im venv
echo "Aktualisiere pip und setuptools..."
/opt/tuxguard/.venv/bin/python -m pip install --upgrade pip setuptools wheel

# Installiere Python-Pakete im Virtual Environment
echo "Installiere Python-Pakete im Virtual Environment..."
/opt/tuxguard/.venv/bin/python -m pip install opencv-python numpy pillow pystray psutil pynput tensorflow

# Kopiere alle Programmdateien (nicht nur das Hauptskript)
echo "Kopiere Programmdateien..."
install -m 755 tuxguard_refactored.py /opt/tuxguard/tuxguard.py
install -m 644 *.py /opt/tuxguard/ 2>/dev/null || true
install -m 644 tux_256.png /opt/tuxguard/
install -m 644 *.db /opt/tuxguard/ 2>/dev/null || true

# Kopiere models und ihre Inhalte
if [ -d "models" ]; then
    cp -r models/* /opt/tuxguard/models/ 2>/dev/null || true
fi

# Erstelle Launcher-Wrapper
echo "Erstelle Launcher-Wrapper..."
cat > /usr/local/bin/tuxguard << 'WRAPPER'
#!/bin/bash
INSTALL_DIR="/opt/tuxguard"
VENV_DIR="/opt/tuxguard/.venv"
PYTHON_CMD="/usr/bin/python3"

# Überprüfe, ob das Installationsverzeichnis existiert
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Fehler: TuxGuard ist nicht installiert unter $INSTALL_DIR"
    exit 1
fi

# Verwende Virtual Environment Python, falls vorhanden
if [ -f "$VENV_DIR/bin/python" ]; then
    PYTHON_CMD="$VENV_DIR/bin/python"
fi

# Setze Umgebungsvariablen für headless-Betrieb
export MEDIAPIPE_DISABLE_GPU=1
export TF_CPP_MIN_LOG_LEVEL=2
export DISPLAY=${DISPLAY:-:0}

# Starte die Anwendung im installierten Verzeichnis
cd "$INSTALL_DIR"
exec "$PYTHON_CMD" tuxguard.py "$@"
WRAPPER
chmod 755 /usr/local/bin/tuxguard

# Erstelle Desktop-Datei mit Launcher-Aufruf
echo "Erstelle Desktop-Starter..."
cat > /usr/share/applications/tuxguard.desktop << EOL
[Desktop Entry]
Version=1.0
Name=TuxGuard
Comment=Gesichtserkennung-Sicherheitssystem
Exec=/usr/local/bin/tuxguard
Icon=/opt/tuxguard/tux_256.png
StartupWMClass=TuxGuard
Terminal=false
Type=Application
Categories=Utility;Security;
EOL

# Stelle sicher, dass der Benutzer Speicher-/Schreibzugriff hat
chmod -R 755 /opt/tuxguard
if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:$SUDO_USER" /opt/tuxguard
fi

# ---------------------------------------------------------------------------
# Master-Passwort + Recovery-Code einrichten
# ---------------------------------------------------------------------------
MASTER_FILE="/opt/tuxguard/master_credentials.json"
if [ -f "$MASTER_FILE" ]; then
    echo "Bestehende Master-Credentials gefunden – überspringe Master-Setup."
else
    echo ""
    echo "==============================================================="
    echo " TuxGuard Master-Passwort einrichten"
    echo "==============================================================="
    echo "Dieses Passwort schützt zentrale TuxGuard-Aktionen."
    echo "Es kann später NUR mit dem angezeigten Recovery-Code geändert werden."
    echo ""

    MASTER_PW=""
    while true; do
        read -r -s -p "Master-Passwort (min. 8 Zeichen): " PW1; echo
        read -r -s -p "Master-Passwort wiederholen:       " PW2; echo
        if [ ${#PW1} -lt 8 ]; then
            echo "  → Zu kurz, bitte mindestens 8 Zeichen wählen."
            continue
        fi
        if [ "$PW1" != "$PW2" ]; then
            echo "  → Passwörter stimmen nicht überein, bitte neu eingeben."
            continue
        fi
        MASTER_PW="$PW1"
        break
    done

    echo ""
    echo "Erzeuge Master-Credentials..."
    RECOVERY_CODE=$(MASTER_PW="$MASTER_PW" /opt/tuxguard/.venv/bin/python - <<'PY'
import os, sys
sys.path.insert(0, "/opt/tuxguard")
from auth import MasterAuth, MasterAuthError
try:
    code = MasterAuth().initialize(os.environ["MASTER_PW"])
    print(code)
except MasterAuthError as exc:
    sys.stderr.write(f"FEHLER: {exc}\n")
    sys.exit(1)
PY
)
    if [ -z "$RECOVERY_CODE" ]; then
        echo "FEHLER: Master-Setup fehlgeschlagen. Bitte tuxguard manuell starten und einrichten."
    else
        # Datei dem Benutzer zuweisen, damit GUI sie schreiben kann
        if [ -n "$SUDO_USER" ]; then
            chown "$SUDO_USER:$SUDO_USER" "$MASTER_FILE"
        fi
        chmod 600 "$MASTER_FILE"

        echo ""
        echo "==============================================================="
        echo " ⚠️  RECOVERY-CODE – BITTE SICHER AUFBEWAHREN!"
        echo "==============================================================="
        echo ""
        echo "    $RECOVERY_CODE"
        echo ""
        echo " Dieser Code ist die EINZIGE Möglichkeit, das Master-Passwort"
        echo " später zurückzusetzen. Notieren Sie ihn JETZT."
        echo "==============================================================="
        echo ""
        read -r -p "Drücken Sie ENTER, sobald Sie den Recovery-Code gesichert haben..." _ack
    fi
    unset MASTER_PW PW1 PW2
fi

echo "Installation abgeschlossen!"
echo "Sie können TuxGuard jetzt über das Anwendungsmenü starten oder mit: tuxguard"

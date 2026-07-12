# TuxGuard 2.0.0

TuxGuard ist eine Linux-Desktop-Sicherheitsanwendung mit Gesichtserkennung, optionaler Tippmustererkennung als zweitem Faktor und konfigurierbaren Reaktionen (z. B. Warnen, Sperren, Deadman).

## Hauptfunktionen

- Live-Überwachung per Kamera
- Benutzerverwaltung (Anlegen, Löschen, Bildverwaltung)
- Sicherheitsmodus mit Lock-/Deadman-Logik
- Tippmustererkennung als 2. Faktor
- Konfigurierbare Faktor-Fusion (face_only, keystroke_only, any, all, priority)
- Admin-geschützte sicherheitsrelevante Einstellungen

## Neu in der UI

Im Tab Überwachung gibt es eine eigene Sektion für die Tippmustererkennung:

- Aktivieren/Deaktivieren der Tippmustererkennung
- Systemweite Erfassung (pynput)
- Adaptives Lernen
- Schwellwert (Empfindlichkeit)
- Mindestanzahl Anschläge fürs Anlernen
- Fusionsmodus und Primärfaktor
- Reaktionen bei Gesichtsverlust, fremdem Tippmuster und fehlendem Tippmuster
- Sichtbarer Button für Tippmuster-Training (kein verstecktes Kontextmenü nötig)

Hinweis: Änderungen an Sicherheits- und Tippmusteroptionen werden zur Laufzeit auf die Config-Klasse angewendet. Bei aktiver Überwachung wird der Tippmuster-Monitor automatisch neu gestartet, damit Änderungen sofort greifen.

## Voraussetzungen

- Linux mit grafischer Oberfläche (Tk)
- Python 3.10+
- Kamera (für Gesichtserkennung)

## Entwicklung: Schnellstart

1. Virtuelle Umgebung anlegen:

   python3 -m venv .venv

2. Abhängigkeiten installieren:

   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/python -m pip install opencv-python numpy pillow pystray psutil pynput pytest

3. Anwendung starten:

   .venv/bin/python tuxguard_refactored.py

## Tests

Tests laufen mit pytest:

.venv/bin/python -m pytest

Aktueller Stand: 118 Tests bestanden.

## Produktion/Installation

Für eine systemweite Installation ist ein Installer vorhanden:

- install.sh
- uninstall.sh

Der Installer richtet unter anderem /opt/tuxguard, einen Launcher und eine Desktop-Datei ein.

## Wichtige Dateien

- tuxguard_refactored.py: Haupteinstiegspunkt
- simple_ui.py: Tkinter-Oberfläche
- config.py: Konfigurationswerte
- database.py: Datenbankzugriff
- auth.py: Master-Auth und Recovery-Flow
- tests/: Test-Suite

## Sicherheitshinweise

- Das Master-Passwort schützt zentrale Admin-Aktionen.
- Der Recovery-Code sollte offline und sicher gespeichert werden.
- Tippmustererkennung nutzt Timing-Merkmale, nicht den eingegebenen Textinhalt.

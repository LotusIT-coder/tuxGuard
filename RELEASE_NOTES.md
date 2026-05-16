# Release Notes

## Zusammenfassung
Dieses Update verbessert die Sichtbarkeit der Erkennung im Kamera-Testmodus und ergänzt eine ausführliche Projekt-Dokumentation für GitHub.

## Enthaltene Änderungen

### 1. Kamera-Testmodus verbessert
Datei: `TuxGuard(1.0.0)/camera.py`

- Gesichtsrahmen (Bounding Boxes) werden im Testmodus sichtbar gezeichnet.
- Erkannter Name wird direkt am Gesicht eingeblendet.
- Emotion inkl. Konfidenzwert wird pro Gesicht angezeigt.
- Statuszeile zeigt zusätzlich erkannte Emotionen und Prozentwerte.
- Testmodus-Anzeige wurde robuster gemacht, damit Emotion/Konfidenz auch bei schwankender Erkennung nachvollziehbar bleibt.

### 2. Neue ausführliche README
Datei: `README.md`

- Projektüberblick und Feature-Beschreibung
- Installations- und Update-Anleitung
- Deinstallationshinweise
- Sicherheitsmodell (Master-Passwort, Recovery-Code, Modi)
- Hinweise zu Kamera-/Emotionslogik
- Testausführung mit Pytest
- Troubleshooting und Datenschutz-Hinweise

## Wichtiger Hinweis zum Verhalten
- Im Testmodus sind Erkennungsdetails absichtlich sichtbar.
- Im Überwachungsmodus bleibt die Vorschau neutral (keine sichtbaren Erkennungsdetails).

## Technische Daten
- Commit: e69ddfd
- Geänderte Dateien:
  - README.md
  - TuxGuard(1.0.0)/camera.py

## Vorschlag für GitHub-Release-Titel
Testmodus: Emotionsanzeige + Konfidenz repariert, README deutlich erweitert

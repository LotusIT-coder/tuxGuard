# TuxGuard

TuxGuard ist eine lokale Linux-Sicherheitsanwendung mit Gesichtserkennung, PIN-/Passwort-Gates und kontinuierlicher Ueberwachung.

Die App ist fuer Desktop-Setups gedacht, bei denen ein System vor unautorisiertem Zugriff geschuetzt werden soll, ohne Cloud-Anbindung und ohne externe Benutzerverwaltung.

## Highlights

- Lokale Benutzerverwaltung mit Gesichtsmerkmalen (Encodings)
- Master-Passwort + Recovery-Code fuer administrative Schutzfunktionen
- Drei Sicherheitsmodi:
  - `self_unlock`: Gesicht kann Sperre automatisch aufheben
  - `strict_pin`: Erkanntes Gesicht braucht zusaetzlich PIN zur Entsperrung
  - `deadman`: Bei ausbleibender legitimer Erkennung wird eine Deadman-Aktion ausgeloest
- Kamera-Testmodus mit sichtbarer Gesichtserkennung und Emotions/Konfidenz-Anzeige
- Ueberwachungsmodus mit neutraler Vorschau (keine sichtbaren Erkennungsdetails)
- System-Tray-Unterstuetzung und optionaler Autostart als User-Service
- Logging in Datei und GUI

## Projektstruktur

Das Repository ist aktuell als Wrapper-Repo mit Unterordner organisiert:

- `TuxGuard(1.0.0)/` enthaelt den eigentlichen Anwendungscode
- Root enthaelt Git-Metadaten und jetzt diese README

Wichtige Dateien:

- `TuxGuard(1.0.0)/tuxguard_refactored.py` - Haupteinstieg der Anwendung
- `TuxGuard(1.0.0)/camera.py` - Kamerazugriff, Erkennung, Emotionen, Testmodus
- `TuxGuard(1.0.0)/database.py` - Benutzer- und Gesichtsdatenbank
- `TuxGuard(1.0.0)/auth.py` - MasterAuth und Recovery-Logik
- `TuxGuard(1.0.0)/simple_ui.py` - Tkinter UI
- `TuxGuard(1.0.0)/config.py` - Zentrale Konfiguration
- `TuxGuard(1.0.0)/install.sh` - Installation nach `/opt/tuxguard`
- `TuxGuard(1.0.0)/tests/` - Pytest-Suite

## Voraussetzungen

### Betrieb (Installationsskript)

- Linux Desktop mit GUI/Display
- `python3`, `python3-venv`, `python3-tk`
- `i3lock`, `v4l-utils`, `lsof`
- Root-Rechte fuer Installation nach `/opt/tuxguard`

Das Skript installiert Python-Abhaengigkeiten in `/opt/tuxguard/.venv`.

### Entwicklung

- Python 3.10+
- Virtuelle Umgebung empfohlen
- Optional Kamera/Display fuer Integrationspfade

## Installation

Repository klonen und in den App-Ordner wechseln:

```bash
git clone https://github.com/LotusIT-coder/tuxGuard.git
cd "tuxGuard/TuxGuard(1.0.0)"
```

Installieren:

```bash
sudo bash install.sh
```

Starten:

```bash
tuxguard
```

## Update einer bestehenden Installation

Wenn du Aenderungen am Code gemacht hast (z. B. Testmodus/Emotionen), musst du die installierte Instanz neu ausrollen:

```bash
cd "TuxGuard(1.0.0)"
sudo bash install.sh
```

Danach App neu starten.

## Deinstallation

```bash
cd "TuxGuard(1.0.0)"
sudo bash uninstall.sh
```

## Sicherheitsmodell (Kurzueberblick)

1. Master-Credentials
- Beim ersten Setup wird ein Master-Passwort gesetzt.
- Ein Recovery-Code wird erzeugt und muss sicher abgelegt werden.
- Passwort und Recovery-Informationen werden gehasht gespeichert.

2. Benutzerzugriff
- Login mit Benutzer+Passwort beim Start.
- Optional weitere Admin-Passwoerter.

3. Laufende Ueberwachung
- Kamera prueft auf legitime/illegitime Praesenz.
- Je nach Modus wird automatisch entsperrt, PIN verlangt oder Deadman-Aktion ausgefuehrt.

## Sicherheitsmodi im Detail

TuxGuard bietet drei distinct Sicherheitsmodi, die in den UI-Einstellungen konfigurierbar sind.

### 1. `self_unlock` - Automatische Entsperrung bei Erkennung

- Erkannter Benutzer hebt Sperre sofort auf, ohne zusaetzliche Eingabe.
- **Verhaeltnis**: Geringste Intervention, aber auch geringste Huerden.
- **Anwendungsfall**: Zuhause/vertrauenswuerdigem Umfeld mit zuverlässiger Kamera.

### 2. `strict_pin` - Gesicht + PIN

- Erkannter Benutzer muss zusaetzlich seine PIN eingeben, um zu entsperren.
- Nutzt den Erkennungsstand als einen Faktor, der PIN ist der zweite.
- **Verhaeltnis**: Mittleres Sicherheitsniveau mit aktiver Benutzerinteraktion.
- **Anwendungsfall**: Bueros, gemeinsame Systeme, wo Kamera-Spoofing oder Nachahmer moeglichst abgewehrt werden sollen.

### 3. `deadman` - Totmannschalter mit erzwungener Aktion

**Konzept:**
- Ein Totmannschalter (Deadman's Switch) ist eine Failsafe-Komponente, die automatisch eine Schutzaktion ausloest, wenn kein explizites Signal mehr eingeht.
- In TuxGuard: Wenn ueber einen konfigurierbaren Zeitraum (Default: 60 Sekunden) KEINE legitimen Benutzer erkannt werden, wird eine Aktion erzwungen.

**Verhalten:**
1. Ueberwachung startet.
2. Wenn legitimer Benutzer erkannt wird, wird der Timer zurueckgesetzt.
3. Wenn KEIN Benutzer erkannt wird:
   - Timer laeuft ab.
   - Aktion wird ausgeloest.
4. Aktion kann sein:
   - **`suspend`**: System wird in den Ruhezustand versetzt (ACPI S3/S4).
   - **`shutdown`**: System wird heruntergefahren.

**Konfiguration:**
- Timeout: `DEADMAN_TIMEOUT_SECONDS` (in `TuxGuard(1.0.0)/config.py`, Default 60 Sekunden)
- Aktion: `DEADMAN_ACTION` (in `TuxGuard(1.0.0)/config.py`, Default "suspend")
- Einstellbar in der UI unter "Sicherheitsmodus" (erfordert Master-Passwort)

**Anwendungsfaelle:**
- **Raum-Verlassen**: Wenn der legitime Benutzer den Schreibtisch verlaesst und nicht wiederkehrt, wird das System automatisch gesichert.
- **Kamera-Ausfall-Fallback**: Wenn Kamera abgedeckt/unterbrochen ist und keine Gesichter erkannt werden, triggert Deadman nach kurzer Zeit.
- **Unerwuenschtes Mitschreiben**: In Bueros, wo das System nach X Sekunden ohne Autorisierung den Zugriff unterbricht.
- **Physische Sicherheit**: Wenn der Monitor verlassen wird, ohne dass der Benutzer aktiv abgemeldet hat.

**Wichtige Hinweise:**
- Deadman ist **nicht** dasselbe wie Auto-Lock. Auto-Lock sperrt nach Inaktivitaet des Nutzers; Deadman sperrt/speichert, wenn das System PHYSISCH unbeobachtet ist.
- Wenn keine Kamera vorhanden ist oder Kamera-Fehler auftritt, laeuft Deadman sofort nach Timeout ab.
- Eine zu kurze Timeout kann zu unerwünschtem Suspend/Shutdown führen (z. B. bei Kameraschwankungen oder Durchzug).
- Mindestempfohlener Timeout: 10-30 Sekunden (Balance zwischen Schutz und Praktikabilitaet).

## Kamera- und Emotionslogik

### Testmodus

Der Kamera-Test zeigt bewusst sichtbare Details:

- Face-Boxen
- erkannter Name
- Emotion + Konfidenz pro Gesicht
- Statusindikator (Gesicht erkannt / kein Gesicht erkannt)

### Ueberwachungsmodus

Die Vorschau bleibt absichtlich neutral und zeigt keine sichtbaren Erkennungsdetails.
Das reduziert Informationsabfluss in der Normalansicht.

## Konfiguration

Die wichtigsten Parameter stehen in `TuxGuard(1.0.0)/config.py`, z. B.:

- Sicherheitsmodus (`SECURITY_MODE`)
- Deadman-Timeout/Aktion
- Emotions-Schwellen und Backend-Wahl
- UI-Verhalten beim Minimieren/Schliessen

## Tests

Im App-Ordner:

```bash
cd "TuxGuard(1.0.0)"
python -m pytest
```

Hinweise:

- `pytest.ini` markiert optionale Integrationspfade (`integration`, `requires_display`, `requires_camera`).
- In headless Umgebungen sollten Integrations-/Display-Tests ggf. selektiv ausgefuehrt werden.

## Troubleshooting

### 1) Kamera-Test zeigt Bild, aber keine Emotionen

- Sicherstellen, dass die aktuelle Codeversion installiert wurde (`sudo bash install.sh`).
- App danach komplett neu starten.
- In Logs nach Backend/Fallback-Meldungen suchen.

### 2) Keine Kamera verfuegbar

- Rechte auf `/dev/video*` pruefen
- Parallel laufende Prozesse pruefen (`lsof /dev/video*`)
- Diagnosefunktion in der App verwenden

### 3) Tray/Autostart verhaelt sich unerwartet

- User-Service und UI-Einstellungen pruefen
- Logs unter `/opt/tuxguard/logs/` kontrollieren

## Datenschutz

- TuxGuard arbeitet lokal auf dem Geraet.
- Keine Cloud-Pflicht im Standardfluss.
- Sensible Daten (Passwoerter/Recovery) werden nicht im Klartext gespeichert.

## Haftung / Einsatzhinweis

Dieses Projekt ist ein lokales Security-Tool fuer kontrollierte Umgebungen. Vor produktivem Einsatz sollten Bedrohungsmodell, Betriebskontext und Hardening-Massnahmen separat validiert werden.

## Lizenz

Aktuell ist keine explizite Lizenzdatei im Repository vorhanden.
Wenn das Projekt veroeffentlicht oder extern genutzt werden soll, sollte eine passende Lizenz (`LICENSE`) ergaenzt werden.

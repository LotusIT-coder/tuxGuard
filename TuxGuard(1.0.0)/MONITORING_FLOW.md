# TuxGuard Überwachungsflow - Dokumentation

## Überblick
Der Überwachungsflow wurde grundlegend überarbeitet, um zuverlässige Sicherheitsmaßnahmen bei unerlaubtem Zugriff zu gewährleisten.

## Kamera-Überwachung

### Erkennungslogik
1. **Gesichtserkennung läuft kontinuierlich** im Hintergrund
2. **Drei mögliche Zustände:**
   - `authorized`: Bekannter Benutzer erkannt
   - `unauthorized`: Unbekanntes Gesicht ODER keine Gesichtserkennung
   - `None`: Initialer Zustand

### Grace Period (Debounce)
- **1 Sekunde Verzögerung** bevor Statuswechsel ausgelöst wird
- Verhindert falsche Alarme bei kurzen Erkennungsfehlern
- Schnell genug für effektive Sicherheit

### Unauthorized Access Trigger
**Wird ausgelöst bei:**
- ✅ Unbekanntes Gesicht erkannt
- ✅ Kamera abgedeckt (kein Gesicht im Bild)
- ✅ Niemand vor der Kamera

**Folge:**
→ `_on_unauthorized_access()` Callback wird aufgerufen
→ Sicherheitsmaßnahmen werden eingeleitet

## Mausüberwachung

### Verifikationslogik
1. **Regelmäßige Überprüfung** alle 5 Sekunden (Config.MOUSE_MONITOR_INTERVAL)
2. **3 Sekunden Datensammlung** für jede Verifikation
3. **Modellbasierte Mustererkennung** mit trainiertem Keras-Modell
4. **Konfidenz-Schwellenwert:** 0.60 (Config.MOUSE_VERIFICATION_THRESHOLD)

### Unauthorized Access Trigger
**Wird ausgelöst bei:**
- ✅ Konfidenz < 0.60 (Muster nicht erkannt)
- ✅ Abweichendes Nutzungsverhalten

**Folge:**
→ `_on_mouse_verification_failed()` Callback wird aufgerufen
→ Sicherheitsmaßnahmen werden eingeleitet

## Sicherheitsmaßnahmen

### Flow bei unerlaubtem Zugriff
```
1. Callback ausgelöst (_on_unauthorized_access oder _on_mouse_verification_failed)
   ↓
2. Überwachung temporär gestoppt (verhindert Callback-Loop)
   ↓
3. Fenster wird wiederhergestellt (falls minimiert)
   ↓
4. Sicherheitsdialog wird angezeigt
   ↓
5. Benutzer-Authentifizierung erforderlich
```

### Sicherheitsdialog
**Eigenschaften:**
- 🔒 **Modal**: Kann nicht geschlossen werden
- ⏱️ **60 Sekunden Timeout**: Automatische Sperre bei Ablauf
- 🔑 **PIN-Eingabe erforderlich**: Keine alternative Schließmöglichkeit
- 🔝 **Always on top**: Bleibt im Vordergrund

**Zwei mögliche Ausgänge:**
1. ✅ **Korrekte PIN:** 
   - Dialog schließt
   - Überwachung wird neugestartet
   - Normaler Betrieb

2. ❌ **Falsche PIN oder Timeout:**
   - System wird mit `i3lock` gesperrt
   - Fallback: `systemctl suspend` falls i3lock nicht verfügbar
   - Überwachung bleibt gestoppt

## Vorteile der neuen Architektur

### 1. Konsistente Sicherheit
- Beide Überwachungstypen (Kamera + Maus) führen zu gleichen Maßnahmen
- Keine "nur logging" Situationen mehr

### 2. Robustheit
- Grace Period verhindert False Positives
- Callback-basierte Architektur ermöglicht klare Trennung
- Error Handling auf allen Ebenen

### 3. Benutzerfreundlichkeit
- Klare Fehlermeldungen mit Grund
- 60s Timeout verhindert ewiges Warten
- Möglichkeit zur Authentifizierung statt sofortiger Sperre

### 4. Sicherheit
- Keine Umgehungsmöglichkeit des Dialogs
- System-Level Lock (i3lock) als finale Maßnahme
- Überwachung stoppt bei Alarm (verhindert Spam)

## Konfiguration

### Anpassbare Parameter (config.py)
```python
MOUSE_MONITOR_INTERVAL = 5          # Sekunden zwischen Überprüfungen
MOUSE_VERIFICATION_THRESHOLD = 0.60  # Mindest-Konfidenz für Autorisation
```

### Kamera Grace Period (camera.py)
```python
GRACE_PERIOD = 1.0  # Sekunden vor Statuswechsel
```

### Dialog Timeout (tuxguard_refactored.py)
```python
timeout_counter = [60]  # Sekunden bis automatische Sperre
```

## Debugging

### Log-Level für Überwachung
- **INFO**: Normale Ereignisse (Benutzer erkannt, Monitoring gestartet)
- **WARNING**: Sicherheitsereignisse (Unerlaubter Zugriff, Verifikation fehlgeschlagen)
- **ERROR**: Technische Fehler (Kamera-Probleme, Callback-Fehler)

### Wichtige Log-Nachrichten
```
"Benutzer erkannt: {name}"                    → Autorisierter Zugriff
"Unerlaubter Zugriff erkannt"                 → Kamera-Alarm
"Mausmuster-Verifikation fehlgeschlagen!"     → Maus-Alarm
"Sicherheitsmaßnahmen werden eingeleitet"     → Lock wird ausgelöst
"PIN korrekt - Zugriff gewährt"               → Erfolgreiche Re-Authentifizierung
```

## Fehlerbehebung

### Problem: Zu viele False Positives (Kamera)
**Lösung:** Grace Period erhöhen in `camera.py`
```python
GRACE_PERIOD = 2.0  # statt 1.0
```

### Problem: Zu viele False Positives (Maus)
**Lösung 1:** Threshold senken in `config.py`
```python
MOUSE_VERIFICATION_THRESHOLD = 0.50  # statt 0.60
```

**Lösung 2:** Mehr Training für bessere Modellqualität
- "Mausbewegungen trainieren" mehrmals ausführen
- Verschiedene Nutzungsszenarien trainieren

### Problem: System sperrt zu schnell
**Lösung:** Monitor-Intervall erhöhen
```python
MOUSE_MONITOR_INTERVAL = 10  # statt 5 Sekunden
```

## Zusammenfassung

✅ **Kamera abgedeckt** → Unauthorized Access → PIN-Dialog → Lock bei Fehler  
✅ **Fremdes Gesicht** → Unauthorized Access → PIN-Dialog → Lock bei Fehler  
✅ **Fremde Mausmuster** → Verification Failed → PIN-Dialog → Lock bei Fehler  

Der Flow ist jetzt vollständig und führt konsequent zu Sicherheitsmaßnahmen!

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tippmustererkennung (Keystroke Dynamics) für TuxGuard.

Zweiter Faktor der **permanenten Überwachung** – zusätzlich zur Bilderkennung.
Während der Überwachung wird der Tipprhythmus laufend mit dem je Nutzer
angelernten Referenzmuster verglichen. Tippt jemand mit fremdem Rhythmus, ist
das ein Eindringling-Signal; tippt der legitime Nutzer, bestätigt das seine
Anwesenheit (Heartbeat).

Verwendet wird ein **Freitext**-Modell (length-independent): Im Alltag wird
beliebiger Text getippt, daher dürfen die Merkmale nicht von einer festen Phrase
abhängen. Zwei klassische Zeitmerkmale werden über viele Anschläge gemittelt:

* **Dwell time** (Haltezeit): Dauer eines Tastendrucks (Press → Release).
* **Flight time** (Flugzeit): Abstand zwischen dem Loslassen einer Taste und
  dem Drücken der nächsten innerhalb desselben Tipplaufs.

Ein Referenzprofil speichert Mittelwert und Streuung von Halte- und Flugzeit.
Eine Live-Probe (Fenster aus mehreren Anschlägen) liefert ihrerseits mittlere
Halte-/Flugzeit; verglichen wird über eine normierte (z-artige) Distanz:

    d = mean( |x_dwell - m_dwell| / (s_dwell + floor),
              |x_flight - m_flight| / (s_flight + floor) )

Liegt ``d`` unter einem Schwellwert, gilt der Tipprhythmus als übereinstimmend.

Sicherheit/Datenschutz: Es werden ausschließlich **Zeitabstände** gespeichert –
niemals die getippten Zeichen. Das Profil erlaubt keine Rückschlüsse auf den
Inhalt der Eingaben.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("TuxGuard.Keystroke")

# ---------------------------------------------------------------------------
# Tastenklassen
# ---------------------------------------------------------------------------

# Modifikatoren erzeugen kein Zeichen und werden ignoriert (sie unterbrechen
# einen Tipplauf NICHT – z. B. Shift vor einem Großbuchstaben).
_MODIFIER_KEYSYMS = frozenset({
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Caps_Lock", "Num_Lock", "Super_L", "Super_R", "Meta_L", "Meta_R",
    "ISO_Level3_Shift", "Multi_key", "Menu", "shift", "ctrl", "alt", "cmd",
})

PROFILE_VERSION = 2
PROFILE_KIND = "freetext"


@dataclass
class KeystrokeConfig:
    """Einstellbare Parameter der Tippmustererkennung."""

    enabled: bool = True
    # Systemweite Erfassung (pynput). Falls nicht verfügbar, degradiert sauber.
    global_capture: bool = True
    # Anschläge für ein vollständiges Referenzprofil (Anlernen).
    min_enrollment_keystrokes: int = 200
    # Fenstergröße einer Live-Probe während der Überwachung.
    match_window_keystrokes: int = 30
    # Obergrenze adaptiv gelernter Anschläge.
    max_profile_keystrokes: int = 2000
    # Schwellwert der normierten Distanz (kleiner = strenger).
    match_threshold: float = 1.8
    # Plausibilitätsgrenzen (größere Werte beenden einen Tipplauf).
    max_dwell_ms: float = 600.0
    max_flight_ms: float = 1500.0
    # Untergrenze der Streuung im Distanzmaß (verhindert Überstrenge).
    std_floor_ms: float = 8.0
    # Profil mit bestätigten Proben nachschärfen (adaptives Lernen).
    adaptive_learning: bool = True
    # Wie lange eine bestätigte Probe als „präsent" gilt (Sekunden).
    presence_ttl_seconds: float = 90.0
    # Wie lange ein fremdes Tippmuster nachwirkt (Sekunden).
    intruder_ttl_seconds: float = 30.0

    @classmethod
    def from_app_config(cls, config) -> "KeystrokeConfig":
        """Erzeugt die Konfiguration aus dem globalen ``Config``-Objekt."""
        g = lambda name, default: getattr(config, name, default)  # noqa: E731
        return cls(
            enabled=bool(g("KEYSTROKE_DYNAMICS_ENABLED", True)),
            global_capture=bool(g("KEYSTROKE_GLOBAL_CAPTURE", True)),
            min_enrollment_keystrokes=int(g("KEYSTROKE_MIN_ENROLLMENT_KEYSTROKES", 200)),
            match_window_keystrokes=int(g("KEYSTROKE_MATCH_WINDOW_KEYSTROKES", 30)),
            max_profile_keystrokes=int(g("KEYSTROKE_MAX_PROFILE_KEYSTROKES", 2000)),
            match_threshold=float(g("KEYSTROKE_MATCH_THRESHOLD", 1.8)),
            max_dwell_ms=float(g("KEYSTROKE_MAX_DWELL_MS", 600.0)),
            max_flight_ms=float(g("KEYSTROKE_MAX_FLIGHT_MS", 1500.0)),
            std_floor_ms=float(g("KEYSTROKE_STD_FLOOR_MS", 8.0)),
            adaptive_learning=bool(g("KEYSTROKE_ADAPTIVE_LEARNING", True)),
            presence_ttl_seconds=float(g("KEYSTROKE_PRESENCE_TTL_SECONDS", 90.0)),
            intruder_ttl_seconds=float(g("KEYSTROKE_INTRUDER_TTL_SECONDS", 30.0)),
        )


# ---------------------------------------------------------------------------
# Aufnahme der Tastatur-Zeitstempel (Freitext, segmentiert in Tippläufe)
# ---------------------------------------------------------------------------

class KeystrokeRecorder:
    """Sammelt Halte-/Flugzeiten aus fortlaufendem Tippen.

    Bewusst ``tkinter``-unabhängig: ``on_press``/``on_release`` akzeptieren
    beliebige Event-Objekte mit den Attributen ``keysym`` und ``char`` (Tk wie
    auch der pynput-Adapter liefern solche Shims). Ein „Tipplauf" ist eine
    Folge zusammenhängender Zeichen-Anschläge; Editier-/Navigationstasten oder
    lange Pausen beenden einen Lauf, sodass nur sinnvolle Flugzeiten entstehen.
    """

    def __init__(self, max_dwell_ms: float = 600.0, max_flight_ms: float = 1500.0):
        self.max_dwell_ms = float(max_dwell_ms)
        self.max_flight_ms = float(max_flight_ms)
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._pending: Dict[str, float] = {}
            self._dwell: List[float] = []
            self._flight: List[float] = []
            self._last_release: Optional[float] = None
            self._run_broken = True

    # -- Tkinter-Anbindung ------------------------------------------------
    def attach(self, widget) -> None:
        """Bindet die Press-/Release-Handler an ein Tk-Widget."""
        widget.bind("<KeyPress>", self.on_press, add="+")
        widget.bind("<KeyRelease>", self.on_release, add="+")

    # -- Event-Handler ----------------------------------------------------
    def on_press(self, event) -> None:
        keysym = getattr(event, "keysym", "") or ""
        if keysym in _MODIFIER_KEYSYMS:
            return  # Modifikatoren ignorieren, Lauf nicht unterbrechen.
        if not self._is_character(event):
            # Editier-/Navigationstaste o. Ä. -> Lauf beenden.
            with self._lock:
                self._run_broken = True
            return
        with self._lock:
            if keysym in self._pending:
                return  # Autorepeat ignorieren.
            self._pending[keysym] = time.perf_counter()

    def on_release(self, event) -> None:
        keysym = getattr(event, "keysym", "") or ""
        now = time.perf_counter()
        with self._lock:
            press = self._pending.pop(keysym, None)
            if press is None:
                return
            dwell_ms = (now - press) * 1000.0
            if dwell_ms < 0 or dwell_ms > self.max_dwell_ms:
                # Unplausible Haltezeit -> Lauf beenden, Anschlag verwerfen.
                self._run_broken = True
                self._last_release = None
                return
            if not self._run_broken and self._last_release is not None:
                flight_ms = (press - self._last_release) * 1000.0
                if 0.0 <= flight_ms <= self.max_flight_ms:
                    self._flight.append(flight_ms)
            self._dwell.append(dwell_ms)
            self._last_release = now
            self._run_broken = False

    @staticmethod
    def _is_character(event) -> bool:
        char = getattr(event, "char", "") or ""
        return len(char) == 1 and char.isprintable()

    # -- Auswertung -------------------------------------------------------
    @property
    def sample_size(self) -> int:
        """Anzahl bisher gesammelter Zeichen-Anschläge."""
        with self._lock:
            return len(self._dwell)

    def take_sample(self, min_keystrokes: int = 1) -> Optional[Dict[str, object]]:
        """Gibt die gesammelten Halte-/Flugzeiten zurück und setzt zurück.

        Liefert ``None``, wenn noch zu wenige Anschläge vorliegen.
        """
        with self._lock:
            if len(self._dwell) < int(max(1, min_keystrokes)):
                return None
            sample = {"dwell": list(self._dwell), "flight": list(self._flight)}
        self.reset()
        return sample


# ---------------------------------------------------------------------------
# Freitext-Profil & Abgleich
# ---------------------------------------------------------------------------

def _arrays(sample: Dict[str, object]) -> Tuple[np.ndarray, np.ndarray]:
    dwell = np.asarray(list((sample or {}).get("dwell", []) or []), dtype=np.float64)
    flight = np.asarray(list((sample or {}).get("flight", []) or []), dtype=np.float64)
    return dwell, flight


def build_profile(samples: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    """Erzeugt aus einer oder mehreren Proben ein Freitext-Referenzprofil.

    Alle Halte- und Flugzeiten werden zusammengeführt; gespeichert werden
    Mittelwert, Streuung und Anzahl je Merkmal.
    """
    dwell_all: List[np.ndarray] = []
    flight_all: List[np.ndarray] = []
    for sample in samples or []:
        dwell, flight = _arrays(sample)
        if dwell.size:
            dwell_all.append(dwell)
        if flight.size:
            flight_all.append(flight)

    if not dwell_all:
        return None
    dwell = np.concatenate(dwell_all)
    flight = np.concatenate(flight_all) if flight_all else np.asarray([], dtype=np.float64)
    if dwell.size < 1:
        return None

    return {
        "version": PROFILE_VERSION,
        "kind": PROFILE_KIND,
        "dwell_n": int(dwell.size),
        "dwell_mean": float(dwell.mean()),
        "dwell_std": float(dwell.std(ddof=0)),
        "flight_n": int(flight.size),
        "flight_mean": float(flight.mean()) if flight.size else 0.0,
        "flight_std": float(flight.std(ddof=0)) if flight.size else 0.0,
        "n_keystrokes": int(dwell.size),
    }


def match_distance(
    profile: Dict[str, object],
    sample: Dict[str, object],
    std_floor_ms: float = 8.0,
) -> float:
    """Normierte Distanz zwischen Profil und Live-Probe.

    Kleiner Wert = ähnlicher Tipprhythmus. ``inf`` bei leerer/ungültiger Probe
    oder fehlendem Profil.
    """
    if not profile:
        return float("inf")
    dwell, flight = _arrays(sample)
    if dwell.size < 1:
        return float("inf")
    floor = float(max(0.0, std_floor_ms))

    terms: List[float] = []
    d_mean = float(profile.get("dwell_mean", 0.0))
    d_std = float(profile.get("dwell_std", 0.0))
    terms.append(abs(float(dwell.mean()) - d_mean) / (d_std + floor))

    if flight.size >= 1 and int(profile.get("flight_n", 0)) >= 1:
        f_mean = float(profile.get("flight_mean", 0.0))
        f_std = float(profile.get("flight_std", 0.0))
        terms.append(abs(float(flight.mean()) - f_mean) / (f_std + floor))

    return float(np.mean(terms))


def is_match(
    profile: Dict[str, object],
    sample: Dict[str, object],
    threshold: float = 1.8,
    std_floor_ms: float = 8.0,
) -> bool:
    """True, wenn die Probe innerhalb des Schwellwerts zum Profil passt."""
    return match_distance(profile, sample, std_floor_ms=std_floor_ms) <= float(threshold)


def match_confidence(distance: float, threshold: float) -> float:
    """Wandelt eine Distanz in einen Vertrauenswert [0..1] (für Logs/Anzeige)."""
    if not np.isfinite(distance) or threshold <= 0:
        return 0.0
    return float(np.clip(1.0 - (distance / (2.0 * threshold)), 0.0, 1.0))


def _combine(mean_a: float, std_a: float, n_a: int,
             values: np.ndarray, max_n: int) -> Tuple[float, float, int]:
    """Vereint einen Aggregatzustand mit neuen Werten (Chan-Parallelvarianz)."""
    n_b = int(values.size)
    if n_b < 1:
        return mean_a, std_a, n_a
    n_a_eff = min(int(n_a), int(max_n))
    if n_a_eff < 1:
        return float(values.mean()), float(values.std(ddof=0)), n_b
    mean_b = float(values.mean())
    var_a = std_a ** 2
    var_b = float(values.var(ddof=0))
    n_total = n_a_eff + n_b
    delta = mean_b - mean_a
    mean_new = mean_a + delta * (n_b / n_total)
    m2 = var_a * n_a_eff + var_b * n_b + (delta ** 2) * (n_a_eff * n_b / n_total)
    var_new = m2 / n_total
    return float(mean_new), float(np.sqrt(max(0.0, var_new))), int(min(n_total, max_n))


def update_profile(
    profile: Dict[str, object],
    sample: Dict[str, object],
    max_keystrokes: int = 2000,
) -> Optional[Dict[str, object]]:
    """Verfeinert ein Profil inkrementell mit einer neuen Probe (adaptiv)."""
    if not profile:
        return profile
    dwell, flight = _arrays(sample)
    if dwell.size < 1:
        return profile

    d_mean, d_std, d_n = _combine(
        float(profile.get("dwell_mean", 0.0)), float(profile.get("dwell_std", 0.0)),
        int(profile.get("dwell_n", 0)), dwell, int(max_keystrokes),
    )
    if flight.size >= 1:
        f_mean, f_std, f_n = _combine(
            float(profile.get("flight_mean", 0.0)), float(profile.get("flight_std", 0.0)),
            int(profile.get("flight_n", 0)), flight, int(max_keystrokes),
        )
    else:
        f_mean = float(profile.get("flight_mean", 0.0))
        f_std = float(profile.get("flight_std", 0.0))
        f_n = int(profile.get("flight_n", 0))

    return {
        "version": PROFILE_VERSION,
        "kind": PROFILE_KIND,
        "dwell_n": d_n,
        "dwell_mean": d_mean,
        "dwell_std": d_std,
        "flight_n": f_n,
        "flight_mean": f_mean,
        "flight_std": f_std,
        "n_keystrokes": d_n,
    }


# ---------------------------------------------------------------------------
# (De-)Serialisierung
# ---------------------------------------------------------------------------

def serialize_profile(profile: Dict[str, object]) -> str:
    """Serialisiert ein Profil als kompakten JSON-Text."""
    return json.dumps(profile, separators=(",", ":"))


def deserialize_profile(blob: Optional[str]) -> Optional[Dict[str, object]]:
    """Liest ein Freitext-Profil aus JSON-Text zurück (mit Plausibilitätsprüfung)."""
    if not blob:
        return None
    try:
        profile = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(profile, dict):
        return None
    if "dwell_mean" not in profile or "dwell_std" not in profile:
        return None
    return profile


# ---------------------------------------------------------------------------
# Anlern-Hilfe (UI-unabhängig)
# ---------------------------------------------------------------------------

class EnrollmentCollector:
    """Sammelt Anschläge für das Anlernen und baut daraus ein Profil.

    UI-unabhängig, damit die Anlern-Logik testbar bleibt.
    """

    def __init__(self, required_keystrokes: int):
        self.required_keystrokes = int(max(1, required_keystrokes))
        self._dwell: List[float] = []
        self._flight: List[float] = []

    @property
    def count(self) -> int:
        return len(self._dwell)

    @property
    def complete(self) -> bool:
        return len(self._dwell) >= self.required_keystrokes

    def add(self, sample: Optional[Dict[str, object]]) -> int:
        """Fügt die Anschläge einer Probe hinzu. Liefert die neue Gesamtanzahl."""
        if sample:
            dwell, flight = _arrays(sample)
            self._dwell.extend(dwell.tolist())
            self._flight.extend(flight.tolist())
        return self.count

    def build(self) -> Optional[Dict[str, object]]:
        """Baut das Profil, sobald genügend Anschläge gesammelt wurden."""
        if len(self._dwell) < self.required_keystrokes:
            return None
        return build_profile([{"dwell": self._dwell, "flight": self._flight}])


# ---------------------------------------------------------------------------
# Globaler Tastatur-Monitor (systemweit, über pynput)
# ---------------------------------------------------------------------------

# Abbildung einiger pynput-Sondertasten auf keysym-Namen. Editier-/Navigations-
# tasten erhalten leeren ``char`` und beenden dadurch einen Tipplauf.
_PYNPUT_KEY_NAMES = {
    "shift": "shift", "shift_r": "shift", "shift_l": "shift",
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "cmd", "cmd_r": "cmd",
}


class _ShimEvent:
    """Minimales Event-Objekt mit ``keysym``/``char`` für den Recorder."""

    __slots__ = ("keysym", "char")

    def __init__(self, keysym: str, char: str):
        self.keysym = keysym
        self.char = char


def _adapt_pynput_key(key) -> _ShimEvent:
    """Wandelt einen pynput-Tastenwert in ein Recorder-Event.

    Es wird ausschließlich die Tastenidentität/-art ausgewertet – der konkrete
    Buchstabe dient nur dazu, Zeichen- von Sondertasten zu unterscheiden.
    """
    char = getattr(key, "char", None)
    if char and len(char) == 1 and char.isprintable():
        return _ShimEvent(keysym=char, char=char)
    name = getattr(key, "name", "") or ""
    if name == "space":
        return _ShimEvent(keysym="space", char=" ")
    if name in _PYNPUT_KEY_NAMES:
        return _ShimEvent(keysym=_PYNPUT_KEY_NAMES[name], char="")
    # Alle übrigen Sondertasten (enter, tab, backspace, pfeile, …) beenden
    # einen Tipplauf, da sie kein druckbares Zeichen liefern.
    return _ShimEvent(keysym=name or "special", char="")


class KeystrokeMonitor:
    """Liest die Tastatur systemweit mit und meldet fertige Live-Proben.

    Speichert ausschließlich Zeitabstände. Fehlt ``pynput`` (oder fehlen die
    nötigen Rechte), bleibt der Monitor inaktiv und ``start`` liefert ``False``;
    die Anwendung läuft dann ohne zweiten Faktor weiter.
    """

    def __init__(self, config: KeystrokeConfig,
                 on_sample: Callable[[Dict[str, object]], None],
                 logger_obj: Optional[logging.Logger] = None):
        self.config = config
        self.on_sample = on_sample
        self.logger = logger_obj or logger
        self._recorder = KeystrokeRecorder(
            max_dwell_ms=config.max_dwell_ms,
            max_flight_ms=config.max_flight_ms,
        )
        self._listener = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @staticmethod
    def is_supported() -> bool:
        try:
            import pynput  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> bool:
        if not self.config.enabled or not self.config.global_capture:
            return False
        if self._running:
            return True
        try:
            from pynput import keyboard
        except Exception as exc:  # pynput fehlt -> sauber degradieren.
            self.logger.warning(
                "Tippmuster-Monitor inaktiv: pynput nicht verfügbar (%s)", exc)
            return False
        try:
            self._recorder.reset()
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release)
            self._listener.daemon = True
            self._listener.start()
            self._running = True
            self.logger.info("Tippmuster-Monitor gestartet (systemweit)")
            return True
        except Exception as exc:
            self.logger.error("Tippmuster-Monitor konnte nicht starten: %s", exc)
            self._listener = None
            self._running = False
            return False

    def stop(self) -> None:
        self._running = False
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._recorder.reset()

    # -- pynput-Callbacks (laufen in eigenem Thread) ----------------------
    def _on_press(self, key) -> None:
        try:
            self._recorder.on_press(_adapt_pynput_key(key))
        except Exception:
            pass

    def _on_release(self, key) -> None:
        try:
            self._recorder.on_release(_adapt_pynput_key(key))
            if self._recorder.sample_size >= self.config.match_window_keystrokes:
                sample = self._recorder.take_sample(self.config.match_window_keystrokes)
                if sample is not None:
                    self.on_sample(sample)
        except Exception:
            pass

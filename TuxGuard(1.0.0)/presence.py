#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mehrfaktor-Präsenzbewertung für die Dauerüberwachung von TuxGuard.

Fasst die beiden Überwachungsfaktoren **Gesichtserkennung** und
**Tippmustererkennung** zu einer Präsenzentscheidung zusammen. Sowohl die
*Priorität/Fusion* der Faktoren als auch die *Reaktion bei Verlust* eines
Faktors sind über die Konfiguration einstellbar.

Faktorzustände:

* Gesicht: ``True`` (erkannt) / ``False`` (nicht erkannt).
* Tippmuster: ``"match"`` (passender Rhythmus), ``"intruder"`` (fremder
  Rhythmus), ``"idle"`` (gerade keine Eingabe – neutral) oder ``"disabled"``.

Das Ergebnis (`PresenceDecision`) sagt der Überwachungsschleife,

* ob ein legitimer Nutzer als anwesend gilt (`keep_alive` – setzt die
  Sperr-/Totmann-Timer zurück),
* ob sofort eine Aktion nötig ist (`immediate_action`, z. B. fremdes
  Tippmuster), und
* welcher Faktor ggf. verloren ging (`lost_factor`) – damit die konfigurierte
  Verlust-Aktion angewandt werden kann.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Faktorzustände Tippmuster
KS_MATCH = "match"
KS_INTRUDER = "intruder"
KS_IDLE = "idle"
KS_DISABLED = "disabled"

# Fusionsstrategien
FUSION_FACE_ONLY = "face_only"
FUSION_KEYSTROKE_ONLY = "keystroke_only"
FUSION_ANY = "any"
FUSION_ALL = "all"
FUSION_PRIORITY = "priority"
_VALID_FUSION = {
    FUSION_FACE_ONLY, FUSION_KEYSTROKE_ONLY, FUSION_ANY, FUSION_ALL, FUSION_PRIORITY,
}

# Mögliche Reaktionen bei Verlust eines Faktors
ACTION_LOCK = "lock"
ACTION_WARN = "warn"
ACTION_IGNORE = "ignore"
ACTION_DEADMAN = "deadman"
_VALID_ACTIONS = {ACTION_LOCK, ACTION_WARN, ACTION_IGNORE, ACTION_DEADMAN}

FACTOR_FACE = "face"
FACTOR_KEYSTROKE = "keystroke"


@dataclass
class PresenceConfig:
    """Einstellbare Fusions- und Reaktionsparameter."""

    keystroke_enabled: bool = True
    fusion_mode: str = FUSION_PRIORITY
    primary_factor: str = FACTOR_FACE
    on_face_lost: str = ACTION_LOCK
    on_keystroke_intruder: str = ACTION_LOCK
    on_keystroke_lost: str = ACTION_IGNORE

    def __post_init__(self):
        if self.fusion_mode not in _VALID_FUSION:
            self.fusion_mode = FUSION_PRIORITY
        if self.primary_factor not in (FACTOR_FACE, FACTOR_KEYSTROKE):
            self.primary_factor = FACTOR_FACE
        if self.on_face_lost not in _VALID_ACTIONS:
            self.on_face_lost = ACTION_LOCK
        if self.on_keystroke_intruder not in _VALID_ACTIONS:
            self.on_keystroke_intruder = ACTION_LOCK
        if self.on_keystroke_lost not in _VALID_ACTIONS:
            self.on_keystroke_lost = ACTION_IGNORE

    @classmethod
    def from_app_config(cls, config) -> "PresenceConfig":
        g = lambda name, default: getattr(config, name, default)  # noqa: E731
        return cls(
            keystroke_enabled=bool(g("KEYSTROKE_DYNAMICS_ENABLED", True)),
            fusion_mode=str(g("PRESENCE_FUSION_MODE", FUSION_PRIORITY)).lower(),
            primary_factor=str(g("PRESENCE_PRIMARY_FACTOR", FACTOR_FACE)).lower(),
            on_face_lost=str(g("PRESENCE_ON_FACE_LOST", ACTION_LOCK)).lower(),
            on_keystroke_intruder=str(g("PRESENCE_ON_KEYSTROKE_INTRUDER", ACTION_LOCK)).lower(),
            on_keystroke_lost=str(g("PRESENCE_ON_KEYSTROKE_LOST", ACTION_IGNORE)).lower(),
        )


@dataclass
class PresenceDecision:
    """Ergebnis der Präsenzbewertung."""

    keep_alive: bool
    immediate_action: Optional[str]
    lost_factor: Optional[str]
    reason: str


def evaluate_presence(
    face_present: bool,
    keystroke_state: str,
    cfg: PresenceConfig,
) -> PresenceDecision:
    """Bewertet die aktuelle Präsenz aus Gesichts- und Tippmustersignal."""
    ks = keystroke_state if cfg.keystroke_enabled else KS_DISABLED
    ks_active = ks != KS_DISABLED
    ks_match = ks == KS_MATCH
    ks_intruder = ks == KS_INTRUDER

    # Fremdes Tippmuster ist immer ein sofortiges Eindringling-Signal.
    if ks_active and ks_intruder:
        return PresenceDecision(
            keep_alive=False,
            immediate_action=cfg.on_keystroke_intruder,
            lost_factor=FACTOR_KEYSTROKE,
            reason="Fremdes Tippmuster erkannt",
        )

    # Ohne aktiven Tippmuster-Faktor entscheidet allein das Gesicht.
    if not ks_active:
        return _face_only_decision(face_present, cfg)

    mode = cfg.fusion_mode
    if mode == FUSION_FACE_ONLY:
        keep = face_present
    elif mode == FUSION_KEYSTROKE_ONLY:
        # Präsent, solange kein fremder Rhythmus auftritt (idle = neutral).
        keep = ks_match or ks == KS_IDLE
    elif mode == FUSION_ANY:
        keep = face_present or ks_match
    elif mode == FUSION_ALL:
        # Streng: Gesicht nötig; idle erlaubt, fremder Rhythmus bereits oben.
        keep = face_present and (ks_match or ks == KS_IDLE)
    elif mode == FUSION_PRIORITY:
        if cfg.primary_factor == FACTOR_KEYSTROKE:
            # Tippmuster primär; Gesicht trägt nur, wenn nicht getippt wird.
            keep = ks_match or (ks == KS_IDLE and face_present)
        else:
            # Gesicht primär; Tippmuster hält als Rückfall die Sitzung offen.
            keep = face_present or ks_match
    else:
        keep = face_present

    if keep:
        return PresenceDecision(True, None, None, "")

    # Nicht präsent: Ursache bestimmen, um die passende Aktion zu wählen.
    if mode == FUSION_KEYSTROKE_ONLY:
        lost = FACTOR_KEYSTROKE
        action = cfg.on_keystroke_lost
    else:
        lost = FACTOR_FACE
        action = cfg.on_face_lost
    return PresenceDecision(False, None, lost, f"Faktor verloren: {lost}")


def _face_only_decision(face_present: bool, cfg: PresenceConfig) -> PresenceDecision:
    if face_present:
        return PresenceDecision(True, None, None, "")
    return PresenceDecision(False, None, FACTOR_FACE, "Gesicht nicht erkannt")

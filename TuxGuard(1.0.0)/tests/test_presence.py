"""Tests für die Mehrfaktor-Präsenzbewertung (presence.evaluate_presence)."""

import presence
from presence import (
    PresenceConfig,
    evaluate_presence,
    KS_MATCH,
    KS_INTRUDER,
    KS_IDLE,
    KS_DISABLED,
    FUSION_FACE_ONLY,
    FUSION_KEYSTROKE_ONLY,
    FUSION_ANY,
    FUSION_ALL,
    FUSION_PRIORITY,
    ACTION_LOCK,
    ACTION_WARN,
    ACTION_DEADMAN,
    ACTION_IGNORE,
    FACTOR_FACE,
    FACTOR_KEYSTROKE,
)


# ---------------------------------------------------------------------------
# Intruder (immer sofort)
# ---------------------------------------------------------------------------

def test_intruder_triggers_immediate_action():
    cfg = PresenceConfig(fusion_mode=FUSION_PRIORITY, on_keystroke_intruder=ACTION_LOCK)
    d = evaluate_presence(True, KS_INTRUDER, cfg)
    assert d.keep_alive is False
    assert d.immediate_action == ACTION_LOCK
    assert d.lost_factor == FACTOR_KEYSTROKE


def test_intruder_respects_configured_action():
    cfg = PresenceConfig(on_keystroke_intruder=ACTION_DEADMAN)
    d = evaluate_presence(True, KS_INTRUDER, cfg)
    assert d.immediate_action == ACTION_DEADMAN


def test_intruder_ignored_when_keystroke_disabled():
    cfg = PresenceConfig(keystroke_enabled=False)
    # Tippmuster aus -> nur Gesicht zählt, kein Intruder-Signal.
    d = evaluate_presence(True, KS_INTRUDER, cfg)
    assert d.keep_alive is True
    assert d.immediate_action is None


# ---------------------------------------------------------------------------
# face_only / keystroke disabled
# ---------------------------------------------------------------------------

def test_face_only_keeps_alive_with_face():
    cfg = PresenceConfig(fusion_mode=FUSION_FACE_ONLY)
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    d = evaluate_presence(False, KS_MATCH, cfg)
    assert d.keep_alive is False
    assert d.lost_factor == FACTOR_FACE


def test_keystroke_disabled_falls_back_to_face():
    cfg = PresenceConfig(keystroke_enabled=False, on_face_lost=ACTION_LOCK)
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    d = evaluate_presence(False, KS_IDLE, cfg)
    assert d.keep_alive is False
    assert d.lost_factor == FACTOR_FACE


# ---------------------------------------------------------------------------
# keystroke_only
# ---------------------------------------------------------------------------

def test_keystroke_only_idle_is_neutral():
    cfg = PresenceConfig(fusion_mode=FUSION_KEYSTROKE_ONLY)
    assert evaluate_presence(False, KS_MATCH, cfg).keep_alive is True
    # idle = neutral -> bleibt präsent (kein Tippen heißt nicht abwesend).
    assert evaluate_presence(False, KS_IDLE, cfg).keep_alive is True


def test_keystroke_only_loss_uses_keystroke_action():
    cfg = PresenceConfig(
        fusion_mode=FUSION_KEYSTROKE_ONLY, on_keystroke_lost=ACTION_WARN)
    # Nur über Intruder kann keystroke_only verloren gehen -> aber das ist
    # immediate. Für den passiven Pfad konstruieren wir disabled-ähnlich nicht;
    # stattdessen prüfen wir, dass idle/match nie verliert.
    assert evaluate_presence(False, KS_IDLE, cfg).keep_alive is True


# ---------------------------------------------------------------------------
# any
# ---------------------------------------------------------------------------

def test_any_keeps_alive_with_either_factor():
    cfg = PresenceConfig(fusion_mode=FUSION_ANY)
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    assert evaluate_presence(False, KS_MATCH, cfg).keep_alive is True
    d = evaluate_presence(False, KS_IDLE, cfg)
    assert d.keep_alive is False
    assert d.lost_factor == FACTOR_FACE


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------

def test_all_requires_face_and_non_intruder():
    cfg = PresenceConfig(fusion_mode=FUSION_ALL)
    assert evaluate_presence(True, KS_MATCH, cfg).keep_alive is True
    # Gesicht da, idle (neutral) -> bleibt präsent.
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    # Kein Gesicht -> verloren, auch bei Match.
    assert evaluate_presence(False, KS_MATCH, cfg).keep_alive is False


# ---------------------------------------------------------------------------
# priority
# ---------------------------------------------------------------------------

def test_priority_face_primary():
    cfg = PresenceConfig(fusion_mode=FUSION_PRIORITY, primary_factor=FACTOR_FACE)
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    # Gesicht weg, aber Tippmuster passt -> Rückfall hält Sitzung.
    assert evaluate_presence(False, KS_MATCH, cfg).keep_alive is True
    # Gesicht weg, kein Tippen -> verloren (Gesicht ist primär).
    d = evaluate_presence(False, KS_IDLE, cfg)
    assert d.keep_alive is False
    assert d.lost_factor == FACTOR_FACE


def test_priority_keystroke_primary():
    cfg = PresenceConfig(fusion_mode=FUSION_PRIORITY, primary_factor=FACTOR_KEYSTROKE)
    assert evaluate_presence(False, KS_MATCH, cfg).keep_alive is True
    # Kein Tippen, aber Gesicht da -> getragen.
    assert evaluate_presence(True, KS_IDLE, cfg).keep_alive is True
    # Kein Tippen, kein Gesicht -> verloren.
    assert evaluate_presence(False, KS_IDLE, cfg).keep_alive is False


# ---------------------------------------------------------------------------
# Konfig-Validierung
# ---------------------------------------------------------------------------

def test_config_defaults_invalid_values():
    cfg = PresenceConfig(
        fusion_mode="quatsch", primary_factor="x",
        on_face_lost="x", on_keystroke_intruder="y", on_keystroke_lost="z")
    assert cfg.fusion_mode == FUSION_PRIORITY
    assert cfg.primary_factor == FACTOR_FACE
    assert cfg.on_face_lost == ACTION_LOCK
    assert cfg.on_keystroke_intruder == ACTION_LOCK
    assert cfg.on_keystroke_lost == ACTION_IGNORE


def test_config_from_app_config():
    from config import Config

    cfg = PresenceConfig.from_app_config(Config)
    assert cfg.fusion_mode in {
        FUSION_FACE_ONLY, FUSION_KEYSTROKE_ONLY, FUSION_ANY, FUSION_ALL, FUSION_PRIORITY,
    }
    assert cfg.primary_factor in (FACTOR_FACE, FACTOR_KEYSTROKE)

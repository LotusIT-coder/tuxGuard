#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Mouse Monitoring Module
Wrapper für Mausüberwachung mit vereinfachter API
"""

import threading
import time
import logging
from typing import Optional, Callable, Dict

import numpy as np

from config import Config
from mouse_movement_recognition import collect_data as recognition_collect_data, preprocess_data as recognition_preprocess_data

logger = logging.getLogger('TuxGuard.MouseMonitor')

# Globale Variablen für Überwachung
_monitor_thread: Optional[threading.Thread] = None
_monitor_active = False
_pattern_model = None
_unauthorized_callback: Optional[Callable[[], None]] = None


def _ensure_keras():
    """Stellt sicher, dass TensorFlow/Keras verfügbar ist."""
    try:
        from tensorflow import keras  # type: ignore
        return keras
    except ImportError as exc:
        logger.error("TensorFlow/Keras konnte nicht importiert werden: %s", exc)
        raise RuntimeError(
            "TensorFlow/Keras wird für Mausmuster-Training benötigt. "
            "Bitte installieren Sie die Abhängigkeiten mit 'pip install tensorflow'."
        ) from exc

def load_pattern_model(force_reload: bool = False):
    """Lädt das Mustererkennungsmodell von der Festplatte."""
    global _pattern_model

    if force_reload:
        _pattern_model = None

    if _pattern_model is not None:
        return _pattern_model

    if not Config.MOUSE_PATTERN_MODEL.exists():
        logger.warning("Kein Mustererkennungsmodell gefunden")
        return None

    try:
        keras = _ensure_keras()
        _pattern_model = keras.models.load_model(str(Config.MOUSE_PATTERN_MODEL))
        logger.info("Mustererkennungsmodell geladen: %s", Config.MOUSE_PATTERN_MODEL)
        return _pattern_model
    except Exception as exc:
        logger.error("Fehler beim Laden des Mustererkennungsmodells: %s", exc, exc_info=True)
        _pattern_model = None
        return None

def verify_mouse_pattern(duration: int = 5) -> bool:
    """Verifiziert Mausbewegungsmuster anhand des trainierten Modells."""
    global _pattern_model

    try:
        if _pattern_model is None:
            _pattern_model = load_pattern_model()

        if _pattern_model is None:
            logger.warning("Kein Mustererkennungsmodell geladen - Zugriff wird erlaubt")
            return True

        logger.info("Musterverifikation für %ss gestartet", duration)
        print("[TuxGuard] Bitte bewegen Sie die Maus während der Verifikation!")
        raw_data = recognition_collect_data(duration)
        if raw_data is None or len(raw_data) == 0:
            logger.warning("Keine Mausdaten für die Verifikation erfasst - Zugriff wird erlaubt")
            return True

        features = recognition_preprocess_data(raw_data)
        if features is None or len(features) == 0:
            logger.warning("Keine gültigen Features für Musterverifikation - Zugriff wird erlaubt")
            return True

        inputs = np.asarray(features, dtype=np.float32)
        predictions = _pattern_model.predict(inputs, verbose=0)
        confidence = float(np.mean(predictions))
        is_authorized = confidence >= Config.MOUSE_VERIFICATION_THRESHOLD

        logger.info(
            "Musterverifikation abgeschlossen: %s (Konfidenz: %.2f, Schwelle: %.2f)",
            "Autorisiert" if is_authorized else "Nicht autorisiert",
            confidence,
            Config.MOUSE_VERIFICATION_THRESHOLD,
        )

        return is_authorized

    except Exception as exc:
        logger.error("Fehler bei Musterverifikation: %s", exc, exc_info=True)
        return True  # Im Fehlerfall Zugriff erlauben

def _monitor_loop():
    """Hauptschleife für Mausüberwachung"""
    global _monitor_active, _unauthorized_callback
    
    logger.info("Mausüberwachung gestartet")
    
    while _monitor_active:
        try:
            # Warte zwischen Überprüfungen
            time.sleep(Config.MOUSE_MONITOR_INTERVAL)
            
            if _monitor_active:  # Prüfe nochmal ob noch aktiv
                # Führe Musterverifikation durch
                is_authorized = verify_mouse_pattern(duration=3)
                
                if not is_authorized:
                    logger.warning("Mausmuster-Verifikation fehlgeschlagen!")
                    
                    # Rufe Callback auf, falls registriert
                    if _unauthorized_callback:
                        try:
                            _unauthorized_callback()
                        except Exception as cb_error:
                            logger.error(f"Fehler in unauthorized_callback: {cb_error}")
                
        except Exception as e:
            logger.error(f"Fehler in Mausüberwachung: {e}")
            time.sleep(1)  # Kurze Pause bei Fehlern
    
    logger.info("Mausüberwachung beendet")

def set_mouse_monitoring_callback(callback: Optional[Callable[[], None]]):
    """Setzt den Callback für fehlgeschlagene Musterverifikation"""
    global _unauthorized_callback
    _unauthorized_callback = callback
    logger.info("Mouse monitoring unauthorized callback registriert")

def start_mouse_monitoring():
    """Startet die Mausüberwachung"""
    global _monitor_thread, _monitor_active
    
    if _monitor_active:
        logger.warning("Mausüberwachung läuft bereits")
        return
    
    _monitor_active = True
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="MouseMonitor"
    )
    _monitor_thread.start()
    
    logger.info("Mausüberwachung gestartet")

def stop_mouse_monitoring():
    """Stoppt die Mausüberwachung"""
    global _monitor_active, _monitor_thread
    
    if not _monitor_active:
        logger.warning("Mausüberwachung läuft nicht")
        return
    
    _monitor_active = False
    
    if _monitor_thread and _monitor_thread.is_alive():
        try:
            _monitor_thread.join(timeout=2.0)
        except Exception as e:
            logger.error(f"Fehler beim Beenden der Mausüberwachung: {e}")
    
    logger.info("Mausüberwachung gestoppt")

def is_monitoring_active() -> bool:
    """Gibt zurück ob die Überwachung aktiv ist"""
    return _monitor_active


def train_mouse_pattern(
    duration: Optional[int] = None,
    epochs: Optional[int] = None,
    batch_size: Optional[int] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
    progress_callback: Optional[Callable[[int, int, Dict[str, float]], None]] = None,
) -> Dict[str, object]:
    """Trainiert das Mausmuster-Modell anhand neu erfasster Daten."""

    keras = _ensure_keras()

    duration = duration or Config.MOUSE_TRAINING_DURATION
    epochs = epochs or Config.MOUSE_TRAINING_EPOCHS
    batch_size = batch_size or Config.MOUSE_TRAINING_BATCH_SIZE

    if log_callback:
        log_callback(f"Sammle Mausdaten für {duration} Sekunden...", "INFO")

    raw_data = recognition_collect_data(duration)
    if raw_data is None or len(raw_data) == 0:
        raise RuntimeError("Es konnten keine Mausdaten erfasst werden.")

    if log_callback:
        log_callback(f"{len(raw_data)} Mausereignisse erfasst", "INFO")

    features = recognition_preprocess_data(raw_data)
    if features is None or len(features) == 0:
        raise RuntimeError("Die erfassten Mausdaten konnten nicht verarbeitet werden.")

    inputs = np.asarray(features, dtype=np.float32)
    sample_count = inputs.shape[0]

    if sample_count < Config.MOUSE_MIN_TRAINING_SAMPLES:
        raise RuntimeError(
            f"Zu wenig Trainingsdaten: {sample_count}/{Config.MOUSE_MIN_TRAINING_SAMPLES}. "
            "Bitte bewegen Sie die Maus während der Aufzeichnung stärker."
        )

    targets = np.ones((sample_count, 1), dtype=np.float32)

    model = keras.Sequential([
        keras.layers.Input(shape=(inputs.shape[1],)),
        keras.layers.Dense(128, activation='relu'),
        keras.layers.Dropout(0.2),
        keras.layers.Dense(64, activation='relu'),
        keras.layers.Dense(1, activation='sigmoid'),
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

    class _ProgressCallback(keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            if progress_callback:
                progress_callback(epoch + 1, epochs, logs or {})

    callbacks = [_ProgressCallback()]

    if log_callback:
        log_callback("Starte Training des Mausmuster-Modells...", "INFO")

    history = model.fit(
        inputs,
        targets,
        epochs=epochs,
        batch_size=min(batch_size, sample_count),
        verbose=0,
        callbacks=callbacks,
    )

    Config.ensure_directories()
    model.save(str(Config.MOUSE_PATTERN_MODEL), overwrite=True)

    global _pattern_model
    _pattern_model = model

    logger.info(
        "Training abgeschlossen: %s (Samples=%s, Features=%s)",
        Config.MOUSE_PATTERN_MODEL,
        sample_count,
        inputs.shape[1],
    )

    if log_callback:
        log_callback(
            f"Training abgeschlossen. Modell gespeichert in {Config.MOUSE_PATTERN_MODEL}",
            "SUCCESS",
        )

    return {
        "history": history.history,
        "samples": sample_count,
        "feature_dim": inputs.shape[1],
        "model_path": str(Config.MOUSE_PATTERN_MODEL),
    }

# Legacy-Funktionen für Kompatibilität mit dem alten Modul
def collect_data(duration: int = 10):
    """Legacy-Funktion für Datensammlung"""
    logger.info(f"Sammle Mausdaten für {duration} Sekunden")
    # Simuliere Datensammlung
    time.sleep(min(duration, 1))  # Maximal 1 Sekunde für Demo
    return [[100, 100, time.time(), 0, 0]]  # Dummy-Daten

def preprocess_data(data):
    """Legacy-Funktion für Datenvorverarbeitung"""
    logger.debug(f"Verarbeite {len(data)} Datenpunkte")
    # Simuliere Verarbeitung
    return [[0.1, 0.2, 0.3, 0.4, 0.5]]  # Dummy-Features

def build_model(input_shape):
    """Legacy-Funktion für Modellerstellung"""
    logger.info(f"Erstelle Modell mit Input-Shape: {input_shape}")
    return "dummy_model"  # Dummy-Modell
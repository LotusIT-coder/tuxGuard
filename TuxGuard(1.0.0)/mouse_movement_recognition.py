#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Mouse Movement Recognition Module
Mausbewegungsmustererkennung mit maschinellem Lernen
"""

import tensorflow as tf
from keras import models
from keras import layers
from pynput.mouse import Listener
import numpy as np
import time
import logging
import os
from pathlib import Path
from typing import List, Tuple, Optional
from config import Config

# Logger
logger = logging.getLogger('TuxGuard.MousePattern')

# Globale Variablen
mouse_data = []
recording = True
model = None

# Kontinuierliches Lernen
training_buffer = []  # Puffer für neue Trainingsdaten
BUFFER_MAX_SIZE = 1000  # Maximale Größe des Trainingspuffers
CONFIDENCE_THRESHOLD = 0.98  # Schwellenwert für neue Trainingsdaten
MIN_TRAINING_SAMPLES = 100  # Mindestanzahl von Samples für inkrementelles Training

def on_move(x, y):
    """Callback-Funktion für Mausbewegungen."""
    if recording:
        try:
            timestamp = time.time()
            mouse_data.append([x, y, timestamp, 0, 0])  # Bewegung: dx=0, dy=0
            logger.debug(f"Mausbewegung erfasst: x={x}, y={y}")
        except Exception as e:
            logger.error(f"Fehler bei der Erfassung der Mausbewegung: {str(e)}", exc_info=True)

def on_click(x, y, button, pressed):
    """Callback-Funktion für Mausklicks."""
    if recording:
        try:
            timestamp = time.time()
            click_flag = 1 if pressed else 0
            mouse_data.append([x, y, timestamp, click_flag, 0])  # Klick: dx=0
            logger.debug(f"Mausklick erfasst: x={x}, y={y}, Button={button}, Pressed={pressed}")
        except Exception as e:
            logger.error(f"Fehler bei der Erfassung des Mausklicks: {str(e)}", exc_info=True)

def on_scroll(x, y, dx, dy):
    """Callback-Funktion für Scrollen."""
    if recording:
        try:
            timestamp = time.time()
            mouse_data.append([x, y, timestamp, 0, dy])  # Scrollen: dy=Scrollbewegung
            logger.debug(f"Scrolling erfasst: x={x}, y={y}, dy={dy}")
        except Exception as e:
            logger.error(f"Fehler bei der Erfassung des Scrollens: {str(e)}", exc_info=True)

def collect_data(duration=10):
    """Sammelt Mausbewegungen für eine bestimmte Dauer."""
    global mouse_data, recording
    mouse_data = []
    recording = True
    with Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll) as listener:
        print(f"Erfassung der Mausbewegungen für {duration} Sekunden gestartet...")
        time.sleep(duration)
        recording = False
        listener.stop()
    print("Erfassung beendet.")
    return np.array(mouse_data)

def preprocess_data(data):
    """Hochentwickelte Vorverarbeitung der Daten mit erweiterter Feature-Extraktion und Verhaltensanalyse."""
    logger.debug(f"Starte erweiterte Datenvorverarbeitung mit {len(data)} Datenpunkten")
    
    def calculate_gesture_features(positions, velocities):
        """Berechnet erweiterte Gesten-Features aus Positionsdaten."""
        gestures = []
        min_gesture_length = 5
        
        # Fensterbasierte Gestenanalyse
        for i in range(0, len(positions) - min_gesture_length):
            window = positions[i:i + min_gesture_length]
            velocity_window = velocities[i:i + min_gesture_length]
            
            # Berechne Gestenkomplexität
            path_length = np.sum(np.sqrt(np.sum(np.diff(window, axis=0) ** 2, axis=1)))
            direct_distance = np.sqrt(np.sum((window[-1] - window[0]) ** 2))
            complexity = path_length / (direct_distance + 1e-6)
            
            # Geschwindigkeitsprofil
            velocity_profile = np.gradient(np.linalg.norm(velocity_window, axis=1))
            
            gestures.append({
                'complexity': complexity,
                'smoothness': 1.0 / (1.0 + np.std(velocity_profile)),
                'efficiency': direct_distance / (path_length + 1e-6),
                'peak_velocity': np.max(np.linalg.norm(velocity_window, axis=1))
            })
        
        if gestures:
            # Berechne Durchschnittswerte manuell
            avg_gestures = {}
            for key in ['complexity', 'smoothness', 'efficiency', 'peak_velocity']:
                avg_gestures[key] = np.mean([g[key] for g in gestures])
            return avg_gestures
        else:
            return {'complexity': 0, 'smoothness': 0, 'efficiency': 0, 'peak_velocity': 0}
    
    if len(data) < 10:  # Erhöhte Mindestanzahl für bessere Statistik
        logger.error("Zu wenig Datenpunkte für aussagekräftige Verarbeitung")
        raise ValueError("Mindestens 10 Datenpunkte erforderlich für zuverlässige Analyse.")
    
    try:
        # Extrahiere und konvertiere Basisdaten mit Fehlerprüfung
        try:
            positions = data[:, :2].astype(np.float32)
            timestamps = data[:, 2].astype(np.float64)
            clicks = data[:, 3].astype(np.float32)
            scrolls = data[:, 4].astype(np.float32)
        except (IndexError, ValueError) as e:
            logger.error(f"Fehler bei der Datenextraktion: {str(e)}")
            raise ValueError("Ungültiges Datenformat")

        # Validiere Daten
        if np.any(np.isnan(positions)) or np.any(np.isinf(positions)):
            logger.error("Ungültige Positionswerte gefunden")
            raise ValueError("Ungültige Positionswerte")

        if np.any(np.isnan(timestamps)) or np.any(np.isinf(timestamps)):
            logger.error("Ungültige Zeitstempel gefunden")
            raise ValueError("Ungültige Zeitstempel")

        if np.any(np.diff(timestamps) <= 0):
            logger.warning("Nicht monotone Zeitstempel erkannt – korrigiere Reihenfolge mit kleinem Offset")
            corrected = timestamps.copy()
            epsilon = 1e-4
            for idx in range(1, len(corrected)):
                if corrected[idx] <= corrected[idx - 1]:
                    corrected[idx] = corrected[idx - 1] + epsilon
            if np.any(np.diff(corrected) <= 0):
                logger.error("Zeitstempel konnten nicht korrigiert werden")
                raise ValueError("Zeitstempel ungültig")
            timestamps = corrected
        timestamps = timestamps.astype(np.float32)

        logger.debug("Basisdaten erfolgreich extrahiert und validiert")

        # Basis-Features
        time_diffs = np.diff(timestamps, prepend=timestamps[0])
        # Verhindere Division durch Null
        time_diffs[time_diffs == 0] = 1e-6
        logger.debug(f"Zeitdifferenzen berechnet: Min={time_diffs.min():.6f}s, Max={time_diffs.max():.6f}s")

        # Geschwindigkeiten berechnen
        velocities = np.diff(positions, axis=0, prepend=positions[0].reshape(1, -1)) / time_diffs.reshape(-1, 1)
        logger.debug("Geschwindigkeiten berechnet")

        # Beschleunigungen berechnen
        accelerations = np.diff(velocities, axis=0, prepend=velocities[0].reshape(1, -1)) / time_diffs.reshape(-1, 1)
        logger.debug("Beschleunigungen berechnet")
        
        # Erweiterte Bewegungsanalyse
        # Bewegungsrichtungen (Winkel) mit verbesserter Genauigkeit
        directions = np.arctan2(velocities[:, 1], velocities[:, 0])
        direction_changes = np.diff(directions, prepend=directions[0])
        smooth_directions = np.convolve(directions, np.ones(5)/5, mode='valid')  # Geglättete Richtungen
        direction_stability = 1.0 / (1.0 + np.std(direction_changes))  # Stabilitätsmetrik
        logger.debug(f"Bewegungsrichtungen analysiert: Stabilität={direction_stability:.4f}")
        
        # Detaillierte Pausenanalyse
        movement_threshold = 2.0  # Pixel
        velocity_magnitudes = np.sqrt(np.sum(velocities**2, axis=1))
        significant_movements = velocity_magnitudes > movement_threshold
        pause_times = np.where(significant_movements, 0, time_diffs)
        
        # Zusätzliche Pausenmetriken
        pause_durations = pause_times[pause_times > 0]
        avg_pause_duration = np.mean(pause_durations) if len(pause_durations) > 0 else 0
        pause_frequency = len(pause_durations) / len(time_diffs)
        logger.debug(f"Pausenanalyse: Anzahl={len(pause_durations)}, Durchschnitt={avg_pause_duration:.3f}s, Frequenz={pause_frequency:.3f}")
        
        # Erweiterte Klickmusteranalyse
        click_intervals = np.zeros_like(clicks)
        click_positions = []
        last_click_time = 0
        click_count = 0
        double_click_count = 0
        click_drag_count = 0
        
        for i in range(len(clicks)):
            if clicks[i] == 1:
                current_time = timestamps[i]
                interval = current_time - last_click_time
                click_intervals[i] = interval
                
                # Speichere Klickposition
                click_positions.append([positions[i, 0], positions[i, 1]])
                
                # Erkenne Doppelklicks (Intervall < 0.5s)
                if 0 < interval < 0.5:
                    double_click_count += 1
                
                # Erkenne Klick-und-Ziehen (Bewegung während Klick)
                if i > 0 and i < len(clicks) - 1:
                    movement_during_click = np.sqrt(np.sum((positions[i+1] - positions[i-1])**2))
                    if movement_during_click > 5.0:  # Schwellenwert für Bewegung
                        click_drag_count += 1
                
                last_click_time = current_time
                click_count += 1
        
        # Klickverhalten-Metriken
        duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0
        if duration <= 0:
            click_density = 0
        else:
            click_density = click_count / duration
        click_positions = np.array(click_positions) if click_positions else np.array([[0, 0]])
        click_spread = np.std(click_positions, axis=0) if len(click_positions) > 1 else np.array([0, 0])
        
        logger.debug(f"Erweiterte Klickanalyse: Gesamt={click_count}, Doppelklicks={double_click_count}, "
                    f"Ziehen={click_drag_count}, Dichte={click_density:.3f}/s, "
                    f"Streuung=[{click_spread[0]:.1f}, {click_spread[1]:.1f}]")
        
        # Erweiterte Feature-Normalisierung mit Robustheit gegen Ausreißer
        def robust_normalize(x, clip_threshold=3):
            try:
                if len(x.shape) == 1:
                    x = x.reshape(-1, 1)
                    
                # Entferne extreme Ausreißer
                means = np.mean(x, axis=0)
                stds = np.std(x, axis=0)
                x_clipped = np.clip(x, means - clip_threshold * stds, means + clip_threshold * stds)
                
                # Robuste Normalisierung mit Berücksichtigung der Verteilung
                if np.any(stds != 0):
                    x_norm = (x_clipped - means) / (stds + 1e-6)
                    # Zusätzliche Sigmoid-Transformation für bessere Verteilung
                    return 2 / (1 + np.exp(-x_norm)) - 1
                return x_clipped - means
                
            except Exception as e:
                logger.error(f"Fehler bei der robusten Normalisierung: {str(e)}")
                raise
        
        # Erweiterte Feature-Extraktion und Zusammenführung
        feature_arrays = [
            robust_normalize(positions),                    # x, y Position (2)
            robust_normalize(velocities),                   # vx, vy Geschwindigkeit (2)
            robust_normalize(accelerations),                # ax, ay Beschleunigung (2)
            robust_normalize(directions.reshape(-1, 1)),    # Bewegungsrichtung (1)
            robust_normalize(smooth_directions.reshape(-1, 1)),  # Geglättete Richtung (1)
            robust_normalize(direction_changes.reshape(-1, 1)),  # Richtungsänderung (1)
            robust_normalize(pause_times.reshape(-1, 1)),   # Pausenzeiten (1)
            robust_normalize(velocity_magnitudes.reshape(-1, 1)),  # Geschwindigkeitsmagnitude (1)
            robust_normalize(click_intervals.reshape(-1, 1)), # Klickintervalle (1)
            clicks.reshape(-1, 1),                         # Klick-Events (1)
            scrolls.reshape(-1, 1),                        # Scroll-Events (1)
            np.full((len(positions), 1), click_density),   # Klickdichte (1)
            np.full((len(positions), 1), direction_stability),  # Richtungsstabilität (1)
            np.full((len(positions), 1), pause_frequency), # Pausenfrequenz (1)
        ]

        # Ermittle die minimale Länge aller Feature-Arrays
        min_len = min(arr.shape[0] for arr in feature_arrays)
        if min_len < 1:
            raise ValueError("Zu wenig Daten nach Feature-Schnitt")
        # Schneide alle Arrays auf die gleiche Länge
        feature_arrays = [arr[:min_len] for arr in feature_arrays]
        features = np.column_stack(feature_arrays)

        logger.info(f"Feature-Extraktion abgeschlossen: {features.shape[1]} Features für {features.shape[0]} Datenpunkte")
        return features
        
    except Exception as e:
        logger.error(f"Fehler bei der Datenvorverarbeitung: {str(e)}", exc_info=True)
        raise

def build_model(input_shape):
    """Erstellt ein hochentwickeltes neuronales Netzwerk mit Multi-Head Attention und Residual Connections."""
    # Input Layer
    inputs = layers.Input(shape=input_shape)
    
    # Initial Feature Extraction
    x = layers.Dense(256, activation='selu')(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.2)(x)
    
    # Multi-Stream Feature Processing
    # Stream 1: Temporale Features mit verbesserter Sequenzverarbeitung
    temporal = layers.Reshape((-1, 256))(x)  # Reshape for sequence processing
    temporal = layers.LayerNormalization()(temporal)
    temporal = layers.Bidirectional(layers.LSTM(128, return_sequences=True))(temporal)
    temporal = layers.Dropout(0.2)(temporal)
    
    # Stream 2: Spatiale Features mit verbesserte Merkmalserkennung
    spatial = layers.Dense(128, activation='selu')(x)
    spatial = layers.LayerNormalization()(spatial)
    spatial = layers.Reshape((-1, 128))(spatial)
    
    # Stream 3: Sequential Pattern Features mit Muster-Fokus
    pattern = layers.Dense(128, activation='relu')(x)
    pattern = layers.LayerNormalization()(pattern)
    pattern = layers.Reshape((-1, 128))(pattern)
    
    # Verbesserte Multi-Head Attention für jeden Stream
    attention_dim = 32  # Reduzierte Dimension für fokussiertere Attention
    temporal = layers.MultiHeadAttention(
        num_heads=8, 
        key_dim=attention_dim,
        attention_axes=(1,)
    )(temporal, temporal, temporal)
    spatial = layers.MultiHeadAttention(
        num_heads=8,
        key_dim=attention_dim,
        attention_axes=(1,)
    )(spatial, spatial, spatial)
    pattern = layers.MultiHeadAttention(
        num_heads=8,
        key_dim=attention_dim,
        attention_axes=(1,)
    )(pattern, pattern, pattern)
    
    # Verbesserte Feature Fusion mit Cross-Attention
    temporal_flat = layers.Flatten()(temporal)
    spatial_flat = layers.Flatten()(spatial)
    pattern_flat = layers.Flatten()(pattern)
    
    # Adaptive Feature Fusion
    fusion_dim = 256
    temporal_proj = layers.Dense(fusion_dim, activation='selu')(temporal_flat)
    spatial_proj = layers.Dense(fusion_dim, activation='selu')(spatial_flat)
    pattern_proj = layers.Dense(fusion_dim, activation='selu')(pattern_flat)
    
    # Cross-Stream Attention
    fusion_attention = layers.MultiHeadAttention(
        num_heads=4,
        key_dim=64
    )(
        layers.Reshape((-1, fusion_dim))(temporal_proj),
        layers.Reshape((-1, fusion_dim))(spatial_proj)
    )
    
    # Enhanced Feature Combination
    merged = layers.Concatenate()([
        layers.Flatten()(fusion_attention),
        pattern_proj
    ])
    
    # Progressive Feature Refinement mit verbesserten Residual Connections
    residual = merged
    for units in [512, 256, 128]:
        x = layers.Dense(units, activation='selu')(residual)
        x = layers.LayerNormalization()(x)
        x = layers.Dropout(0.2)(x)
        # Gewichtete Residual Connection
        x = layers.Dense(units, activation='linear')(x)
        if x.shape[-1] == residual.shape[-1]:
            scale = layers.Dense(units, activation='sigmoid')(residual)
            x = layers.Add()([layers.Multiply()([scale, x]), 
                            layers.Multiply()([1-scale, residual])])
        residual = x
        
    # Enhanced Classification Layers
    x = layers.Dense(128, activation='selu')(x)
    x = layers.LayerNormalization()(x)
    x = layers.Dropout(0.15)(x)
    
    # Pattern Detection Head
    pattern_features = layers.Dense(64, activation='selu')(x)
    pattern_features = layers.LayerNormalization()(pattern_features)
    
    # Dual-Head Output mit Uncertainty Estimation
    confidence = layers.Dense(1, activation='sigmoid', name='confidence')(pattern_features)
    pattern_logits = layers.Dense(3, name='pattern_logits')(pattern_features)
    pattern_type = layers.Activation('softmax', name='pattern_type')(pattern_logits)
    
    # Model Definition mit verbesserten Outputs
    model = models.Model(inputs=inputs, outputs=[confidence, pattern_type])
    
    # Optimierter Training Setup
    optimizer = tf.keras.optimizers.AdamW(
        learning_rate=1e-4,
        weight_decay=1e-5,
        beta_1=0.9,
        beta_2=0.999,
        epsilon=1e-7,
        amsgrad=True
    )
    
    # Custom Loss für bessere Präzision
    def combined_loss(y_true, y_pred):
        confidence_loss = tf.keras.losses.binary_crossentropy(y_true[0], y_pred[0])
        pattern_loss = tf.keras.losses.categorical_crossentropy(y_true[1], y_pred[1])
        return confidence_loss + 0.3 * pattern_loss
    
    model.compile(
        optimizer=optimizer,
        loss=combined_loss,
        metrics={
            'confidence': ['accuracy', tf.keras.metrics.Precision(), tf.keras.metrics.Recall()],
            'pattern_type': 'categorical_accuracy'
        }
    )
    
    return model

def update_training_buffer(features, confidence):
    """Aktualisiert den Trainingspuffer mit neuen Daten hoher Konfidenz."""
    global training_buffer
    
    logger.debug(f"Prüfe neue Daten für Training (Konfidenz: {confidence:.4f})")
    
    # Nur Daten mit hoher Konfidenz zum Training verwenden
    if confidence > CONFIDENCE_THRESHOLD:
        try:
            # Füge neue Features zum Puffer hinzu
            prev_size = len(training_buffer)
            training_buffer.extend(features.tolist())
            new_size = len(training_buffer)
            
            logger.info(f"Neue Trainingsdaten hinzugefügt: {new_size - prev_size} Datenpunkte")
            
            # Begrenze die Puffergröße
            if len(training_buffer) > BUFFER_MAX_SIZE:
                # Behalte die neuesten Daten
                removed_count = len(training_buffer) - BUFFER_MAX_SIZE
                training_buffer = training_buffer[-BUFFER_MAX_SIZE:]
                logger.debug(f"Buffer begrenzt: {removed_count} alte Datenpunkte entfernt")
                
            logger.debug(f"Aktueller Buffer-Status: {len(training_buffer)}/{BUFFER_MAX_SIZE} Datenpunkte")
            
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren des Trainingspuffers: {str(e)}", exc_info=True)
    else:
        logger.debug(f"Daten ignoriert - Konfidenz {confidence:.4f} unter Schwellenwert {CONFIDENCE_THRESHOLD}")

def incremental_training():
    """Führt inkrementelles Training mit gesammelten Daten durch."""
    global model, training_buffer
    
    logger.debug("Prüfe Voraussetzungen für inkrementelles Training")
    
    if len(training_buffer) < MIN_TRAINING_SAMPLES:
        logger.info(f"Zu wenig Trainingsdaten: {len(training_buffer)}/{MIN_TRAINING_SAMPLES}")
        return False
    try:
        # Konvertiere Buffer zu numpy array
        training_data = np.array(training_buffer)
        logger.debug(f"Trainingsdaten vorbereitet: Shape={training_data.shape}")
        
        # Erstelle Labels (alle positiv, da aus erfolgreichem Training)
        labels = np.ones(len(training_data))
        
        logger.info(f"Starte inkrementelles Training mit {len(training_data)} Samples")

        # Führe eine Trainingsepoche durch
        start_time = time.time()
        history = model.fit(
            training_data, 
            labels,
            epochs=1,
            batch_size=32,
            verbose=0
        )
        training_time = time.time() - start_time

        # Extrahiere Metriken
        loss = history.history['loss'][0]
        
        # Detailliertes Logging der Trainingsergebnisse
        logger.info(f"Inkrementelles Training abgeschlossen:"
                   f"\n\tTrainingszeit: {training_time:.2f}s"
                   f"\n\tLoss: {loss:.4f}")

        # Leere den Buffer nach erfolgreichem Training
        buffer_size = len(training_buffer)
        training_buffer = []
        logger.debug(f"Training-Buffer geleert ({buffer_size} Samples entfernt)")

        return True
        
    except Exception as e:
        logger.error("Fehler beim inkrementellen Training", exc_info=True)
        logger.error(f"Details zum Fehler: {str(e)}")
        return False

def real_time_classification():
    """Führt eine hochpräzise Echtzeit-Klassifikation mit adaptivem Lernen und erweiterter Musteranalyse durch."""
    global mouse_data, model, training_buffer
    logger.info("Starte erweiterte Echtzeit-Klassifikation mit adaptivem Lernen und Musteranalyse")
    
    # Erweiterte Konfigurationskonstanten für die Klassifikation
    CONFIG = {
        'WINDOW_SIZE': 75,            # Vergrößerte Fenstergröße für stabilere Analyse
        'MIN_SAMPLES': 20,            # Erhöhte Mindestanzahl Samples für bessere Statistik
        'BASE_THRESHOLD': 0.92,       # Angepasster Basis-Schwellenwert für höhere Sensitivität
        'ADAPTIVE_THRESHOLD': True,   # Aktiviere adaptive Schwellenwerte
        'STABILITY_WEIGHT': 0.35,     # Erhöhte Gewichtung der Stabilität
        'HISTORY_SIZE': 15,           # Vergrößerter Verlaufspuffer für bessere Trendanalyse
        'ANOMALY_THRESHOLD': 1.8,     # Verfeinerter Schwellenwert für Anomalieerkennung
        'TEMPORAL_WINDOW': 5,         # Fenster für zeitliche Kohärenzanalyse
        'MIN_PATTERN_LENGTH': 8,      # Minimale Länge für Mustererkennung
        'VELOCITY_THRESHOLD': 1000,   # Schwellenwert für Geschwindigkeitsanalyse
        'PAUSE_THRESHOLD': 0.2,       # Schwellenwert für Pausenerkennung
        'SMOOTHING_FACTOR': 0.15      # Faktor für Signalglättung
    }
    
    if model is None:
        logger.error("Kein Modell geladen - Klassifikation nicht möglich")
        raise RuntimeError("Modell nicht initialisiert")
    
    # Initialisiere Zustandsvariablen
    prediction_buffer = []  # Puffer für Vorhersagen
    confidence_history = [] # Verlauf der Konfidenzwerte
    anomaly_count = 0      # Zähler für anomale Muster
    last_thresholds = []   # Verlauf der adaptiven Schwellenwerte
    
    # Hilfsfunktionen für die adaptive Klassifikation
    def calculate_adaptive_threshold(confidence_history):
        """Berechnet adaptiven Schwellenwert basierend auf historischen Daten."""
        if len(confidence_history) < 3:
            return CONFIG['BASE_THRESHOLD']
        
        mean_confidence = np.mean(confidence_history)
        std_confidence = np.std(confidence_history)
        
        # Adaptiver Schwellenwert basierend auf Verteilung
        adaptive_threshold = mean_confidence - CONFIG['ANOMALY_THRESHOLD'] * std_confidence
        
        # Begrenzen Sie den Schwellenwert auf sinnvolle Werte
        return max(min(adaptive_threshold, 0.99), 0.80)
    
    def detect_anomaly(prediction, confidence_history):
        """Erkennt anomale Muster basierend auf historischen Daten."""
        if len(confidence_history) < 5:
            return False
            
        mean_conf = np.mean(confidence_history)
        std_conf = np.std(confidence_history)
        z_score = (prediction - mean_conf) / (std_conf + 1e-6)
        
        return abs(z_score) > CONFIG['ANOMALY_THRESHOLD']
    
    with Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll) as listener:
        while True:
            time.sleep(0.1)  # Noch häufigere Überprüfung (10x pro Sekunde)
            
            if len(mouse_data) >= CONFIG['MIN_SAMPLES']:
                # Verwende nur die letzten Datenpunkte
                recent_data = np.array(mouse_data[-CONFIG['WINDOW_SIZE']:])
                
                try:
                    # Erweiterte Feature-Extraktion
                    features = preprocess_data(recent_data)
                    
                    # Qualitätsprüfung der Features
                    if features is None or np.any(np.isnan(features)) or np.any(np.isinf(features)):
                        logger.warning("Ungültige Features erkannt - überspringe Analyse")
                        continue
                    
                    # Verbesserte Vorhersage mit Ensemble-Ansatz
                    predictions = model.predict(features, verbose=0)
                    
                    # Berechne erweiterte Metriken
                    mean_confidence = predictions.mean()
                    min_confidence = predictions.min()
                    max_confidence = predictions.max()
                    prediction_stability = 1.0 - predictions.std()
                    
                    # Aktualisiere Konfidenz-Verlauf
                    confidence_history.append(mean_confidence)
                    if len(confidence_history) > CONFIG['HISTORY_SIZE']:
                        confidence_history.pop(0)
                    
                    # Berechne adaptiven Schwellenwert
                    current_threshold = calculate_adaptive_threshold(confidence_history)
                    last_thresholds.append(current_threshold)
                    if len(last_thresholds) > CONFIG['HISTORY_SIZE']:
                        last_thresholds.pop(0)
                    
                    # Erweiterte Anomalieerkennung
                    is_anomaly = detect_anomaly(mean_confidence, confidence_history)
                    if is_anomaly:
                        anomaly_count += 1
                    else:
                        anomaly_count = max(0, anomaly_count - 1)
                    
                    # Füge Vorhersage zum Puffer hinzu
                    prediction_buffer.append({
                        'confidence': mean_confidence,
                        'stability': prediction_stability,
                        'threshold': current_threshold,
                        'is_anomaly': is_anomaly
                    })
                    if len(prediction_buffer) > CONFIG['HISTORY_SIZE']:
                        prediction_buffer.pop(0)
                    
                    # Berechne gewichtete Vertrauenswürdigkeit
                    weighted_confidence = (
                        mean_confidence * (1 - CONFIG['STABILITY_WEIGHT']) +
                        prediction_stability * CONFIG['STABILITY_WEIGHT']
                    )
                    
                    # Adaptive Autorisierungsentscheidung
                    is_authorized = (
                        weighted_confidence > current_threshold and
                        min_confidence > 0.3 and
                        prediction_stability > 0.7 and
                        anomaly_count < 3
                    )
                    
                    # Detailliertes Logging der erweiterten Entscheidungsfindung
                    logger.debug(f"Erweiterte Autorisierungskriterien:"
                               f"\n\tGewichtete Konfidenz: {weighted_confidence:.4f}"
                               f"\n\tAktueller Schwellenwert: {current_threshold:.4f}"
                               f"\n\tMinimale Konfidenz: {min_confidence:.4f}"
                               f"\n\tStabilität: {prediction_stability:.4f}"
                               f"\n\tAnomalien: {anomaly_count}")
                    
                    # Adaptives Lernen mit Qualitätskontrolle
                    if is_authorized:
                        logger.info("Nutzer autorisiert - Starte adaptives Lernen")
                        
                        # Aktualisiere den Trainingspuffer nur mit hochwertigen Daten
                        if prediction_stability > 0.8 and not is_anomaly:
                            update_training_buffer(features, weighted_confidence)
                            logger.debug("Hochwertige Trainingsdaten hinzugefügt")
                        
                        # Führe inkrementelles Training durch
                        if len(training_buffer) >= MIN_TRAINING_SAMPLES:
                            training_success = incremental_training()
                            training_status = "✓" if training_success else "⨯"
                            logger.info(f"Adaptives Training durchgeführt: {'Erfolgreich' if training_success else 'Fehlgeschlagen'}")
                        else:
                            training_status = f"({len(training_buffer)}/{MIN_TRAINING_SAMPLES})"
                            logger.debug(f"Sammle weitere Trainingsdaten: {training_status}")
                    else:
                        logger.warning(
                            f"Nicht autorisierter Zugriff erkannt:"
                            f"\n\tGewichtete Konfidenz: {weighted_confidence:.4f}"
                            f"\n\tSchwellenwert: {current_threshold:.4f}"
                            f"\n\tStabilität: {prediction_stability:.4f}"
                            f"\n\tAnomalien: {anomaly_count}"
                        )
                        training_status = "-"
                    
                    status = "Autorisiert" if is_authorized else "Nicht autorisiert"
                    confidence = f"{weighted_confidence:.2%}"
                    
                    logger.info(f"Status: {status} (Konfidenz: {confidence}, "
                              f"Stabilität: {prediction_stability:.2f}, Training: {training_status})")
                    
                    # Ausgabe für Benutzer
                    print(f"Status: {status} (Konfidenz: {confidence}, "
                          f"Stabilität: {prediction_stability:.2f}, Training: {training_status})")
                    
                except Exception as e:
                    print(f"Fehler bei der Klassifikation: {str(e)}")
                    continue
                
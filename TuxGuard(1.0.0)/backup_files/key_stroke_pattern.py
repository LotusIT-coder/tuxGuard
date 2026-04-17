import logging
import numpy as np
import tensorflow as tf
from keras import layers, models
from pynput import keyboard
import time
from scipy.stats import skew, kurtosis
import os

# Logging-Konfiguration
logger = logging.getLogger('TuxGuard.KeyPattern')

# Globale Variablen
keystroke_data = []
recording = False
model = None
reference_text = "Der schnelle braune Fuchs springt über den faulen Hund. 123"
current_text = ""
start_time = None
key_timings = []

class KeyStrokePattern:
    def __init__(self):
        self.model = self.build_model()
        self.training_data = []
        self.CONFIDENCE_THRESHOLD = 0.95

    def on_press(self, key):
        """Callback für Tastendruck"""
        global current_text, start_time, key_timings
        
        if not recording:
            return

        try:
            if start_time is None:
                start_time = time.time()

            timestamp = time.time()
            
            # Verarbeite normale Tasten und Sondertasten
            if hasattr(key, 'char'):
                char = key.char
            else:
                char = str(key)

            key_timings.append({
                'key': char,
                'timestamp': timestamp,
                'event_type': 'press'
            })

            # Aktualisiere den eingegebenen Text
            if hasattr(key, 'char') and key.char is not None:
                current_text += key.char
            elif key == keyboard.Key.space:
                current_text += ' '
            elif key == keyboard.Key.backspace and len(current_text) > 0:
                current_text = current_text[:-1]

            # Überprüfe, ob genügend Text eingegeben wurde
            if len(current_text) >= len(reference_text):
                return False  # Stoppt den Listener

        except Exception as e:
            logger.error(f"Fehler bei der Tastenverarbeitung: {str(e)}", exc_info=True)

    def on_release(self, key):
        """Callback für Tastenloslassen"""
        if not recording:
            return

        try:
            timestamp = time.time()
            
            if hasattr(key, 'char'):
                char = key.char
            else:
                char = str(key)

            key_timings.append({
                'key': char,
                'timestamp': timestamp,
                'event_type': 'release'
            })

        except Exception as e:
            logger.error(f"Fehler bei der Tastenverarbeitung: {str(e)}", exc_info=True)

    def extract_features(self, timings):
        """Extrahiert Features aus den Tastenanschlag-Timings"""
        features = []
        
        # Gruppiere Press/Release Events
        key_pairs = []
        press_events = {}
        
        for event in timings:
            if event['event_type'] == 'press':
                press_events[event['key']] = event['timestamp']
            elif event['event_type'] == 'release' and event['key'] in press_events:
                key_pairs.append({
                    'key': event['key'],
                    'press_time': press_events[event['key']],
                    'release_time': event['timestamp']
                })
                del press_events[event['key']]

        # Berechne Features
        if len(key_pairs) < 2:
            return None

        # 1. Haltezeiten (Dwell Time)
        hold_times = [pair['release_time'] - pair['press_time'] for pair in key_pairs]
        
        # 2. Flugzeiten (Flight Time)
        flight_times = []
        for i in range(len(key_pairs) - 1):
            flight_time = key_pairs[i + 1]['press_time'] - key_pairs[i]['release_time']
            flight_times.append(flight_time)

        # 3. Statistische Features
        features.extend([
            np.mean(hold_times),
            np.std(hold_times),
            skew(hold_times),
            kurtosis(hold_times),
            np.mean(flight_times),
            np.std(flight_times),
            skew(flight_times),
            kurtosis(flight_times)
        ])

        # 4. Rhythmus-Features
        digraph_times = []
        for i in range(len(key_pairs) - 1):
            digraph_time = key_pairs[i + 1]['press_time'] - key_pairs[i]['press_time']
            digraph_times.append(digraph_time)

        features.extend([
            np.mean(digraph_times),
            np.std(digraph_times),
            np.percentile(digraph_times, 25),
            np.percentile(digraph_times, 75)
        ])

        # 5. Geschwindigkeits-Features
        char_per_second = len(key_pairs) / (key_pairs[-1]['release_time'] - key_pairs[0]['press_time'])
        features.append(char_per_second)

        return np.array(features)

    def build_model(self):
        """Erstellt das neuronale Netzwerk für die Tastenanschlagmustererkennung"""
        input_dim = 13  # Anzahl der Features
        
        model = models.Sequential([
            layers.Dense(64, activation='relu', input_shape=(input_dim,)),
            layers.BatchNormalization(),
            layers.Dropout(0.3),
            
            layers.Dense(32, activation='relu'),
            layers.BatchNormalization(),
            layers.Dropout(0.2),
            
            layers.Dense(16, activation='relu'),
            layers.BatchNormalization(),
            
            layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss='binary_crossentropy',
            metrics=['accuracy']
        )
        
        return model

    def collect_typing_sample(self):
        """Sammelt eine Typing-Probe"""
        global recording, current_text, start_time, key_timings
        
        recording = True
        current_text = ""
        start_time = None
        key_timings = []
        
        print(f"\nBitte geben Sie folgenden Text ein:\n{reference_text}\n")
        
        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()
        
        recording = False
        features = self.extract_features(key_timings)
        
        return features

    def train_model(self, user_samples, other_samples):
        """Trainiert das Modell mit den gesammelten Proben"""
        X = np.vstack([user_samples, other_samples])
        y = np.hstack([np.ones(len(user_samples)), np.zeros(len(other_samples))])
        
        # Shuffle the data
        indices = np.arange(len(X))
        np.random.shuffle(indices)
        X = X[indices]
        y = y[indices]
        
        # Train the model
        history = self.model.fit(
            X, y,
            epochs=50,
            batch_size=32,
            validation_split=0.2,
            verbose=0
        )
        
        return history

    def verify_user(self, sample):
        """Überprüft, ob die Probe zum bekannten Benutzermuster passt"""
        if sample is None:
            return False, 0.0
            
        prediction = self.model.predict(sample.reshape(1, -1), verbose=0)[0][0]
        is_user = prediction > self.CONFIDENCE_THRESHOLD
        
        return is_user, prediction

    def save_model(self, path):
        """Speichert das trainierte Modell"""
        self.model.save(path)

    def load_model(self, path):
        """Lädt ein trainiertes Modell"""
        self.model = models.load_model(path)

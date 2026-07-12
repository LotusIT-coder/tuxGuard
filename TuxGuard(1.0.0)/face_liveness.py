#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liveness- und Anti-Spoofing-Modul für TuxGuard.

Ziel: Verhindern, dass die Kameraerkennung mit einem 2D-Foto (Ausdruck oder
Bildschirm) überlistet wird. Ein einzelnes gespeichertes 3D-Landmark-Modell
reicht dafür nicht aus, da MediaPipe auch aus einem flachen Foto ein 3D-Mesh
fittet. Stattdessen kombiniert dieses Modul mehrere unabhängige Signale:

1. **3D-Referenzgeometrie** (``GeometryModel``)
   Aggregiertes 3D-Landmark-Modell pro Nutzer (aus den hochgeladenen Bildern).
   Dient als *Konsistenz-Check* der Identität (Procrustes/Kabsch-Abgleich),
   nicht als alleiniger Spoof-Schutz.

2. **Passive Textur-/Moiré-Analyse** (``texture_live_score``)
   Einzelbild-Heuristik: Detailgehalt (Laplace-Varianz), Hochfrequenz-/
   Moiré-Energie (FFT) und Farbsättigung. Papierausdrucke und Bildschirme
   weichen hier typischerweise von echter Haut ab.

3. **Temporale Liveness** (``LivenessMonitor``)
   Über mehrere Frames: Blinzeln (eyeBlink-Blendshapes), Kopfbewegung
   (Pose aus der 4×4-Transformationsmatrix) und Bewegungs-Parallaxe
   (Nasen-Offset korreliert bei echten Gesichtern mit der Kopfdrehung,
   bei einem starren Foto nicht).

4. **Aktive Challenge** (optional)
   Fordert den Nutzer auf, zu blinzeln oder den Kopf zu drehen, und
   verifiziert die Reaktion innerhalb eines Zeitfensters.

Alle Schwellwerte sind heuristisch und über ``LivenessConfig`` einstellbar.
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger("TuxGuard.Liveness")

# Landmark-Indizes (MediaPipe FaceLandmarker, 478 Punkte).
_LEFT_EYE_OUTER = 33
_RIGHT_EYE_OUTER = 263
_NOSE_TIP = 1
# Stabile Anker zur kanonischen 3D-Normalisierung (Augen, Nase, Mundwinkel,
# Kinn, Stirn, Nasenwurzel).
_ANCHOR_INDICES = (33, 263, 1, 61, 291, 152, 10, 168)


# ===========================================================================
# 3D-Referenzgeometrie
# ===========================================================================

def _normalize_geometry(xyz: np.ndarray) -> Optional[np.ndarray]:
    """Zentriert auf den Schwerpunkt und skaliert auf Einheits-RMS-Radius.

    Macht die Geometrie translations- und skaleninvariant. Die Rotation
    wird erst beim Vergleich (Kabsch) ausgeglichen.
    """
    if xyz is None or xyz.ndim != 2 or xyz.shape[0] < 4 or xyz.shape[1] != 3:
        return None
    centered = xyz - xyz.mean(axis=0, keepdims=True)
    scale = float(np.sqrt((centered ** 2).sum() / centered.shape[0]))
    if scale < 1e-9:
        return None
    return centered / scale


def _kabsch_align(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotiert ``source`` optimal auf ``target`` (beide zentriert/skaliert)."""
    h = source.T @ target
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    correction = np.diag([1.0, 1.0, d])
    rotation = vt.T @ correction @ u.T
    return source @ rotation.T


def geometry_rms_distance(model: np.ndarray, live: np.ndarray) -> float:
    """RMS-Restabstand zwischen Referenzmodell und Live-Geometrie.

    Beide werden normalisiert und per Kabsch rotationsbereinigt. Ein
    kleiner Wert bedeutet hohe geometrische Übereinstimmung. ``inf`` bei
    ungültigen Eingaben.
    """
    norm_model = _normalize_geometry(model)
    norm_live = _normalize_geometry(live)
    if norm_model is None or norm_live is None:
        return float("inf")
    if norm_model.shape != norm_live.shape:
        return float("inf")
    aligned = _kabsch_align(norm_live, norm_model)
    diff = aligned - norm_model
    return float(np.sqrt((diff ** 2).sum() / diff.shape[0]))


def aggregate_geometries(geometries: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    """Mittelt mehrere 3D-Geometrien zu einem Referenzmodell.

    Die erste gültige Geometrie dient als Referenzrahmen; alle weiteren
    werden per Kabsch darauf ausgerichtet und gemittelt.
    """
    normalized: List[np.ndarray] = []
    reference: Optional[np.ndarray] = None
    for geom in geometries:
        norm = _normalize_geometry(np.asarray(geom, dtype=np.float64))
        if norm is None:
            continue
        if reference is None:
            reference = norm
            normalized.append(norm)
        elif norm.shape == reference.shape:
            normalized.append(_kabsch_align(norm, reference))
    if not normalized:
        return None
    return np.mean(np.stack(normalized, axis=0), axis=0).astype(np.float64)


def combine_geometry_models(
    existing_model: Optional[np.ndarray],
    existing_n: int,
    new_model: Optional[np.ndarray],
    new_n: int,
) -> Tuple[Optional[np.ndarray], int]:
    """Verschmilzt ein bestehendes Referenzmodell mit einem neuen Aggregat.

    Beide Modelle sind bereits gemittelte Aggregate. Das neue wird per Kabsch
    auf das bestehende ausgerichtet und gewichtet (nach Sample-Anzahl)
    gemittelt. Liefert (kombiniertes_modell, gesamt_samples).
    """
    norm_existing = _normalize_geometry(existing_model) if existing_model is not None else None
    norm_new = _normalize_geometry(new_model) if new_model is not None else None
    if norm_existing is None:
        return (norm_new, int(new_n)) if norm_new is not None else (None, 0)
    if norm_new is None:
        return norm_existing, int(existing_n)
    if norm_existing.shape != norm_new.shape:
        # Inkompatible Punktzahl (z. B. Cascade-Reste) – neues Modell bevorzugen.
        return norm_new, int(new_n)
    aligned_new = _kabsch_align(norm_new, norm_existing)
    total = max(1, int(existing_n) + int(new_n))
    combined = (norm_existing * int(existing_n) + aligned_new * int(new_n)) / total
    return combined.astype(np.float64), total


def serialize_geometry(xyz: np.ndarray) -> bytes:
    """Serialisiert eine Geometrie ``(N, 3)`` kompakt als float32-Bytes."""
    arr = np.ascontiguousarray(np.asarray(xyz, dtype=np.float32))
    return arr.tobytes()


def deserialize_geometry(blob: bytes) -> Optional[np.ndarray]:
    """Deserialisiert float32-Bytes zurück in ein ``(N, 3)``-Array."""
    if not blob:
        return None
    try:
        flat = np.frombuffer(blob, dtype=np.float32)
        if flat.size == 0 or flat.size % 3 != 0:
            return None
        return flat.reshape(-1, 3).astype(np.float64)
    except Exception:  # pylint: disable=broad-except
        return None


# ===========================================================================
# Passive Textur-/Moiré-Analyse (Einzelbild)
# ===========================================================================

def _crop_face(rgb_image: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
    top, right, bottom, left = bbox
    h, w = rgb_image.shape[:2]
    top = max(0, min(int(top), h))
    bottom = max(0, min(int(bottom), h))
    left = max(0, min(int(left), w))
    right = max(0, min(int(right), w))
    if bottom - top < 24 or right - left < 24:
        return None
    return rgb_image[top:bottom, left:right]


def texture_live_score(
    rgb_image: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> float:
    """Heuristische Echtheits-Wahrscheinlichkeit eines Gesichts-Crops [0..1].

    Höher = eher echtes Gesicht. Kombiniert drei Indizien:
      * Detailgehalt (Laplace-Varianz) – sehr glatte oder sehr unruhige
        Crops sind verdächtig.
      * Moiré-/Hochfrequenz-Energie (FFT) – Bildschirme erzeugen
        auffällige Hochfrequenz-Spitzen.
      * Farbsättigung – Ausdrucke/Screens weichen oft von Hauttönen ab.

    Heuristik, kein Garant – als ein Signal unter mehreren gedacht.
    """
    crop = _crop_face(rgb_image, bbox)
    if crop is None:
        return 0.5  # unbestimmt

    try:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    except Exception:  # pylint: disable=broad-except
        return 0.5
    gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)

    # 1) Detailgehalt: zu wenig Detail => Foto unscharf/glatt; sehr viel
    #    Detail bei feinem Raster => evtl. Druckraster/Moiré.
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    detail_score = float(np.clip((lap_var - 15.0) / 120.0, 0.0, 1.0))

    # 2) Moiré / Hochfrequenz: Anteil der Energie im hohen Frequenzband.
    f = np.fft.fftshift(np.fft.fft2(gray.astype(np.float32)))
    mag = np.abs(f)
    cy, cx = mag.shape[0] // 2, mag.shape[1] // 2
    yy, xx = np.ogrid[: mag.shape[0], : mag.shape[1]]
    radius = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    high = float(mag[radius > 0.35 * mag.shape[0] / 2].sum())
    total = float(mag.sum()) + 1e-8
    high_ratio = high / total
    # Sehr hoher HF-Anteil deutet auf Raster/Moiré (Bildschirm/Druck) hin.
    moire_score = float(np.clip(1.0 - (high_ratio - 0.18) / 0.22, 0.0, 1.0))

    # 3) Farbsättigung: echte Haut hat moderate, nicht extreme Sättigung.
    try:
        hsv = cv2.cvtColor(cv2.resize(crop, (128, 128)), cv2.COLOR_RGB2HSV)
        sat = float(hsv[:, :, 1].mean()) / 255.0
    except Exception:  # pylint: disable=broad-except
        sat = 0.3
    sat_score = float(np.clip(1.0 - abs(sat - 0.35) / 0.45, 0.0, 1.0))

    score = 0.45 * detail_score + 0.35 * moire_score + 0.20 * sat_score
    return float(np.clip(score, 0.0, 1.0))


# ===========================================================================
# Kopf-Pose aus Transformationsmatrix
# ===========================================================================

def head_pose_angles(transform: Optional[np.ndarray]) -> Optional[Tuple[float, float, float]]:
    """Liefert (yaw, pitch, roll) in Grad aus der 4×4-Transformationsmatrix."""
    if transform is None:
        return None
    try:
        r = np.asarray(transform, dtype=np.float64)[:3, :3]
        sy = math.sqrt(r[0, 0] ** 2 + r[1, 0] ** 2)
        if sy > 1e-6:
            pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
            yaw = math.degrees(math.atan2(-r[2, 0], sy))
            roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
        else:
            pitch = math.degrees(math.atan2(-r[1, 2], r[1, 1]))
            yaw = math.degrees(math.atan2(-r[2, 0], sy))
            roll = 0.0
        return (yaw, pitch, roll)
    except Exception:  # pylint: disable=broad-except
        return None


def _normalized_nose_offset(landmarks3d: Optional[np.ndarray]) -> Optional[float]:
    """Horizontaler Nasen-Offset relativ zur Augenmitte, auf Augenabstand normiert.

    Bei einem echten 3D-Gesicht verschiebt sich dieser Wert mit der
    Kopfdrehung (Parallaxe). Bei einem flachen Foto bleibt er nahezu
    konstant, egal wie das Foto bewegt/gedreht wird.
    """
    if landmarks3d is None or landmarks3d.shape[0] <= max(_ANCHOR_INDICES):
        return None
    left_eye = landmarks3d[_LEFT_EYE_OUTER]
    right_eye = landmarks3d[_RIGHT_EYE_OUTER]
    nose = landmarks3d[_NOSE_TIP]
    eye_center_x = (left_eye[0] + right_eye[0]) / 2.0
    inter_ocular = float(abs(right_eye[0] - left_eye[0]))
    if inter_ocular < 1e-6:
        return None
    return float((nose[0] - eye_center_x) / inter_ocular)


# ===========================================================================
# Konfiguration & Ergebnis
# ===========================================================================

@dataclass
class LivenessConfig:
    """Einstellbare Schwellwerte für die Liveness-Prüfung."""

    enabled: bool = True
    # Passive Textur
    texture_min_score: float = 0.45
    # Blinzeln
    blink_close_threshold: float = 0.45
    blink_open_threshold: float = 0.20
    require_blink: bool = True
    blink_window_seconds: float = 8.0
    # Bewegungs-Parallaxe
    require_parallax: bool = True
    parallax_min_yaw_range: float = 8.0    # Grad Kopfdrehung nötig für Aussage
    parallax_min_slope: float = 0.004      # Nasen-Offset-Änderung pro Grad Yaw
    motion_window_seconds: float = 6.0
    # 3D-Geometrie-Konsistenz
    geometry_max_rms: float = 0.18
    geometry_required: bool = False
    # Aktive Challenge
    active_challenge_enabled: bool = True
    challenge_timeout_seconds: float = 12.0
    challenge_turn_yaw_degrees: float = 15.0


@dataclass
class LivenessResult:
    """Ergebnis der Liveness-Prüfung für einen Frame."""

    is_live: bool = False
    score: float = 0.0
    texture_score: float = 0.5
    blink_ok: bool = False
    parallax_ok: bool = False
    geometry_ok: bool = True
    challenge_active: bool = False
    challenge_prompt: Optional[str] = None
    reasons: List[str] = field(default_factory=list)


# ===========================================================================
# Temporaler Liveness-Monitor (ein Subjekt)
# ===========================================================================

class LivenessMonitor:
    """Zustandsbehafteter Liveness-Prüfer für das aktuell überwachte Gesicht.

    Pro Frame wird ``update`` mit den Merkmalen des erkannten Gesichts
    aufgerufen. Der Monitor sammelt Blinzel-Ereignisse, Kopfbewegung und
    Parallaxe über ein gleitendes Zeitfenster und kann optional eine aktive
    Challenge fahren.
    """

    def __init__(self, config: Optional[LivenessConfig] = None):
        self.config = config or LivenessConfig()
        self._eye_closed = False
        self._blink_times: List[float] = []
        self._motion_samples: List[Tuple[float, float, float]] = []  # (t, yaw, nose_offset)
        # Aktive Challenge
        self._challenge_kind: Optional[str] = None
        self._challenge_started_at: Optional[float] = None
        self._challenge_baseline_blinks = 0
        self._challenge_passed_at: Optional[float] = None

    # -- Reset ------------------------------------------------------------
    def reset(self) -> None:
        self._eye_closed = False
        self._blink_times.clear()
        self._motion_samples.clear()
        self._challenge_kind = None
        self._challenge_started_at = None
        self._challenge_passed_at = None

    # -- Blinzeln ---------------------------------------------------------
    def _update_blink(self, blendshapes: Dict[str, float], now: float) -> None:
        left = float(blendshapes.get("eyeBlinkLeft", 0.0))
        right = float(blendshapes.get("eyeBlinkRight", 0.0))
        closure = max(left, right)
        if not self._eye_closed and closure >= self.config.blink_close_threshold:
            self._eye_closed = True
        elif self._eye_closed and closure <= self.config.blink_open_threshold:
            self._eye_closed = False
            self._blink_times.append(now)
        # Fenster beschneiden
        cutoff = now - self.config.blink_window_seconds
        self._blink_times = [t for t in self._blink_times if t >= cutoff]

    def _blink_ok(self) -> bool:
        if not self.config.require_blink:
            return True
        return len(self._blink_times) >= 1

    # -- Parallaxe / Bewegung --------------------------------------------
    def _update_motion(
        self,
        yaw: Optional[float],
        nose_offset: Optional[float],
        now: float,
    ) -> None:
        if yaw is None or nose_offset is None:
            return
        self._motion_samples.append((now, yaw, nose_offset))
        cutoff = now - self.config.motion_window_seconds
        self._motion_samples = [s for s in self._motion_samples if s[0] >= cutoff]

    def _parallax_ok(self) -> Tuple[bool, bool]:
        """Liefert (parallax_bestätigt, aussagekräftig).

        ``aussagekräftig`` ist False, solange der Kopf nicht genug gedreht
        wurde – dann kann noch keine Parallaxe-Aussage getroffen werden.
        """
        if not self.config.require_parallax:
            return True, True
        if len(self._motion_samples) < 5:
            return False, False
        yaws = np.array([s[1] for s in self._motion_samples], dtype=np.float64)
        offsets = np.array([s[2] for s in self._motion_samples], dtype=np.float64)
        yaw_range = float(yaws.max() - yaws.min())
        if yaw_range < self.config.parallax_min_yaw_range:
            return False, False  # noch nicht genug Bewegung
        # Steigung des Nasen-Offsets über Yaw via robuster Regression.
        try:
            slope = float(np.polyfit(yaws, offsets, 1)[0])
        except Exception:  # pylint: disable=broad-except
            return False, True
        return (abs(slope) >= self.config.parallax_min_slope), True

    # -- Aktive Challenge -------------------------------------------------
    def start_challenge(self) -> None:
        """Startet eine zufällige aktive Challenge (Blinzeln oder Kopfdrehung)."""
        if not self.config.active_challenge_enabled:
            return
        self._challenge_kind = random.choice(["blink", "turn_left", "turn_right"])
        self._challenge_started_at = time.time()
        self._challenge_baseline_blinks = len(self._blink_times)
        self._challenge_passed_at = None

    def _challenge_prompt(self) -> Optional[str]:
        return {
            "blink": "Bitte einmal blinzeln",
            "turn_left": "Bitte Kopf leicht nach links drehen",
            "turn_right": "Bitte Kopf leicht nach rechts drehen",
        }.get(self._challenge_kind or "")

    def _update_challenge(self, yaw: Optional[float], now: float) -> Tuple[bool, Optional[str]]:
        """Verarbeitet die aktive Challenge. Liefert (passed, prompt)."""
        if self._challenge_kind is None:
            return True, None
        if self._challenge_passed_at is not None:
            return True, None
        if self._challenge_started_at is not None and (
            now - self._challenge_started_at > self.config.challenge_timeout_seconds
        ):
            # Timeout -> Challenge gilt als nicht bestanden, neu anfordern.
            self._challenge_kind = None
            self._challenge_started_at = None
            return False, None

        passed = False
        if self._challenge_kind == "blink":
            passed = len(self._blink_times) > self._challenge_baseline_blinks
        elif self._challenge_kind == "turn_left" and yaw is not None:
            passed = yaw >= self.config.challenge_turn_yaw_degrees
        elif self._challenge_kind == "turn_right" and yaw is not None:
            passed = yaw <= -self.config.challenge_turn_yaw_degrees

        if passed:
            self._challenge_passed_at = now
            return True, None
        return False, self._challenge_prompt()

    def challenge_satisfied(self) -> bool:
        return self._challenge_passed_at is not None

    # -- Hauptaktualisierung ---------------------------------------------
    def update(
        self,
        blendshapes: Optional[Dict[str, float]],
        landmarks3d: Optional[np.ndarray],
        transform: Optional[np.ndarray],
        texture_score: float,
        geometry_rms: Optional[float] = None,
    ) -> LivenessResult:
        """Aktualisiert den Zustand mit einem Frame und liefert das Urteil."""
        now = time.time()
        result = LivenessResult(texture_score=float(texture_score))

        if not self.config.enabled:
            result.is_live = True
            result.score = 1.0
            return result

        blendshapes = blendshapes or {}
        self._update_blink(blendshapes, now)

        pose = head_pose_angles(transform)
        yaw = pose[0] if pose else None
        nose_offset = _normalized_nose_offset(landmarks3d)
        self._update_motion(yaw, nose_offset, now)

        # Einzelsignale
        texture_ok = texture_score >= self.config.texture_min_score
        result.blink_ok = self._blink_ok()
        parallax_ok, parallax_meaningful = self._parallax_ok()
        result.parallax_ok = parallax_ok

        # 3D-Geometrie-Konsistenz
        if geometry_rms is None or not math.isfinite(geometry_rms):
            result.geometry_ok = not self.config.geometry_required
        else:
            result.geometry_ok = geometry_rms <= self.config.geometry_max_rms

        # Aktive Challenge
        challenge_passed = True
        if self.config.active_challenge_enabled and self._challenge_kind is not None:
            result.challenge_active = True
            challenge_passed, prompt = self._update_challenge(yaw, now)
            result.challenge_prompt = prompt

        # Gesamturteil
        reasons: List[str] = []
        if not texture_ok:
            reasons.append("textur")
        if self.config.require_blink and not result.blink_ok:
            reasons.append("kein_blinzeln")
        if self.config.require_parallax and parallax_meaningful and not parallax_ok:
            reasons.append("keine_parallaxe")
        if not result.geometry_ok:
            reasons.append("geometrie")
        if result.challenge_active and not challenge_passed:
            reasons.append("challenge_offen")

        # Parallaxe darf nur blocken, wenn sie aussagekräftig ist. Solange der
        # Kopf nicht genug bewegt wurde, ersetzt das Blinzeln/Challenge die
        # Tiefenaussage.
        is_live = (
            texture_ok
            and (result.blink_ok or not self.config.require_blink)
            and result.geometry_ok
            and challenge_passed
        )
        if self.config.require_parallax and parallax_meaningful and not parallax_ok:
            is_live = False

        result.is_live = bool(is_live)
        result.reasons = reasons

        # Score: gewichtete Mischung der Signale (rein informativ).
        score = (
            0.30 * float(texture_score)
            + 0.25 * (1.0 if result.blink_ok else 0.0)
            + 0.20 * (1.0 if parallax_ok else (0.5 if not parallax_meaningful else 0.0))
            + 0.15 * (1.0 if result.geometry_ok else 0.0)
            + 0.10 * (1.0 if challenge_passed else 0.0)
        )
        result.score = float(np.clip(score, 0.0, 1.0))
        return result

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Robuste Gesichtserkennung für TuxGuard.

Primärer Backend: MediaPipe FaceLandmarker (478 Landmarks, BlazeFace + Face Mesh,
sehr robust gegenüber Kopfneigung, Halbprofilen und schwacher Beleuchtung).

Fallback: OpenCV-Haar-Cascades (frontal + Profil + gespiegeltes Profil + ±15°
Rotationen). Wird automatisch verwendet, wenn MediaPipe oder das Modell nicht
verfügbar sind.

Encoding-Pipeline:
    Detektion → Landmark-basierte Ausrichtung (Augenlinie horizontal,
    fester Augenabstand) → kanonisches 96×96 Crop → Intensitäts- und
    Gradientenfeatures → L2-normalisierte 1280-D Kodierung.

Die Ausrichtung über Landmarks macht die Kodierung weitgehend invariant
gegenüber Kopfdrehung/-neigung und verbessert die Wiedererkennung deutlich.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger("TuxGuard.FaceBackend")

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = Path(__file__).with_name("face_mediapipe_worker.py")

_MODEL_FILENAME = "face_landmarker_v2.task"
_MODEL_URL = "https://storage.googleapis.com/mediapipe-assets/face_landmarker_v2.task"

# Kanonisches Ausgabeformat für die ausgerichtete Gesichtsregion.
_CANONICAL_SIZE = 96
# Sollpositionen der Augenmitten im kanonischen Crop (in Pixeln).
_LEFT_EYE_TARGET = (32.0, 38.0)
_RIGHT_EYE_TARGET = (64.0, 38.0)

# Indizes der wichtigsten Landmarks im FaceLandmarker-Modell (478 Punkte).
# Wir mitteln über mehrere Punkte pro Auge für eine stabilere Schätzung.
_LEFT_EYE_LANDMARKS = (33, 133, 159, 145, 153, 144)   # äußere/innere/obere/untere Punkte
_RIGHT_EYE_LANDMARKS = (362, 263, 386, 374, 380, 373)
_NOSE_TIP_LANDMARK = 1
_CHIN_LANDMARK = 152
_FOREHEAD_LANDMARK = 10

_EmotionDetection = Tuple[
    Tuple[int, int, int, int],
    Optional[object],
    Optional[Dict[str, float]],
]

# ---------------------------------------------------------------------------
# Haar-Cascades (Fallback)
# ---------------------------------------------------------------------------

_FACE_CASCADE: Optional[cv2.CascadeClassifier] = None
_PROFILE_CASCADE: Optional[cv2.CascadeClassifier] = None


def _resolve_haarcascade_path(filename: str) -> Path:
    """Ermittelt robust den Pfad zu OpenCV-Haar-Cascades."""
    candidates = []
    if hasattr(cv2, "data") and getattr(cv2.data, "haarcascades", None):
        candidates.append(Path(cv2.data.haarcascades) / filename)
    cv2_file = Path(getattr(cv2, "__file__", "")).resolve()
    candidates.extend([
        cv2_file.parent / "data" / filename,
        cv2_file.parent / "haarcascades" / filename,
        Path("/usr/share/opencv4/haarcascades") / filename,
        Path("/usr/share/opencv/haarcascades") / filename,
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Haar-Cascade nicht gefunden: {filename}")


def _get_face_cascade() -> cv2.CascadeClassifier:
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        path = _resolve_haarcascade_path("haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(str(path))
        if cascade.empty():
            raise RuntimeError(f"Haar-Cascade konnte nicht geladen werden: {path}")
        _FACE_CASCADE = cascade
    return _FACE_CASCADE


def _get_profile_cascade() -> cv2.CascadeClassifier:
    global _PROFILE_CASCADE
    if _PROFILE_CASCADE is None:
        path = _resolve_haarcascade_path("haarcascade_profileface.xml")
        cascade = cv2.CascadeClassifier(str(path))
        if cascade.empty():
            raise RuntimeError(f"Profil-Cascade konnte nicht geladen werden: {path}")
        _PROFILE_CASCADE = cascade
    return _PROFILE_CASCADE


# ---------------------------------------------------------------------------
# MediaPipe FaceLandmarker (primärer Backend)
# ---------------------------------------------------------------------------

_MP_LANDMARKER = None
_MP_LOCK = threading.Lock()
_MP_AVAILABLE: Optional[bool] = None  # tri-state: None=ungeprüft, True/False
_MP_MODEL_PATH: Optional[Path] = None


def _candidate_model_paths() -> List[Path]:
    """Mögliche Speicherorte des FaceLandmarker-Modells."""
    here = Path(__file__).resolve().parent
    return [
        Path(os.environ.get("TUXGUARD_FACE_MODEL", "")),
        here / "models" / _MODEL_FILENAME,
        here / _MODEL_FILENAME,
        Path("/opt/tuxguard/models") / _MODEL_FILENAME,
        Path.home() / ".cache" / "tuxguard" / _MODEL_FILENAME,
    ]


def _find_model_path() -> Optional[Path]:
    for candidate in _candidate_model_paths():
        try:
            if candidate and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


def _download_model_if_possible() -> Optional[Path]:
    """Versucht, das Modell in den Benutzer-Cache herunterzuladen."""
    target = Path.home() / ".cache" / "tuxguard" / _MODEL_FILENAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Lade FaceLandmarker-Modell herunter nach %s …", target)
        urllib.request.urlretrieve(_MODEL_URL, target)
        if target.is_file() and target.stat().st_size > 0:
            return target
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Modell-Download fehlgeschlagen: %s", exc)
    return None


def _ensure_landmarker():
    """Initialisiert (lazy) den MediaPipe FaceLandmarker.

    Gibt das Landmarker-Objekt zurück oder ``None``, wenn MediaPipe nicht
    aktiviert oder nicht verfügbar ist.

    MediaPipe ist standardmäßig **deaktiviert**, weil es in derselben
    Python-Instanz wie TensorFlow zu Symbol-Konflikten (LLVM/TFLite
    PassRegistry) und Segfaults führen kann. Aktivierung über Env-Var
    ``TUXGUARD_USE_MEDIAPIPE=1`` – sinnvoll nur im isolierten Worker-
    Subprozess (siehe ``face_mediapipe_worker.py``), der diese Variable
    selbst setzt.
    """
    global _MP_LANDMARKER, _MP_AVAILABLE, _MP_MODEL_PATH

    if _MP_AVAILABLE is False:
        return None
    if _MP_LANDMARKER is not None:
        return _MP_LANDMARKER

    if os.environ.get("TUXGUARD_USE_MEDIAPIPE", "0") not in ("1", "true", "yes"):
        _MP_AVAILABLE = False
        return None

    with _MP_LOCK:
        if _MP_LANDMARKER is not None:
            return _MP_LANDMARKER
        if _MP_AVAILABLE is False:
            return None

        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("MediaPipe nicht verfügbar (%s) – Cascade-Fallback aktiv.", exc)
            _MP_AVAILABLE = False
            return None

        model_path = _find_model_path() or _download_model_if_possible()
        if model_path is None:
            logger.warning(
                "FaceLandmarker-Modell nicht gefunden – Cascade-Fallback aktiv."
            )
            _MP_AVAILABLE = False
            return None

        try:
            base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
            options = mp_vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=4,
                min_face_detection_confidence=0.3,
                min_face_presence_confidence=0.3,
                min_tracking_confidence=0.3,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
            )
            _MP_LANDMARKER = mp_vision.FaceLandmarker.create_from_options(options)
            _MP_MODEL_PATH = model_path
            _MP_AVAILABLE = True
            logger.info("MediaPipe FaceLandmarker geladen (%s).", model_path)
            return _MP_LANDMARKER
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("FaceLandmarker konnte nicht initialisiert werden: %s", exc)
            _MP_AVAILABLE = False
            return None


def _landmark_xy(
    landmarks: Sequence,
    index: int,
    width: int,
    height: int,
) -> Tuple[float, float]:
    point = landmarks[index]
    return (float(point.x) * width, float(point.y) * height)


def _eye_center(
    landmarks: Sequence,
    indices: Sequence[int],
    width: int,
    height: int,
) -> Tuple[float, float]:
    pts = np.array(
        [_landmark_xy(landmarks, i, width, height) for i in indices],
        dtype=np.float32,
    )
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def _bbox_from_landmarks(
    landmarks: Sequence,
    width: int,
    height: int,
    pad_ratio: float = 0.15,
) -> Tuple[int, int, int, int]:
    xs = np.fromiter((p.x for p in landmarks), dtype=np.float32) * width
    ys = np.fromiter((p.y for p in landmarks), dtype=np.float32) * height
    left = float(xs.min())
    right = float(xs.max())
    top = float(ys.min())
    bottom = float(ys.max())
    pad_w = (right - left) * pad_ratio
    pad_h = (bottom - top) * pad_ratio
    left = max(0, int(round(left - pad_w)))
    right = min(width, int(round(right + pad_w)))
    top = max(0, int(round(top - pad_h)))
    bottom = min(height, int(round(bottom + pad_h)))
    return top, right, bottom, left


def _detect_with_mediapipe(
    image: np.ndarray,
) -> List[_EmotionDetection]:
    """Liefert Liste aus (bbox, landmark_list_or_None)."""
    landmarker = _ensure_landmarker()
    if landmarker is None:
        return []

    try:
        import mediapipe as mp
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                            data=np.ascontiguousarray(image, dtype=np.uint8))
        with _MP_LOCK:
            result = landmarker.detect(mp_image)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("MediaPipe-Detect fehlgeschlagen: %s", exc)
        return []

    height, width = image.shape[:2]
    detections: List[_EmotionDetection] = []
    landmarks_list = list(result.face_landmarks or [])
    blendshapes_list = list(result.face_blendshapes or [])
    for index, landmarks in enumerate(landmarks_list):
        try:
            bbox = _bbox_from_landmarks(landmarks, width, height)
            if bbox[2] > bbox[0] and bbox[1] > bbox[3]:
                blendshape_scores: Dict[str, float] = {}
                if index < len(blendshapes_list):
                    categories = getattr(blendshapes_list[index], "categories", []) or []
                    for category in categories:
                        name = str(getattr(category, "category_name", "") or "").strip()
                        if not name:
                            continue
                        score = float(getattr(category, "score", 0.0) or 0.0)
                        blendshape_scores[name] = max(0.0, min(1.0, score))
                detections.append((bbox, landmarks, blendshape_scores))
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Landmark-Auswertung fehlgeschlagen: %s", exc)
    return detections


# ---------------------------------------------------------------------------
# Haar-Cascade-Detektion (Fallback und Augmentierung für volle Profile)
# ---------------------------------------------------------------------------

def _detect_with_cascades(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    if image is None or image.size == 0:
        return []

    rgb = np.ascontiguousarray(image, dtype=np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    try:
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    except Exception:  # pylint: disable=broad-except
        gray = cv2.equalizeHist(gray)

    height, width = gray.shape
    results: List[Tuple[int, int, int, int]] = []

    def _add(x: int, y: int, w: int, h: int) -> None:
        top = max(int(y), 0)
        left = max(int(x), 0)
        bottom = min(int(y + h), height)
        right = min(int(x + w), width)
        if bottom > top and right > left:
            results.append((top, right, bottom, left))

    try:
        for x, y, w, h in _get_face_cascade().detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)
        ):
            _add(x, y, w, h)

        for x, y, w, h in _get_profile_cascade().detectMultiScale(
            gray, scaleFactor=1.08, minNeighbors=3, minSize=(48, 48)
        ):
            _add(x, y, w, h)

        flipped = cv2.flip(gray, 1)
        for x, y, w, h in _get_profile_cascade().detectMultiScale(
            flipped, scaleFactor=1.08, minNeighbors=3, minSize=(48, 48)
        ):
            _add(width - (x + w), y, w, h)

        for angle in (-15, 15):
            rot_mat = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
            inv_mat = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), -angle, 1.0)
            rotated = cv2.warpAffine(
                gray, rot_mat, (width, height),
                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
            )
            rotated_hits: List[Tuple[int, int, int, int]] = []
            for x, y, w, h in _get_face_cascade().detectMultiScale(
                rotated, scaleFactor=1.1, minNeighbors=4, minSize=(48, 48)
            ):
                rotated_hits.append((x, y, w, h))
            for x, y, w, h in _get_profile_cascade().detectMultiScale(
                rotated, scaleFactor=1.08, minNeighbors=3, minSize=(48, 48)
            ):
                rotated_hits.append((x, y, w, h))
            for x, y, w, h in rotated_hits:
                corners = np.array([
                    [x, y], [x + w, y], [x + w, y + h], [x, y + h]
                ], dtype=np.float32)
                ones = np.ones((4, 1), dtype=np.float32)
                mapped = (inv_mat @ np.hstack([corners, ones]).T).T
                xs, ys = mapped[:, 0], mapped[:, 1]
                _add(int(round(xs.min())), int(round(ys.min())),
                     int(round(xs.max() - xs.min())),
                     int(round(ys.max() - ys.min())))
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Cascade-Detektion fehlgeschlagen: %s", exc)

    return results


# ---------------------------------------------------------------------------
# Bounding-Box-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _box_overlap(a: Tuple[int, int, int, int],
                 b: Tuple[int, int, int, int]) -> float:
    at, ar, ab, al = a
    bt, br, bb, bl = b
    inter_left = max(al, bl)
    inter_top = max(at, bt)
    inter_right = min(ar, br)
    inter_bottom = min(ab, bb)
    if inter_right <= inter_left or inter_bottom <= inter_top:
        return 0.0
    inter = (inter_right - inter_left) * (inter_bottom - inter_top)
    area_a = max(1, (ab - at) * (ar - al))
    area_b = max(1, (bb - bt) * (br - bl))
    return inter / min(area_a, area_b)


def _dedupe_boxes(
    boxes: Sequence[Tuple[int, int, int, int]],
    threshold: float = 0.5,
) -> List[Tuple[int, int, int, int]]:
    out: List[Tuple[int, int, int, int]] = []
    for box in boxes:
        if any(_box_overlap(box, existing) >= threshold for existing in out):
            continue
        out.append(box)
    return out


def _clip_box(
    box: Tuple[int, int, int, int],
    image_shape: Tuple[int, ...],
) -> Tuple[int, int, int, int]:
    top, right, bottom, left = box
    height, width = image_shape[:2]
    top = max(0, min(top, height))
    bottom = max(0, min(bottom, height))
    left = max(0, min(left, width))
    right = max(0, min(right, width))
    return top, right, bottom, left


# ---------------------------------------------------------------------------
# Detektion mit Landmarks (fasst MediaPipe + Cascade zusammen)
# ---------------------------------------------------------------------------

# Pro-Frame-Cache: vermeidet doppelte Detektion, wenn der Aufrufer zuerst
# face_locations() und danach face_encodings() für denselben Frame aufruft.
_DETECTION_CACHE_KEY: Optional[Tuple[int, int, int, bytes]] = None
_DETECTION_CACHE_VALUE: List[_EmotionDetection] = []


def _cache_key(image: np.ndarray) -> Tuple[int, int, int, bytes]:
    # id() + Form + ein paar Stichprobenbytes – günstig und ausreichend
    # eindeutig für aufeinanderfolgende Aufrufe innerhalb desselben Frames.
    flat = image.reshape(-1)
    sample = flat[:: max(1, flat.size // 8)][:8].tobytes()
    return (id(image), image.shape[0], image.shape[1], sample)


def _detect_faces_with_landmarks(
    image: np.ndarray,
) -> List[_EmotionDetection]:
    """Hauptdetektion. Liefert (bbox, landmarks_or_None) sortiert nach Größe."""
    global _DETECTION_CACHE_KEY, _DETECTION_CACHE_VALUE

    if image is None or image.size == 0:
        return []

    key = _cache_key(image)
    if key == _DETECTION_CACHE_KEY:
        return _DETECTION_CACHE_VALUE

    detections = _detect_with_mediapipe(image)
    mp_boxes = [det[0] for det in detections]

    # Cascade nur als Augmentierung für sehr seitliche Profile, die der
    # FaceLandmarker (frontal-orientiert) nicht erkennt. Wenn MediaPipe
    # gar nicht verfügbar ist, ist sie der primäre Backend.
    cascade_boxes = _detect_with_cascades(image)
    for box in cascade_boxes:
        if any(_box_overlap(box, existing) >= 0.4 for existing in mp_boxes):
            continue
        detections.append((box, None, None))

    # Deduplizierung über alle Detektionen
    deduped: List[_EmotionDetection] = []
    for det in detections:
        if any(_box_overlap(det[0], existing[0]) >= 0.5 for existing in deduped):
            continue
        deduped.append(det)

    # Nach Fläche absteigend sortieren – größere Gesichter sind verlässlicher.
    deduped.sort(
        key=lambda d: (d[0][2] - d[0][0]) * (d[0][1] - d[0][3]),
        reverse=True,
    )

    _DETECTION_CACHE_KEY = key
    _DETECTION_CACHE_VALUE = deduped
    return deduped


# ---------------------------------------------------------------------------
# Encoding (mit Landmark-basierter Ausrichtung)
# ---------------------------------------------------------------------------

def _align_with_landmarks(
    image: np.ndarray,
    landmarks: Sequence,
) -> Optional[np.ndarray]:
    """Richtet ein Gesicht über die Augenpositionen kanonisch aus."""
    height, width = image.shape[:2]
    try:
        left_eye = _eye_center(landmarks, _LEFT_EYE_LANDMARKS, width, height)
        right_eye = _eye_center(landmarks, _RIGHT_EYE_LANDMARKS, width, height)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Augen-Landmarks nicht verfügbar: %s", exc)
        return None

    src = np.array([left_eye, right_eye], dtype=np.float32)
    dst = np.array([_LEFT_EYE_TARGET, _RIGHT_EYE_TARGET], dtype=np.float32)

    # Ähnlichkeitstransformation aus zwei Punkt-Paaren herleiten.
    dx_src = src[1, 0] - src[0, 0]
    dy_src = src[1, 1] - src[0, 1]
    dx_dst = dst[1, 0] - dst[0, 0]
    dy_dst = dst[1, 1] - dst[0, 1]
    src_len = float(np.hypot(dx_src, dy_src))
    if src_len < 1e-3:
        return None
    scale = float(np.hypot(dx_dst, dy_dst)) / src_len
    angle = float(np.arctan2(dy_src, dx_src) - np.arctan2(dy_dst, dx_dst))
    cos_a = np.cos(angle) * scale
    sin_a = np.sin(angle) * scale

    matrix = np.array([
        [cos_a, sin_a, dst[0, 0] - (cos_a * src[0, 0] + sin_a * src[0, 1])],
        [-sin_a, cos_a, dst[0, 1] - (-sin_a * src[0, 0] + cos_a * src[0, 1])],
    ], dtype=np.float32)

    aligned = cv2.warpAffine(
        image, matrix, (_CANONICAL_SIZE, _CANONICAL_SIZE),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    return aligned


def _align_with_bbox(
    image: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> Optional[np.ndarray]:
    top, right, bottom, left = _clip_box(bbox, image.shape)
    region = image[top:bottom, left:right]
    if region.size == 0:
        return None
    return cv2.resize(region, (_CANONICAL_SIZE, _CANONICAL_SIZE),
                      interpolation=cv2.INTER_AREA)


def _encode_aligned(aligned_rgb: np.ndarray) -> Optional[np.ndarray]:
    """Wandelt einen kanonischen 96×96-RGB-Crop in eine 1280-D Kodierung."""
    if aligned_rgb is None or aligned_rgb.size == 0:
        return None

    gray = cv2.cvtColor(aligned_rgb, cv2.COLOR_RGB2GRAY)
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    except Exception:  # pylint: disable=broad-except
        gray = cv2.equalizeHist(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    intensity = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    grad_x = cv2.Sobel(intensity, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(intensity, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(grad_x, grad_y)
    grad_mag = cv2.resize(grad_mag, (16, 16), interpolation=cv2.INTER_AREA)

    intensity_vec = intensity.astype(np.float32).flatten() / 255.0
    grad_vec = grad_mag.astype(np.float32).flatten()
    if grad_vec.max() > 0:
        grad_vec /= grad_vec.max()

    encoding = np.concatenate([intensity_vec, grad_vec]).astype(np.float64)
    encoding -= encoding.mean()
    norm = np.linalg.norm(encoding)
    if norm < 1e-8:
        return None
    return encoding / norm


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def load_image_file(file_path: str) -> np.ndarray:
    """Lädt ein Bild und gibt es als RGB-Array zurück."""
    image = cv2.imread(file_path)
    if image is None:
        raise FileNotFoundError(f"Bilddatei nicht gefunden: {file_path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def face_locations(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Liefert erkannte Gesichter als Tupel ``(top, right, bottom, left)``."""
    return [bbox for bbox, _, _ in _detect_faces_with_landmarks(image)]


def face_encodings(
    image: np.ndarray,
    face_locations: Optional[List[Tuple[int, int, int, int]]] = None,  # noqa: ARG001
) -> List[np.ndarray]:
    """Liefert eine Liste robuster, landmark-ausgerichteter Gesichtskodierungen.

    Hinweis: Auch wenn ``face_locations`` übergeben wird, führt diese Funktion
    intern eine eigene Detektion (mit Landmarks) durch, da die Ausrichtung über
    Landmarks die Kodierungsqualität deutlich verbessert. Das Argument bleibt
    aus Kompatibilitätsgründen erhalten.
    """
    detections = _detect_faces_with_landmarks(image)
    encodings: List[np.ndarray] = []
    for bbox, landmarks, _ in detections:
        aligned: Optional[np.ndarray] = None
        if landmarks is not None:
            aligned = _align_with_landmarks(image, landmarks)
        if aligned is None:
            aligned = _align_with_bbox(image, bbox)
        if aligned is None:
            continue
        encoding = _encode_aligned(aligned)
        if encoding is not None:
            encodings.append(encoding)
    return encodings


def face_distance(
    known_encodings: List[np.ndarray],
    face_encoding: np.ndarray,
) -> np.ndarray:
    """Euklidischer Abstand zwischen bekannten Kodierungen und einer neuen."""
    if not known_encodings:
        return np.array([])
    distances = []
    for known in known_encodings:
        if known.shape != face_encoding.shape:
            distances.append(float("inf"))
            continue
        distances.append(float(np.linalg.norm(known - face_encoding)))
    return np.array(distances, dtype=np.float64)


def compare_faces(
    known_encodings: List[np.ndarray],
    face_encoding: np.ndarray,
    tolerance: float = 0.9,
) -> List[bool]:
    """Vergleicht bekannte Kodierungen mit einer neuen Kodierung."""
    distances = face_distance(known_encodings, face_encoding)
    return [float(distance) <= tolerance for distance in distances]


def _mean_score(scores: Dict[str, float], keys: Sequence[str]) -> float:
    values = [float(scores.get(key, 0.0)) for key in keys]
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _infer_emotion_from_blendshapes(
    scores: Optional[Dict[str, float]],
    min_confidence: float,
) -> Dict[str, object]:
    """Leitet eine grobe Emotion aus FaceBlendshape-Scores ab."""
    if not scores:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "source": "none",
            "scores": {},
        }

    emotion_scores = {
        "happy": _mean_score(scores, (
            "mouthSmileLeft", "mouthSmileRight", "cheekSquintLeft", "cheekSquintRight"
        )),
        "sad": _mean_score(scores, (
            "browInnerUp", "mouthFrownLeft", "mouthFrownRight"
        )),
        "angry": _mean_score(scores, (
            "browDownLeft", "browDownRight", "noseSneerLeft", "noseSneerRight", "jawForward"
        )),
        "surprised": _mean_score(scores, (
            "jawOpen", "eyeWideLeft", "eyeWideRight", "browOuterUpLeft", "browOuterUpRight"
        )),
        "fearful": _mean_score(scores, (
            "eyeWideLeft", "eyeWideRight", "mouthStretchLeft", "mouthStretchRight", "browInnerUp"
        )),
        "disgusted": _mean_score(scores, (
            "noseSneerLeft", "noseSneerRight", "mouthUpperUpLeft", "mouthUpperUpRight"
        )),
        "neutral": 0.2,
    }

    total = float(sum(max(0.0, val) for val in emotion_scores.values()))
    if total <= 1e-8:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "source": "blendshape",
            "scores": emotion_scores,
        }

    best_label, best_score = max(emotion_scores.items(), key=lambda item: item[1])
    confidence = float(max(0.0, min(1.0, best_score / total)))
    label = best_label if confidence >= min_confidence else "unknown"

    return {
        "label": label,
        "confidence": confidence,
        "source": "blendshape",
        "scores": emotion_scores,
    }


def face_emotions(
    image: np.ndarray,
    min_confidence: float = 0.35,
) -> List[Dict[str, object]]:
    """Liefert pro erkanntem Gesicht eine grobe Emotionsschätzung.

    Die Reihenfolge entspricht ``face_locations(image)``.
    """
    detections = _detect_faces_with_landmarks(image)
    emotions: List[Dict[str, object]] = []
    threshold = float(max(0.0, min(1.0, min_confidence)))
    for bbox, _, blendshape_scores in detections:
        result = _infer_emotion_from_blendshapes(blendshape_scores, threshold)
        result["bbox"] = bbox
        emotions.append(result)
    return emotions


def safe_face_encodings_from_file(file_path: str, timeout: int = 30) -> List[np.ndarray]:
    """Liest Gesichtskodierungen in einem separaten Prozess aus einer Bilddatei."""
    if not _WORKER_SCRIPT.exists():
        raise FileNotFoundError(f"Worker-Skript nicht gefunden: {_WORKER_SCRIPT}")

    try:
        result = subprocess.run(
            [sys.executable, str(_WORKER_SCRIPT), file_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Gesichtserkennung hat das Zeitlimit überschritten.") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        details = f"Worker beendet mit Code {result.returncode}"
        if stdout:
            try:
                payload = json.loads(stdout)
                details = payload.get("error", details)
            except json.JSONDecodeError:
                details = stdout.splitlines()[-1]
        elif stderr:
            details = stderr.splitlines()[-1]
        raise RuntimeError(f"Gesichtserkennung fehlgeschlagen: {details}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ungültige Antwort vom Gesichtserkennungs-Worker.") from exc

    return [np.array(encoding, dtype=np.float64) for encoding in payload.get("encodings", [])]


def safe_face_analysis_from_file(file_path: str, timeout: int = 30) -> Dict[str, object]:
    """Liefert Gesichtskodierungen plus optionale Emotionsschätzung aus Worker."""
    if not _WORKER_SCRIPT.exists():
        raise FileNotFoundError(f"Worker-Skript nicht gefunden: {_WORKER_SCRIPT}")

    try:
        result = subprocess.run(
            [sys.executable, str(_WORKER_SCRIPT), file_path, "--with-emotions"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Gesichtsanalyse hat das Zeitlimit überschritten.") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        details = f"Worker beendet mit Code {result.returncode}"
        if stdout:
            try:
                payload = json.loads(stdout)
                details = payload.get("error", details)
            except json.JSONDecodeError:
                details = stdout.splitlines()[-1]
        elif stderr:
            details = stderr.splitlines()[-1]
        raise RuntimeError(f"Gesichtsanalyse fehlgeschlagen: {details}")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ungültige Antwort vom Gesichtsanalyse-Worker.") from exc

    return {
        "encodings": [np.array(encoding, dtype=np.float64) for encoding in payload.get("encodings", [])],
        "emotions": payload.get("emotions", []),
    }


def backend_info() -> dict:
    """Diagnose-Information über den aktiven Backend (für Logs/Tests)."""
    landmarker = _ensure_landmarker()
    return {
        "backend": "mediapipe" if landmarker is not None else "opencv-cascade",
        "model_path": str(_MP_MODEL_PATH) if _MP_MODEL_PATH else None,
        "available": bool(landmarker is not None),
    }

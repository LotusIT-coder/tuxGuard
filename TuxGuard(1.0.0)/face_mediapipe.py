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


def _config_value(name: str, default: float) -> float:
    """Liest ein Tunable aus der zentralen Config (lazy, optional).

    Das Modul bleibt ohne Config lauffähig (z. B. isolierter Worker-Prozess
    oder Tests); dann gelten die eingebauten Standardwerte.
    """
    try:
        from config import Config  # lokaler Import vermeidet harte Abhängigkeit
        return float(getattr(Config, name, default))
    except Exception:  # pylint: disable=broad-except
        return float(default)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = Path(__file__).with_name("face_mediapipe_worker.py")

_MODEL_FILENAME = "face_landmarker_v2.task"
# Offizielles FaceLandmarker-Bundle MIT Blendshape-Submodell (~3,7 MB).
# Achtung: Die ältere URL unter mediapipe-assets/face_landmarker_v2.task
# liefert eine Variante OHNE Blendshapes (~1,4 MB), mit der weder
# Emotionserkennung noch output_face_blendshapes=True funktionieren.
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

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

# Stabile, weit auseinanderliegende Landmarks zur kanonischen Normalisierung
# der 3D-Geometrie (Augen außen, Nasenspitze, Mundwinkel, Kinn, Stirn).
_GEOMETRY_ANCHOR_LANDMARKS = (33, 263, 1, 61, 291, 152, 10, 199)

# Eine 4-Tuple-Detektion: (bbox, landmarks_or_None, blendshapes_or_None,
# transform_matrix_or_None). ``transform_matrix`` ist die 4×4 Kopf-Pose-Matrix
# des FaceLandmarkers (nur bei MediaPipe-Detektionen vorhanden).
_FaceDetection = Tuple[
    Tuple[int, int, int, int],
    Optional[object],
    Optional[Dict[str, float]],
    Optional[np.ndarray],
]
# Rückwärtskompatibler Alias.
_EmotionDetection = _FaceDetection

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
_MP_BLENDSHAPES = False  # True, wenn das geladene Modell Blendshapes liefert


def _block_tensorflow_import() -> None:
    """Verhindert, dass MediaPipe das volle TensorFlow-Paket mitlädt.

    ``mediapipe.tasks`` importiert TensorFlow nur optional (für Doku-
    Dekoratoren). Ist das volle TensorFlow-Paket installiert, kollidieren
    dessen MLIR-Pass-Registries mit denen von MediaPipe und das Laden des
    FaceLandmarker-Graphen endet in einem Segfault
    ("Error: Required pass not found"). TuxGuard selbst nutzt TensorFlow
    nicht, daher wird der Import prozessweit blockiert.
    """
    if "tensorflow" not in sys.modules:
        sys.modules["tensorflow"] = None  # type: ignore[assignment]


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

    MediaPipe ist standardmäßig **aktiviert**. Bei Problemen kann es
    über ``TUXGUARD_USE_MEDIAPIPE=0`` explizit deaktiviert werden.
    """
    global _MP_LANDMARKER, _MP_AVAILABLE, _MP_MODEL_PATH, _MP_BLENDSHAPES

    if _MP_AVAILABLE is False:
        return None
    if _MP_LANDMARKER is not None:
        return _MP_LANDMARKER

    use_mp = str(os.environ.get("TUXGUARD_USE_MEDIAPIPE", "1") or "1").strip().lower()
    if use_mp in ("0", "false", "no"):
        _MP_AVAILABLE = False
        return None

    with _MP_LOCK:
        if _MP_LANDMARKER is not None:
            return _MP_LANDMARKER
        if _MP_AVAILABLE is False:
            return None

        _block_tensorflow_import()
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

        # Konfigurierbare Mindest-Konfidenz: 0.3 war zu tolerant und führte
        # zu Phantomdetektionen in strukturierten Hintergründen.
        confidence = max(0.05, min(0.95, _config_value("FACE_DETECTION_MIN_CONFIDENCE", 0.5)))

        def _create(path: Path, with_blendshapes: bool):
            options = mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(path)),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=4,
                min_face_detection_confidence=confidence,
                min_face_presence_confidence=confidence,
                min_tracking_confidence=confidence,
                output_face_blendshapes=with_blendshapes,
                output_facial_transformation_matrixes=True,
            )
            return mp_vision.FaceLandmarker.create_from_options(options)

        landmarker = None
        blendshapes = False
        try:
            landmarker = _create(model_path, True)
            blendshapes = True
        except Exception as exc:  # pylint: disable=broad-except
            if "blendshape" in str(exc).lower():
                # Modell ohne Blendshape-Submodell (z. B. alte mediapipe-assets-
                # Variante). Versuche, das vollständige Modell nachzuladen.
                logger.warning(
                    "Modell %s enthält kein Blendshape-Submodell – "
                    "lade vollständiges Modell nach.", model_path,
                )
                fresh = _download_model_if_possible()
                if fresh is not None:
                    try:
                        landmarker = _create(fresh, True)
                        blendshapes = True
                        model_path = fresh
                    except Exception as exc2:  # pylint: disable=broad-except
                        logger.warning("Nachgeladenes Modell fehlgeschlagen: %s", exc2)
            else:
                logger.warning("FaceLandmarker-Init mit Blendshapes fehlgeschlagen: %s", exc)

        if landmarker is None:
            # Letzter Versuch: ohne Blendshapes (Landmarks/Alignment bleiben
            # nutzbar, nur die Emotionserkennung entfällt).
            try:
                landmarker = _create(model_path, False)
                logger.warning(
                    "FaceLandmarker ohne Blendshapes geladen – "
                    "Emotionserkennung nicht verfügbar."
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("FaceLandmarker konnte nicht initialisiert werden: %s", exc)
                _MP_AVAILABLE = False
                return None

        _MP_LANDMARKER = landmarker
        _MP_MODEL_PATH = model_path
        _MP_BLENDSHAPES = blendshapes
        _MP_AVAILABLE = True
        logger.info(
            "MediaPipe FaceLandmarker geladen (%s, Blendshapes=%s).",
            model_path, blendshapes,
        )
        return _MP_LANDMARKER


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
    transform_list = list(getattr(result, "facial_transformation_matrixes", None) or [])
    for index, landmarks in enumerate(landmarks_list):
        try:
            bbox = _bbox_from_landmarks(landmarks, width, height)
            if bbox[2] > bbox[0] and bbox[1] > bbox[3]:
                blendshape_scores: Dict[str, float] = {}
                if index < len(blendshapes_list):
                    entry = blendshapes_list[index]
                    # Neue Tasks-API liefert direkt eine Liste von Category-
                    # Objekten, ältere Versionen ein Objekt mit ``.categories``.
                    if isinstance(entry, (list, tuple)):
                        categories = entry
                    else:
                        categories = getattr(entry, "categories", []) or []
                    for category in categories:
                        name = str(getattr(category, "category_name", "") or "").strip()
                        if not name:
                            continue
                        score = float(getattr(category, "score", 0.0) or 0.0)
                        blendshape_scores[name] = max(0.0, min(1.0, score))
                transform = None
                if index < len(transform_list):
                    try:
                        transform = np.asarray(transform_list[index], dtype=np.float64)
                        if transform.shape != (4, 4):
                            transform = None
                    except Exception:  # pylint: disable=broad-except
                        transform = None
                detections.append((bbox, landmarks, blendshape_scores, transform))
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
            gray, scaleFactor=1.08, minNeighbors=4, minSize=(48, 48)
        ):
            _add(x, y, w, h)

        flipped = cv2.flip(gray, 1)
        for x, y, w, h in _get_profile_cascade().detectMultiScale(
            flipped, scaleFactor=1.08, minNeighbors=4, minSize=(48, 48)
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
                rotated, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)
            ):
                rotated_hits.append((x, y, w, h))
            for x, y, w, h in _get_profile_cascade().detectMultiScale(
                rotated, scaleFactor=1.08, minNeighbors=4, minSize=(48, 48)
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
    # Solange MediaPipe aktiv ist, sind Cascade-Treffer nur Ergänzung –
    # dann muss sich ein Kandidat durch mindestens einen weiteren,
    # überlappenden Treffer eines anderen Durchlaufs bestätigen. Einzelne,
    # unbestätigte Cascade-Treffer sind überwiegend Phantomgesichter.
    cascade_is_fallback = _MP_AVAILABLE is False
    for index, box in enumerate(cascade_boxes):
        if any(_box_overlap(box, existing) >= 0.4 for existing in mp_boxes):
            continue
        if not cascade_is_fallback:
            votes = sum(
                1
                for other_index, other in enumerate(cascade_boxes)
                if other_index != index and _box_overlap(box, other) >= 0.5
            )
            if votes < 1:
                continue
        detections.append((box, None, None, None))

    # Deduplizierung über alle Detektionen
    deduped: List[_EmotionDetection] = []
    for det in detections:
        if any(_box_overlap(det[0], existing[0]) >= 0.5 for existing in deduped):
            continue
        deduped.append(det)

    # Winzige Boxen sind bei einer Desktop-Kamera keine plausiblen Nutzer-
    # Gesichter, sondern fast immer Fehldetektionen im Hintergrund.
    height, width = image.shape[:2]
    min_rel = max(0.0, min(0.5, _config_value("FACE_MIN_RELATIVE_SIZE", 0.08)))
    min_side = min_rel * float(min(height, width))
    if min_side > 0:
        deduped = [
            det for det in deduped
            if (det[0][2] - det[0][0]) >= min_side
            and (det[0][1] - det[0][3]) >= min_side
        ]

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
    return [bbox for bbox, _, _, _ in _detect_faces_with_landmarks(image)]


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
    for bbox, landmarks, _, _ in detections:
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


def landmarks_to_xyz(landmarks: Sequence) -> np.ndarray:
    """Wandelt MediaPipe-Landmarks in ein ``(N, 3)``-Array (x, y, z) um.

    Die Koordinaten sind die normalisierten MediaPipe-Werte (x, y in [0, 1]
    relativ zur Bildbreite/-höhe, z als relative Tiefe in vergleichbarer
    Skala wie x). Liefert ein leeres Array, wenn keine 3D-Punkte vorliegen.
    """
    try:
        return np.array(
            [(float(p.x), float(p.y), float(p.z)) for p in landmarks],
            dtype=np.float64,
        )
    except Exception:  # pylint: disable=broad-except
        return np.empty((0, 3), dtype=np.float64)


def face_geometry(image: np.ndarray) -> List[np.ndarray]:
    """Liefert pro erkanntem Gesicht die rohe 3D-Landmark-Geometrie ``(N, 3)``.

    Nur MediaPipe-Detektionen besitzen 3D-Landmarks; Cascade-Fallback-
    Detektionen werden übersprungen. Die Reihenfolge entspricht
    ``face_locations(image)`` für die MediaPipe-Treffer.
    """
    geometries: List[np.ndarray] = []
    for _, landmarks, _, _ in _detect_faces_with_landmarks(image):
        if landmarks is None:
            continue
        xyz = landmarks_to_xyz(landmarks)
        if xyz.size:
            geometries.append(xyz)
    return geometries


def face_analysis_full(image: np.ndarray) -> List[Dict[str, object]]:
    """Konsolidierte Einzeldetektion: alle Merkmale pro Gesicht in einem Pass.

    Liefert pro Gesicht ein Dict mit:
        ``bbox``         – (top, right, bottom, left)
        ``encoding``     – 1280-D Kodierung oder ``None``
        ``landmarks3d``  – ``(N, 3)``-Array oder ``None`` (nur MediaPipe)
        ``blendshapes``  – Dict[str, float] (ggf. leer)
        ``transform``    – 4×4 Kopf-Pose-Matrix oder ``None``

    Dient der Kamera-Pipeline, um Identitäts-, Emotions- und
    Liveness-Auswertung aus einer einzigen Detektion zu speisen.
    """
    results: List[Dict[str, object]] = []
    for bbox, landmarks, blendshapes, transform in _detect_faces_with_landmarks(image):
        aligned: Optional[np.ndarray] = None
        if landmarks is not None:
            aligned = _align_with_landmarks(image, landmarks)
        if aligned is None:
            aligned = _align_with_bbox(image, bbox)
        encoding = _encode_aligned(aligned) if aligned is not None else None
        landmarks3d = landmarks_to_xyz(landmarks) if landmarks is not None else None
        if landmarks3d is not None and landmarks3d.size == 0:
            landmarks3d = None
        results.append(
            {
                "bbox": bbox,
                "encoding": encoding,
                "landmarks3d": landmarks3d,
                "blendshapes": dict(blendshapes) if blendshapes else {},
                "transform": transform,
            }
        )
    return results


def _blockwise_squared_diff(diff: np.ndarray) -> Optional[np.ndarray]:
    """Zerlegt die Differenz zweier 1280-D-Kodierungen in 16 Gesichtsregionen.

    Die Kodierung besteht aus einem 32×32-Intensitätsraster (1024 Werte) und
    einem 16×16-Gradientenraster (256 Werte). Beide werden in ein räumlich
    deckungsgleiches 4×4-Regionenraster aufgeteilt; zurückgegeben wird die
    quadrierte Abweichung je Region.
    """
    if diff.shape != (1280,):
        return None
    intensity = diff[:1024].reshape(32, 32)
    gradient = diff[1024:].reshape(16, 16)
    intensity_blocks = (
        intensity.reshape(4, 8, 4, 8).transpose(0, 2, 1, 3).reshape(16, -1)
    )
    gradient_blocks = (
        gradient.reshape(4, 4, 4, 4).transpose(0, 2, 1, 3).reshape(16, -1)
    )
    return (
        np.square(intensity_blocks).sum(axis=1)
        + np.square(gradient_blocks).sum(axis=1)
    )


def face_distance(
    known_encodings: List[np.ndarray],
    face_encoding: np.ndarray,
) -> np.ndarray:
    """Verdeckungsrobuster Abstand zwischen Kodierungen.

    Für die 1280-D-Standardkodierung wird die Distanz blockweise über 16
    Gesichtsregionen berechnet; die am stärksten abweichenden Regionen
    (Anteil ``FACE_MATCH_OCCLUSION_TRIM``) werden verworfen und das Ergebnis
    auf die volle Fläche reskaliert. Dadurch bleibt ein Gesicht auch mit
    Teilverdeckung (Headset, Brille, Mikrofonbügel) erkennbar, während
    fremde Gesichter – deren Abweichung über alle Regionen verteilt ist –
    weiterhin deutlich über der Toleranz liegen.

    Für abweichende Kodierungsformate wird der euklidische Abstand genutzt.
    """
    if not known_encodings:
        return np.array([])

    trim_ratio = max(0.0, min(0.4, _config_value("FACE_MATCH_OCCLUSION_TRIM", 0.25)))
    distances = []
    for known in known_encodings:
        if known.shape != face_encoding.shape:
            distances.append(float("inf"))
            continue
        diff = (known - face_encoding).astype(np.float64, copy=False)
        blocks = _blockwise_squared_diff(diff) if trim_ratio > 0 else None
        if blocks is None:
            distances.append(float(np.linalg.norm(diff)))
            continue
        total = blocks.shape[0]
        keep = max(8, total - int(round(total * trim_ratio)))
        kept = np.sort(blocks)[:keep]
        # Reskalierung auf die volle Regionenzahl hält die Distanz
        # vergleichbar mit der bisherigen L2-Skala (Toleranz unverändert).
        distances.append(float(np.sqrt(kept.sum() * (total / float(keep)))))
    return np.array(distances, dtype=np.float64)


def compare_faces(
    known_encodings: List[np.ndarray],
    face_encoding: np.ndarray,
    tolerance: float = 0.9,
) -> List[bool]:
    """Vergleicht bekannte Kodierungen mit einer neuen Kodierung."""
    distances = face_distance(known_encodings, face_encoding)
    return [float(distance) <= tolerance for distance in distances]


def _pair_score(scores: Dict[str, float], left: str, right: str) -> float:
    """Maximum eines Links/Rechts-Blendshape-Paares.

    ``max`` statt Mittelwert, damit auch einseitige Ausdrücke (z. B.
    schiefes Lächeln) voll gewertet werden.
    """
    return max(float(scores.get(left, 0.0)), float(scores.get(right, 0.0)))


def _infer_emotion_from_blendshapes(
    scores: Optional[Dict[str, float]],
    min_confidence: float,
) -> Dict[str, object]:
    """Leitet eine Emotion aus FaceBlendshape-Scores ab.

    Verwendet gewichtete Kombinationen der relevanten Action Units mit
    Gegen-Evidenz (z. B. dämpft ein Lächeln "angry"/"sad") und einem
    dynamischen Neutral-Score. Die zurückgegebenen ``scores`` sind auf
    Wahrscheinlichkeiten normalisiert (Summe = 1).
    """
    if not scores:
        return {
            "label": "unknown",
            "confidence": 0.0,
            "source": "none",
            "scores": {},
        }

    def s(name: str) -> float:
        return float(scores.get(name, 0.0))

    smile = _pair_score(scores, "mouthSmileLeft", "mouthSmileRight")
    frown = _pair_score(scores, "mouthFrownLeft", "mouthFrownRight")
    brow_down = _pair_score(scores, "browDownLeft", "browDownRight")
    brow_inner_up = s("browInnerUp")
    brow_outer_up = _pair_score(scores, "browOuterUpLeft", "browOuterUpRight")
    eye_wide = _pair_score(scores, "eyeWideLeft", "eyeWideRight")
    eye_squint = _pair_score(scores, "eyeSquintLeft", "eyeSquintRight")
    cheek_squint = _pair_score(scores, "cheekSquintLeft", "cheekSquintRight")
    jaw_open = s("jawOpen")
    mouth_press = _pair_score(scores, "mouthPressLeft", "mouthPressRight")
    mouth_stretch = _pair_score(scores, "mouthStretchLeft", "mouthStretchRight")
    nose_sneer = _pair_score(scores, "noseSneerLeft", "noseSneerRight")
    upper_lip_up = _pair_score(scores, "mouthUpperUpLeft", "mouthUpperUpRight")
    lower_lip_down = _pair_score(scores, "mouthLowerDownLeft", "mouthLowerDownRight")
    mouth_shrug_lower = s("mouthShrugLower")

    raw = {
        "happy": (
            1.2 * smile + 0.4 * cheek_squint + 0.2 * eye_squint
            - 0.8 * frown - 0.3 * brow_down
        ),
        "sad": (
            1.0 * frown + 0.7 * brow_inner_up + 0.4 * mouth_shrug_lower
            - 1.2 * smile - 0.3 * jaw_open - 0.3 * eye_wide
        ),
        "angry": (
            1.1 * brow_down + 0.3 * eye_squint + 0.4 * mouth_press
            + 0.4 * nose_sneer - 1.0 * smile
        ),
        "surprised": (
            0.9 * jaw_open + 0.9 * brow_outer_up + 0.6 * eye_wide
            - 0.8 * brow_down - 0.6 * smile
        ),
        "fearful": (
            0.9 * eye_wide + 0.7 * mouth_stretch + 0.6 * brow_inner_up
            + 0.2 * jaw_open - 1.0 * smile - 0.4 * brow_down
        ),
        "disgusted": (
            1.1 * nose_sneer + 0.7 * upper_lip_up + 0.3 * lower_lip_down
            - 0.8 * smile
        ),
    }

    # Stärkste beobachtete Aktivierung – bei entspanntem Gesicht dominiert
    # der Neutral-Score, bei deutlicher Mimik fällt er schnell ab.
    activation = max(
        smile, frown, brow_down, brow_inner_up, brow_outer_up,
        eye_wide, jaw_open, nose_sneer, mouth_stretch, mouth_press,
        upper_lip_up,
    )
    raw["neutral"] = max(0.0, 0.6 - 1.2 * activation)

    clipped = {label: max(0.0, value) for label, value in raw.items()}
    total = float(sum(clipped.values()))
    if total <= 1e-8:
        # Keine Evidenz für irgendetwas → neutral.
        probs = {label: 0.0 for label in clipped}
        probs["neutral"] = 1.0
    else:
        probs = {label: value / total for label, value in clipped.items()}

    best_label, best_prob = max(probs.items(), key=lambda item: item[1])
    confidence = float(max(0.0, min(1.0, best_prob)))
    label = best_label if confidence >= min_confidence else "unknown"

    return {
        "label": label,
        "confidence": confidence,
        "source": "blendshape",
        "scores": probs,
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
    for bbox, _, blendshape_scores, _ in detections:
        result = _infer_emotion_from_blendshapes(blendshape_scores, threshold)
        result["bbox"] = bbox
        emotions.append(result)
    return emotions


def _run_worker(file_path: str, extra_args: List[str], timeout: int, task_label: str) -> Dict[str, object]:
    """Führt den Worker-Prozess aus und liefert das JSON-Payload.

    Gemeinsame Basis für Kodierung, Analyse und Enrollment (identisches
    Subprozess-, Fehler- und Parsing-Verhalten).
    """
    if not _WORKER_SCRIPT.exists():
        raise FileNotFoundError(f"Worker-Skript nicht gefunden: {_WORKER_SCRIPT}")

    try:
        result = subprocess.run(
            [sys.executable, str(_WORKER_SCRIPT), file_path, *extra_args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{task_label} hat das Zeitlimit überschritten.") from exc

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
        raise RuntimeError(f"{task_label} fehlgeschlagen: {details}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ungültige Antwort vom Worker ({task_label}).") from exc


def safe_face_encodings_from_file(file_path: str, timeout: int = 30) -> List[np.ndarray]:
    """Liest Gesichtskodierungen in einem separaten Prozess aus einer Bilddatei."""
    payload = _run_worker(file_path, [], timeout, "Gesichtserkennung")
    return [np.array(encoding, dtype=np.float64) for encoding in payload.get("encodings", [])]


def safe_face_analysis_from_file(file_path: str, timeout: int = 30) -> Dict[str, object]:
    """Liefert Gesichtskodierungen plus optionale Emotionsschätzung aus Worker."""
    payload = _run_worker(file_path, ["--with-emotions"], timeout, "Gesichtsanalyse")
    return {
        "encodings": [np.array(encoding, dtype=np.float64) for encoding in payload.get("encodings", [])],
        "emotions": payload.get("emotions", []),
    }


def safe_face_enrollment_from_file(file_path: str, timeout: int = 45) -> Dict[str, object]:
    """Liefert Kodierungen UND 3D-Geometrie aus einer Bilddatei (isolierter Prozess).

    Wird beim Hinzufügen von Trainingsbildern genutzt, um zusätzlich zur
    1280-D Kodierung das 3D-Referenzmodell des Nutzers aufzubauen.
    """
    payload = _run_worker(file_path, ["--with-geometry"], timeout, "Gesichtserfassung")
    return {
        "encodings": [
            np.array(encoding, dtype=np.float64)
            for encoding in payload.get("encodings", [])
        ],
        "geometry": [
            np.array(geom, dtype=np.float64)
            for geom in payload.get("geometry", [])
        ],
    }


def backend_info() -> dict:
    """Diagnose-Information über den aktiven Backend (für Logs/Tests)."""
    landmarker = _ensure_landmarker()
    return {
        "backend": "mediapipe" if landmarker is not None else "opencv-cascade",
        "model_path": str(_MP_MODEL_PATH) if _MP_MODEL_PATH else None,
        "available": bool(landmarker is not None),
        "blendshapes": bool(_MP_BLENDSHAPES),
    }

"""Tests für Liveness/Anti-Spoofing (face_liveness) und 3D-Modell-Speicherung."""

import time

import numpy as np
import pytest

from face_liveness import (
    LivenessConfig,
    LivenessMonitor,
    aggregate_geometries,
    combine_geometry_models,
    deserialize_geometry,
    geometry_rms_distance,
    head_pose_angles,
    serialize_geometry,
    texture_live_score,
)


# ---------------------------------------------------------------------------
# 3D-Geometrie
# ---------------------------------------------------------------------------

def _random_geometry(n: int = 300, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, 3)).astype(np.float64)


def test_geometry_rms_distance_identical_is_near_zero():
    geom = _random_geometry()
    assert geometry_rms_distance(geom, geom.copy()) < 1e-6


def test_geometry_rms_distance_rotation_invariant():
    geom = _random_geometry()
    # Rotation um die Z-Achse darf den Abstand nicht vergrößern (Kabsch).
    theta = 0.7
    rot = np.array([
        [np.cos(theta), -np.sin(theta), 0.0],
        [np.sin(theta), np.cos(theta), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rotated = geom @ rot.T
    assert geometry_rms_distance(geom, rotated) < 1e-6


def test_geometry_rms_distance_different_faces_larger():
    a = _random_geometry(seed=1)
    b = _random_geometry(seed=2)
    assert geometry_rms_distance(a, b) > 0.3


def test_geometry_rms_distance_invalid_returns_inf():
    assert geometry_rms_distance(np.empty((0, 3)), _random_geometry()) == float("inf")
    assert geometry_rms_distance(_random_geometry(), _random_geometry(n=100)) == float("inf")


def test_serialize_deserialize_geometry_roundtrip():
    geom = _random_geometry()
    blob = serialize_geometry(geom)
    restored = deserialize_geometry(blob)
    assert restored is not None
    assert restored.shape == geom.shape
    assert np.allclose(restored, geom, atol=1e-5)


def test_deserialize_geometry_handles_garbage():
    assert deserialize_geometry(b"") is None
    assert deserialize_geometry(b"\x01\x02\x03") is None  # nicht durch 3 teilbar


def test_aggregate_geometries_averages_samples():
    geom = _random_geometry()
    agg = aggregate_geometries([geom, geom.copy(), geom.copy()])
    assert agg is not None
    assert geometry_rms_distance(agg, geom) < 1e-6


def test_aggregate_geometries_empty_returns_none():
    assert aggregate_geometries([]) is None


def test_combine_geometry_models_weights_samples():
    geom = _random_geometry()
    model, total = combine_geometry_models(None, 0, aggregate_geometries([geom]), 1)
    assert model is not None
    assert total == 1
    combined, total2 = combine_geometry_models(model, 1, aggregate_geometries([geom]), 2)
    assert combined is not None
    assert total2 == 3


# ---------------------------------------------------------------------------
# Kopf-Pose
# ---------------------------------------------------------------------------

def test_head_pose_identity_is_zero():
    angles = head_pose_angles(np.eye(4))
    assert angles is not None
    yaw, pitch, roll = angles
    assert abs(yaw) < 1e-6 and abs(pitch) < 1e-6 and abs(roll) < 1e-6


def test_head_pose_none_returns_none():
    assert head_pose_angles(None) is None


# ---------------------------------------------------------------------------
# Passive Textur
# ---------------------------------------------------------------------------

def test_texture_live_score_in_range():
    rng = np.random.default_rng(0)
    image = rng.integers(0, 256, size=(200, 200, 3), dtype=np.uint8)
    score = texture_live_score(image, (20, 180, 180, 20))
    assert 0.0 <= score <= 1.0


def test_texture_live_score_tiny_bbox_is_indeterminate():
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    assert texture_live_score(image, (0, 5, 5, 0)) == 0.5


# ---------------------------------------------------------------------------
# LivenessMonitor
# ---------------------------------------------------------------------------

def test_monitor_disabled_always_live():
    monitor = LivenessMonitor(LivenessConfig(enabled=False))
    result = monitor.update({}, None, None, 0.0)
    assert result.is_live is True


def test_monitor_texture_failure_is_spoof_signal():
    cfg = LivenessConfig(
        require_blink=False, require_parallax=False, active_challenge_enabled=False
    )
    monitor = LivenessMonitor(cfg)
    result = monitor.update({}, None, None, texture_score=0.05)
    assert result.is_live is False
    assert "textur" in result.reasons


def test_monitor_blink_detection_unlocks():
    cfg = LivenessConfig(
        require_blink=True, require_parallax=False, active_challenge_enabled=False
    )
    monitor = LivenessMonitor(cfg)
    # Augen geschlossen -> noch kein Blinzeln
    res_closed = monitor.update({"eyeBlinkLeft": 0.8}, None, None, texture_score=0.9)
    assert res_closed.is_live is False
    assert "kein_blinzeln" in res_closed.reasons
    # Augen wieder offen -> Blinzeln registriert
    res_open = monitor.update({"eyeBlinkLeft": 0.0}, None, None, texture_score=0.9)
    assert res_open.blink_ok is True
    assert res_open.is_live is True


def test_monitor_parallax_flat_photo_blocks():
    cfg = LivenessConfig(
        require_blink=False,
        require_parallax=True,
        active_challenge_enabled=False,
        parallax_min_yaw_range=8.0,
        parallax_min_slope=0.004,
    )
    monitor = LivenessMonitor(cfg)
    now = time.time()
    # Kopf dreht deutlich (Yaw -10..+10), aber Nasen-Offset bleibt konstant
    # => flaches Foto.
    monitor._motion_samples = [
        (now, float(yaw), 0.0) for yaw in range(-10, 11, 3)
    ]
    ok, meaningful = monitor._parallax_ok()
    assert meaningful is True
    assert ok is False


def test_monitor_parallax_real_face_passes():
    cfg = LivenessConfig(
        require_blink=False,
        require_parallax=True,
        active_challenge_enabled=False,
        parallax_min_yaw_range=8.0,
        parallax_min_slope=0.004,
    )
    monitor = LivenessMonitor(cfg)
    now = time.time()
    # Nasen-Offset korreliert mit Yaw (echte Parallaxe).
    monitor._motion_samples = [
        (now, float(yaw), 0.01 * yaw) for yaw in range(-10, 11, 3)
    ]
    ok, meaningful = monitor._parallax_ok()
    assert meaningful is True
    assert ok is True


def test_monitor_parallax_insufficient_motion_not_meaningful():
    cfg = LivenessConfig(require_parallax=True)
    monitor = LivenessMonitor(cfg)
    now = time.time()
    monitor._motion_samples = [(now, 1.0, 0.0), (now, 1.5, 0.0)]
    ok, meaningful = monitor._parallax_ok()
    assert meaningful is False


def test_monitor_geometry_required_blocks_without_model():
    cfg = LivenessConfig(
        require_blink=False,
        require_parallax=False,
        active_challenge_enabled=False,
        geometry_required=True,
    )
    monitor = LivenessMonitor(cfg)
    result = monitor.update({}, None, None, texture_score=0.9, geometry_rms=None)
    assert result.geometry_ok is False
    assert "geometrie" in result.reasons


def test_monitor_active_challenge_blink_passes():
    cfg = LivenessConfig(
        require_blink=False,
        require_parallax=False,
        active_challenge_enabled=True,
    )
    monitor = LivenessMonitor(cfg)
    monitor._challenge_kind = "blink"
    monitor._challenge_started_at = time.time()
    monitor._challenge_baseline_blinks = 0
    # Blinzeln ausführen -> Challenge erfüllt
    monitor.update({"eyeBlinkLeft": 0.8}, None, None, texture_score=0.9)
    result = monitor.update({"eyeBlinkLeft": 0.0}, None, None, texture_score=0.9)
    assert monitor.challenge_satisfied() is True
    assert result.is_live is True


# ---------------------------------------------------------------------------
# 3D-Modell-Speicherung in der Datenbank
# ---------------------------------------------------------------------------

def test_db_geometry_model_upsert_and_get(db_manager):
    user_id = db_manager.add_user("alice", "123456")
    geom = _random_geometry()
    db_manager.upsert_face_geometry_model(user_id, serialize_geometry(geom), 3)

    stored = db_manager.get_face_geometry_model(user_id)
    assert stored is not None
    blob, num = stored
    assert num == 3
    restored = deserialize_geometry(blob)
    assert restored is not None
    assert np.allclose(restored, geom, atol=1e-5)


def test_db_geometry_model_upsert_overwrites(db_manager):
    user_id = db_manager.add_user("bob", "123456")
    db_manager.upsert_face_geometry_model(user_id, serialize_geometry(_random_geometry(seed=1)), 1)
    db_manager.upsert_face_geometry_model(user_id, serialize_geometry(_random_geometry(seed=2)), 5)
    _, num = db_manager.get_face_geometry_model(user_id)
    assert num == 5


def test_db_get_all_geometry_models(db_manager):
    uid_a = db_manager.add_user("alice", "123456")
    uid_b = db_manager.add_user("bob", "123456")
    db_manager.upsert_face_geometry_model(uid_a, serialize_geometry(_random_geometry(seed=1)), 2)
    db_manager.upsert_face_geometry_model(uid_b, serialize_geometry(_random_geometry(seed=2)), 4)

    models = {name: (blob, n) for name, blob, n in db_manager.get_all_face_geometry_models()}
    assert set(models) == {"alice", "bob"}
    assert models["alice"][1] == 2
    assert models["bob"][1] == 4


def test_db_get_geometry_model_missing_returns_none(db_manager):
    user_id = db_manager.add_user("nobody", "123456")
    assert db_manager.get_face_geometry_model(user_id) is None

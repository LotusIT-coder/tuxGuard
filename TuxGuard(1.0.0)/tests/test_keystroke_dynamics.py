"""Tests für die Freitext-Tippmustererkennung (Keystroke Dynamics)."""

import pytest

import keystroke_dynamics as ksd


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

class _Event:
    """Minimaler Ersatz für ein Tk-/pynput-Event (nur keysym/char)."""

    def __init__(self, keysym: str, char: str):
        self.keysym = keysym
        self.char = char


def _sample(dwell, flight):
    return {"dwell": list(dwell), "flight": list(flight)}


def _consistent_samples(count=4, n_dwell=60, base_dwell=100.0, base_flight=150.0):
    """Erzeugt mehrere sehr ähnliche Freitext-Proben."""
    samples = []
    for k in range(count):
        jitter = (k % 3) - 1  # -1, 0, 1
        dwell = [base_dwell + jitter for _ in range(n_dwell)]
        flight = [base_flight + jitter for _ in range(n_dwell - 1)]
        samples.append(_sample(dwell, flight))
    return samples


# ---------------------------------------------------------------------------
# build_profile
# ---------------------------------------------------------------------------

def test_build_profile_aggregates_mean_and_std():
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=50))
    assert profile is not None
    assert profile["version"] == ksd.PROFILE_VERSION
    assert profile["kind"] == ksd.PROFILE_KIND
    assert profile["dwell_n"] == 4 * 50
    assert profile["dwell_mean"] == pytest.approx(100.0, abs=1.0)
    assert profile["flight_n"] == 4 * 49
    assert profile["flight_mean"] == pytest.approx(150.0, abs=1.0)
    assert profile["n_keystrokes"] == 4 * 50


def test_build_profile_handles_varying_lengths():
    samples = _consistent_samples(count=3, n_dwell=40)
    samples.append(_sample([100.0] * 10, [150.0] * 9))  # andere Länge ist ok
    profile = ksd.build_profile(samples)
    assert profile is not None
    assert profile["dwell_n"] == 3 * 40 + 10


def test_build_profile_returns_none_without_dwell():
    assert ksd.build_profile([]) is None
    assert ksd.build_profile([{"dwell": [], "flight": []}]) is None


# ---------------------------------------------------------------------------
# match_distance / is_match / match_confidence
# ---------------------------------------------------------------------------

def test_match_distance_low_for_similar_sample():
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=60))
    similar = _sample([100.0] * 30, [150.0] * 29)
    distance = ksd.match_distance(profile, similar, std_floor_ms=8.0)
    assert distance < 1.8
    assert ksd.is_match(profile, similar, threshold=1.8, std_floor_ms=8.0) is True


def test_match_distance_high_for_different_sample():
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=60))
    different = _sample([400.0] * 30, [800.0] * 29)
    distance = ksd.match_distance(profile, different, std_floor_ms=8.0)
    assert distance > 1.8
    assert ksd.is_match(profile, different, threshold=1.8, std_floor_ms=8.0) is False


def test_match_distance_inf_on_empty_sample():
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=60))
    assert ksd.match_distance(profile, _sample([], [])) == float("inf")
    assert ksd.match_distance(None, _sample([100.0], [])) == float("inf")


def test_match_distance_dwell_only_sample():
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=60))
    # Probe ohne Flugzeiten ist gültig (nur Haltezeit zählt).
    dwell_only = _sample([100.0] * 30, [])
    distance = ksd.match_distance(profile, dwell_only, std_floor_ms=8.0)
    assert distance < 1.8


def test_match_confidence_bounds():
    assert ksd.match_confidence(0.0, 1.8) == pytest.approx(1.0)
    assert ksd.match_confidence(1.8, 1.8) == pytest.approx(0.5)
    assert ksd.match_confidence(float("inf"), 1.8) == 0.0
    assert 0.0 <= ksd.match_confidence(1.0, 1.8) <= 1.0


# ---------------------------------------------------------------------------
# update_profile (adaptives Lernen)
# ---------------------------------------------------------------------------

def test_update_profile_grows_counts_and_keeps_kind():
    profile = ksd.build_profile(_consistent_samples(count=2, n_dwell=30))
    before = profile["dwell_n"]
    sample = _sample([100.0] * 20, [150.0] * 19)
    updated = ksd.update_profile(profile, sample, max_keystrokes=10000)
    assert updated["kind"] == ksd.PROFILE_KIND
    assert updated["dwell_n"] == before + 20
    assert updated["dwell_mean"] == pytest.approx(100.0, abs=1.0)


def test_update_profile_caps_at_max_keystrokes():
    profile = ksd.build_profile(_consistent_samples(count=2, n_dwell=30))
    profile["dwell_n"] = 2000
    sample = _sample([100.0] * 20, [150.0] * 19)
    updated = ksd.update_profile(profile, sample, max_keystrokes=2000)
    assert updated["dwell_n"] == 2000


def test_update_profile_ignores_empty_sample():
    profile = ksd.build_profile(_consistent_samples(count=2, n_dwell=30))
    updated = ksd.update_profile(profile, _sample([], []), max_keystrokes=2000)
    assert updated["dwell_n"] == profile["dwell_n"]


# ---------------------------------------------------------------------------
# Serialisierung
# ---------------------------------------------------------------------------

def test_serialize_and_deserialize_roundtrip():
    profile = ksd.build_profile(_consistent_samples(count=3, n_dwell=40))
    blob = ksd.serialize_profile(profile)
    assert isinstance(blob, str)
    restored = ksd.deserialize_profile(blob)
    assert restored is not None
    assert restored["dwell_mean"] == profile["dwell_mean"]
    assert restored["flight_mean"] == profile["flight_mean"]


def test_deserialize_handles_invalid_input():
    assert ksd.deserialize_profile(None) is None
    assert ksd.deserialize_profile("") is None
    assert ksd.deserialize_profile("kein json") is None
    assert ksd.deserialize_profile('{"foo": 1}') is None


# ---------------------------------------------------------------------------
# EnrollmentCollector
# ---------------------------------------------------------------------------

def test_enrollment_collector_collects_until_complete():
    collector = ksd.EnrollmentCollector(required_keystrokes=50)
    assert collector.complete is False
    collector.add(_sample([100.0] * 30, [150.0] * 29))
    assert collector.complete is False
    total = collector.add(_sample([100.0] * 30, [150.0] * 29))
    assert total == 60
    assert collector.complete is True
    assert collector.build() is not None


def test_enrollment_collector_build_none_when_incomplete():
    collector = ksd.EnrollmentCollector(required_keystrokes=100)
    collector.add(_sample([100.0] * 10, [150.0] * 9))
    assert collector.build() is None


# ---------------------------------------------------------------------------
# KeystrokeRecorder (mit simulierten Events)
# ---------------------------------------------------------------------------

def test_recorder_collects_dwell_and_flight():
    recorder = ksd.KeystrokeRecorder()
    for ch in "abcdef":
        recorder.on_press(_Event(ch, ch))
        recorder.on_release(_Event(ch, ch))
    assert recorder.sample_size == 6
    sample = recorder.take_sample(min_keystrokes=6)
    assert sample is not None
    assert len(sample["dwell"]) == 6
    assert len(sample["flight"]) == 5
    # take_sample setzt zurück.
    assert recorder.sample_size == 0


def test_recorder_modifiers_do_not_break_run():
    recorder = ksd.KeystrokeRecorder()
    recorder.on_press(_Event("a", "a"))
    recorder.on_release(_Event("a", "a"))
    # Shift drücken (Modifier) -> Lauf bleibt erhalten.
    recorder.on_press(_Event("Shift_L", ""))
    recorder.on_release(_Event("Shift_L", ""))
    recorder.on_press(_Event("B", "B"))
    recorder.on_release(_Event("B", "B"))
    sample = recorder.take_sample(min_keystrokes=2)
    assert sample is not None
    assert len(sample["dwell"]) == 2
    # Flugzeit zwischen 'a' und 'B' bleibt erhalten (Shift unterbricht nicht).
    assert len(sample["flight"]) == 1


def test_recorder_edit_key_breaks_run():
    recorder = ksd.KeystrokeRecorder()
    recorder.on_press(_Event("a", "a"))
    recorder.on_release(_Event("a", "a"))
    recorder.on_press(_Event("BackSpace", ""))  # Editiertaste -> Lauf endet
    recorder.on_release(_Event("BackSpace", ""))
    recorder.on_press(_Event("b", "b"))
    recorder.on_release(_Event("b", "b"))
    sample = recorder.take_sample(min_keystrokes=2)
    assert sample is not None
    # Zwei Haltezeiten, aber keine Flugzeit über den Bruch hinweg.
    assert len(sample["dwell"]) == 2
    assert len(sample["flight"]) == 0


def test_recorder_take_sample_none_when_too_few():
    recorder = ksd.KeystrokeRecorder()
    for ch in "ab":
        recorder.on_press(_Event(ch, ch))
        recorder.on_release(_Event(ch, ch))
    assert recorder.take_sample(min_keystrokes=6) is None


def test_recorder_reset_clears_state():
    recorder = ksd.KeystrokeRecorder()
    for ch in "abcdef":
        recorder.on_press(_Event(ch, ch))
        recorder.on_release(_Event(ch, ch))
    recorder.reset()
    assert recorder.sample_size == 0
    assert recorder.take_sample(min_keystrokes=1) is None


# ---------------------------------------------------------------------------
# pynput-Adapter
# ---------------------------------------------------------------------------

class _PynKey:
    def __init__(self, char=None, name=None):
        self.char = char
        self.name = name


def test_adapt_pynput_printable_char():
    ev = ksd._adapt_pynput_key(_PynKey(char="x"))
    assert ev.char == "x"
    assert ev.keysym == "x"


def test_adapt_pynput_space():
    ev = ksd._adapt_pynput_key(_PynKey(char=None, name="space"))
    assert ev.char == " "
    assert ev.keysym == "space"


def test_adapt_pynput_modifier_has_empty_char():
    ev = ksd._adapt_pynput_key(_PynKey(char=None, name="shift"))
    assert ev.char == ""
    assert ev.keysym == "shift"


def test_adapt_pynput_special_key_breaks_run():
    ev = ksd._adapt_pynput_key(_PynKey(char=None, name="enter"))
    assert ev.char == ""


# ---------------------------------------------------------------------------
# KeystrokeMonitor (ohne pynput im Dev-Env -> degradiert sauber)
# ---------------------------------------------------------------------------

def test_monitor_start_returns_false_without_pynput():
    cfg = ksd.KeystrokeConfig()
    samples = []
    monitor = ksd.KeystrokeMonitor(cfg, samples.append)
    # In der Dev-Umgebung ist pynput nicht installiert -> start() == False.
    started = monitor.start()
    if not started:
        assert monitor.running is False
    monitor.stop()


def test_monitor_disabled_config_does_not_start():
    cfg = ksd.KeystrokeConfig(enabled=False)
    monitor = ksd.KeystrokeMonitor(cfg, lambda s: None)
    assert monitor.start() is False
    assert monitor.running is False


# ---------------------------------------------------------------------------
# KeystrokeConfig
# ---------------------------------------------------------------------------

def test_config_from_app_config_reads_values():
    from config import Config

    cfg = ksd.KeystrokeConfig.from_app_config(Config)
    assert isinstance(cfg.enabled, bool)
    assert cfg.min_enrollment_keystrokes >= 1
    assert cfg.match_threshold > 0
    assert cfg.match_window_keystrokes >= 1


# ---------------------------------------------------------------------------
# Datenbank-Methoden
# ---------------------------------------------------------------------------

def test_db_upsert_and_get_keystroke_profile(db_manager):
    user_id = db_manager.add_user("tippnutzer", "123456")
    profile = ksd.build_profile(_consistent_samples(count=4, n_dwell=50))
    blob = ksd.serialize_profile(profile)

    db_manager.upsert_keystroke_profile(
        user_id, blob, profile["n_keystrokes"], 0)

    assert db_manager.has_keystroke_profile(user_id) is True
    assert db_manager.get_keystroke_profile(user_id) == blob
    assert db_manager.get_keystroke_profile_by_name("tippnutzer") == blob


def test_db_upsert_keystroke_profile_updates(db_manager):
    user_id = db_manager.add_user("tippnutzer", "123456")
    p1 = ksd.serialize_profile(ksd.build_profile(_consistent_samples(count=4, n_dwell=50)))
    p2 = ksd.serialize_profile(ksd.build_profile(_consistent_samples(count=5, n_dwell=50)))

    db_manager.upsert_keystroke_profile(user_id, p1, 200, 0)
    db_manager.upsert_keystroke_profile(user_id, p2, 250, 0)

    assert db_manager.get_keystroke_profile(user_id) == p2


def test_db_get_all_keystroke_profiles(db_manager):
    uid1 = db_manager.add_user("nutzer_a", "123456")
    uid2 = db_manager.add_user("nutzer_b", "654321")
    blob_a = ksd.serialize_profile(ksd.build_profile(_consistent_samples(count=4, n_dwell=50)))
    blob_b = ksd.serialize_profile(ksd.build_profile(_consistent_samples(count=5, n_dwell=50)))
    db_manager.upsert_keystroke_profile(uid1, blob_a, 200, 0)
    db_manager.upsert_keystroke_profile(uid2, blob_b, 250, 0)

    rows = db_manager.get_all_keystroke_profiles()
    by_name = {name: blob for _uid, name, blob in rows}
    assert by_name["nutzer_a"] == blob_a
    assert by_name["nutzer_b"] == blob_b


def test_db_get_keystroke_profile_missing(db_manager):
    assert db_manager.get_keystroke_profile(999) is None
    assert db_manager.get_keystroke_profile_by_name("unbekannt") is None
    assert db_manager.has_keystroke_profile(999) is False


def test_db_delete_keystroke_profile(db_manager):
    user_id = db_manager.add_user("tippnutzer", "123456")
    blob = ksd.serialize_profile(ksd.build_profile(_consistent_samples(count=4, n_dwell=50)))
    db_manager.upsert_keystroke_profile(user_id, blob, 200, 0)
    db_manager.delete_keystroke_profile(user_id)
    assert db_manager.has_keystroke_profile(user_id) is False

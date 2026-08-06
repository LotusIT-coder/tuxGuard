import os
import threading
import types
from pathlib import Path
from unittest.mock import Mock

import cv2
import pytest
import tkinter as tk

from camera import CameraManager
from config import Config
from face_mediapipe import face_encodings as mp_face_encodings
from face_mediapipe import face_locations as mp_face_locations
from simple_ui import PasswordDialog
from tuxguard_refactored import TuxGuardApplication


DISPLAY_AVAILABLE = bool(os.environ.get("DISPLAY"))


def _camera_available() -> bool:
    for index in range(5):
        cap = cv2.VideoCapture(index)
        try:
            if cap.isOpened():
                ok, _frame = cap.read()
                if ok:
                    return True
        finally:
            if cap is not None and cap.isOpened():
                cap.release()
    return False


CAMERA_AVAILABLE = _camera_available()


@pytest.fixture
def tk_root():
    if not DISPLAY_AVAILABLE:
        pytest.skip("Kein DISPLAY verfügbar für Tk-Integrationstests.")
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.update_idletasks()
            root.destroy()
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.requires_display
@pytest.mark.parametrize(("dialog_class", "entry_name"), [(PasswordDialog, "password_entry")])
def test_unlock_dialog_maps_before_replacing_lock_overlay_grab(
    monkeypatch, tk_root, dialog_class, entry_name,
):
    tk_root.deiconify()
    tk_root.update_idletasks()
    lock_overlay = tk.Toplevel(tk_root)
    lock_overlay.geometry("320x220+0+0")
    lock_overlay.overrideredirect(True)
    lock_overlay.attributes("-topmost", True)
    lock_overlay.update_idletasks()
    lock_overlay.grab_set()
    observed = {}
    original_toplevel = tk.Toplevel

    class ObservingToplevel(original_toplevel):
        def grab_set(self, *args, **kwargs):
            if self.master is lock_overlay:
                observed["viewable_at_grab"] = bool(self.winfo_viewable())
            return super().grab_set(*args, **kwargs)

    monkeypatch.setattr("simple_ui.tk.Toplevel", ObservingToplevel)
    dialog = dialog_class(lock_overlay, title="Entsperren", reason="Test")

    def dismiss_dialog():
        observed["viewable_after_show"] = bool(dialog.dialog.winfo_viewable())
        observed["dialog_has_grab"] = lock_overlay.grab_current() is dialog.dialog
        getattr(dialog, entry_name).insert(0, "123456")
        dialog._cancel()

    try:
        tk_root.after(50, dismiss_dialog)
        result = dialog.show()

        assert result is None
        assert observed["viewable_at_grab"] is True
        assert observed["viewable_after_show"] is True
        assert observed["dialog_has_grab"] is True
        assert lock_overlay.grab_current() is lock_overlay
    finally:
        try:
            lock_overlay.grab_release()
            lock_overlay.destroy()
        except tk.TclError:
            pass


@pytest.mark.integration
@pytest.mark.requires_display
def test_tray_minimize_uses_real_app_icon(monkeypatch, tk_root):
    created = {}

    class DummyIcon:
        def __init__(self, name, image, title, menu):
            created["name"] = name
            created["image"] = image
            created["title"] = title
            created["menu"] = menu

        def run(self):
            created["run_called"] = True

        def stop(self):
            created["stop_called"] = True

    monkeypatch.setattr("tuxguard_refactored.pystray.Icon", DummyIcon)
    monkeypatch.setattr("tuxguard_refactored.pystray.Menu", lambda *args: list(args))
    monkeypatch.setattr("tuxguard_refactored.pystray.MenuItem", lambda *args: tuple(args))

    app = object.__new__(TuxGuardApplication)
    app.root = tk_root
    app.logger = types.SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
    app.monitoring_active = False
    app.tray_icon = None
    app.active_threads = []
    app._restore_from_tray = Mock()
    app._toggle_monitoring_from_tray = Mock()
    app._quit_from_tray = Mock()

    app._minimize_to_tray()

    assert app.tray_icon is not None
    assert created["name"] == Config.APP_NAME
    assert created["title"] == Config.APP_NAME
    assert created["image"].size[0] <= Config.TRAY_ICON_SIZE[0]
    assert created["image"].size[1] <= Config.TRAY_ICON_SIZE[1]


@pytest.mark.integration
@pytest.mark.requires_display
def test_lock_screen_key_event_triggers_admin_unlock_when_forced(monkeypatch, tk_root):
    original_toplevel = tk.Toplevel

    class SafeToplevel(original_toplevel):
        def attributes(self, name, value=None):
            if name in {"-fullscreen", "-topmost"}:
                return None
            return super().attributes(name, value)

    monkeypatch.setattr("tuxguard_refactored.tk.Toplevel", SafeToplevel)

    app = object.__new__(TuxGuardApplication)
    app.root = tk_root
    app.logger = types.SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
    app.lock_target = "screen"
    app.security_mode = "self_unlock"
    app.security_lock_active = False
    app.security_lock_reason = ""
    app.security_lock_window = None
    app.security_lock_status_label = None
    app.security_lock_unlock_pending = False
    app.force_admin_unlock_required = False
    app.current_user = "alice"
    app._lock_system_session = Mock()
    app._prompt_lock_unlock = Mock()
    app._update_security_lock_status = TuxGuardApplication._update_security_lock_status.__get__(app, TuxGuardApplication)

    app._activate_security_lock("Admin Unlock Test", force_admin_password=True)
    app.security_lock_window.update_idletasks()
    app.security_lock_window.focus_force()
    app.security_lock_window.event_generate("<Button-1>", x=10, y=10)
    app.security_lock_window.update()

    assert app._prompt_lock_unlock.called
    app.security_lock_window.destroy()


@pytest.mark.integration
@pytest.mark.requires_camera
def test_live_opencv_camera_path_reads_real_frame():
    if not CAMERA_AVAILABLE:
        pytest.skip("Keine reale Kamera verfügbar.")

    cap = cv2.VideoCapture(0)
    try:
        assert cap.isOpened()
        ok, frame = cap.read()
        assert ok is True
        assert frame is not None
        assert frame.size > 0
    finally:
        if cap.isOpened():
            cap.release()


def test_camera_stop_continues_without_opencv_highgui(monkeypatch):
    manager = object.__new__(CameraManager)
    manager.active_event = threading.Event()
    manager.active_event.set()
    manager.is_active = True
    manager.camera_after_id = None
    manager.video_capture = None
    manager.parent_window = Mock()
    manager.stop_monitoring = Mock()
    manager._emotion_tracks = {}
    monkeypatch.setattr(cv2, "destroyAllWindows", Mock(side_effect=cv2.error("HighGUI unavailable")))

    manager.stop()

    assert manager.active_event.is_set() is False
    assert manager.is_active is False
    manager.stop_monitoring.assert_called_once()


@pytest.mark.integration
@pytest.mark.requires_camera
def test_live_mediapipe_path_processes_real_camera_frame():
    if not CAMERA_AVAILABLE:
        pytest.skip("Keine reale Kamera verfügbar.")

    cap = cv2.VideoCapture(0)
    try:
        assert cap.isOpened()
        ok, frame = cap.read()
        assert ok is True
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = mp_face_locations(rgb)
        encodings = mp_face_encodings(rgb, locations)
        assert isinstance(locations, list)
        assert isinstance(encodings, list)
    finally:
        if cap.isOpened():
            cap.release()


@pytest.mark.integration
@pytest.mark.requires_display
@pytest.mark.requires_camera
def test_camera_manager_real_availability_and_diagnose_path(tk_root):
    if not CAMERA_AVAILABLE:
        pytest.skip("Keine reale Kamera verfügbar.")

    db_stub = types.SimpleNamespace(get_all_face_encodings=lambda: [])
    manager = CameraManager(tk_root, db_stub)

    assert isinstance(manager.is_available, bool)
    diagnosis = manager.diagnose()
    assert "KAMERA-DIAGNOSE" in diagnosis

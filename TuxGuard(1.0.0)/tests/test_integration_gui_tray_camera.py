import os
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
from simple_ui import SimplePinDialog
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
def test_real_pin_dialog_ok_button_and_entry_flow(tk_root):
    dialog = SimplePinDialog(tk_root, title="PIN-Test", reason="Bitte PIN eingeben")
    observed = {}

    def interact():
        buttons = [child for child in dialog.dialog.winfo_children()[0].winfo_children() if isinstance(child, tk.Frame)]
        assert buttons, "Button-Container fehlt"
        button_texts = []
        for child in buttons[0].winfo_children():
            if isinstance(child, tk.Button):
                button_texts.append(child.cget("text"))
        observed["button_texts"] = button_texts
        dialog.pin_entry.insert(0, "123456")
        dialog._ok()

    tk_root.after(100, interact)
    result = dialog.show()

    assert result == "123456"
    assert any("OK" in text for text in observed["button_texts"])
    assert any("Abbrechen" in text for text in observed["button_texts"])


@pytest.mark.integration
@pytest.mark.requires_display
def test_real_pin_dialog_cancel_flow(tk_root):
    dialog = SimplePinDialog(tk_root, title="PIN-Test", reason="Langer Hinweistext fuer GUI-Test")

    tk_root.after(100, dialog._cancel)
    result = dialog.show()

    assert result is None


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
def test_lock_screen_key_event_triggers_strict_unlock(monkeypatch, tk_root):
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
    app.security_mode = "strict_pin"
    app.security_lock_active = False
    app.security_lock_reason = ""
    app.security_lock_window = None
    app.security_lock_status_label = None
    app.security_lock_unlock_pending = False
    app.strict_unlock_prompt_active = False
    app.force_admin_unlock_required = False
    app.current_user = "alice"
    app._lock_system_session = Mock()
    app._prompt_strict_unlock = Mock()
    app._prompt_lock_unlock = Mock()
    app._update_security_lock_status = TuxGuardApplication._update_security_lock_status.__get__(app, TuxGuardApplication)

    app._activate_security_lock("GUI Event Test")
    app.security_lock_window.update_idletasks()
    app.security_lock_window.focus_force()
    app.security_lock_window.event_generate("<Button-1>", x=10, y=10)
    app.security_lock_window.update()

    assert app._prompt_strict_unlock.called
    app.security_lock_window.destroy()


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
    app.strict_unlock_prompt_active = False
    app.force_admin_unlock_required = False
    app.current_user = "alice"
    app._lock_system_session = Mock()
    app._prompt_strict_unlock = Mock()
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

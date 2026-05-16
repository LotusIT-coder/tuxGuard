import importlib
import sys
import types
from unittest.mock import Mock

import pytest


_ORIGINAL_MODULES = {}


def _install_import_stubs():
    simple_ui_stub = types.ModuleType("simple_ui")

    class _Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def show(self):
            return None

    simple_ui_stub.MainUI = object
    simple_ui_stub.PinDialog = _Dialog
    simple_ui_stub.PasswordDialog = _Dialog
    simple_ui_stub.LoginDialog = _Dialog
    simple_ui_stub.FirstRunWizard = _Dialog
    simple_ui_stub.MasterPasswordSetupDialog = _Dialog
    simple_ui_stub.show_recovery_code = lambda *args, **kwargs: None
    for name, module in {
        "simple_ui": simple_ui_stub,
        "camera": None,
        "face_mediapipe": None,
        "pystray": None,
    }.items():
        _ORIGINAL_MODULES.setdefault(name, sys.modules.get(name))
    sys.modules["simple_ui"] = simple_ui_stub

    camera_stub = types.ModuleType("camera")
    camera_stub.CameraManager = object
    sys.modules["camera"] = camera_stub

    face_stub = types.ModuleType("face_mediapipe")
    face_stub.safe_face_encodings_from_file = lambda *args, **kwargs: []
    sys.modules["face_mediapipe"] = face_stub

    class _PystrayIcon:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            pass

        def stop(self):
            pass

    pystray_stub = types.ModuleType("pystray")
    pystray_stub.Icon = _PystrayIcon
    pystray_stub.Menu = lambda *args, **kwargs: (args, kwargs)
    pystray_stub.MenuItem = lambda *args, **kwargs: (args, kwargs)
    sys.modules["pystray"] = pystray_stub


def _restore_import_stubs():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


_install_import_stubs()
app_module = importlib.import_module("tuxguard_refactored")
_restore_import_stubs()
TuxGuardApplication = app_module.TuxGuardApplication


class DummyRoot:
    def __init__(self):
        self._state = "normal"
        self.after_calls = []
        self.withdraw_called = False
        self.deiconify_called = False
        self.topmost_values = []

    def after(self, delay, callback=None):
        self.after_calls.append((delay, callback))
        return "after-id"

    def state(self):
        return self._state

    def withdraw(self):
        self.withdraw_called = True

    def deiconify(self):
        self.deiconify_called = True

    def update_idletasks(self):
        pass

    def lift(self):
        pass

    def focus_force(self):
        pass

    def attributes(self, name, value=None):
        self.topmost_values.append((name, value))


@pytest.fixture
def app():
    app = object.__new__(TuxGuardApplication)
    app.root = DummyRoot()
    app.logger = types.SimpleNamespace(info=Mock(), warning=Mock(), error=Mock(), debug=Mock())
    app.master_auth = types.SimpleNamespace(
        verify_admin_password=Mock(return_value=True),
        verify=Mock(return_value=True),
        add_admin_password=Mock(return_value=2),
    )
    app.db_manager = types.SimpleNamespace(delete_user=Mock(return_value=True))
    app.ui = types.SimpleNamespace(
        add_security_log=Mock(),
        update_monitoring_button=Mock(),
        clear_monitor_preview=Mock(),
        set_ui_behavior=Mock(),
    )
    app.camera_manager = types.SimpleNamespace(is_available=True, is_active=False, start=Mock(return_value=True), stop=Mock())
    app.monitoring_active = False
    app.security_mode = "strict_pin"
    app.security_lock_delay_seconds = 10
    app.deadman_timeout_seconds = 60
    app.deadman_action = "suspend"
    app.security_lock_active = False
    app.security_lock_window = None
    app.security_lock_status_label = None
    app.security_lock_unlock_pending = False
    app.strict_unlock_prompt_active = False
    app.force_admin_unlock_required = False
    app.deadman_triggered = False
    app.last_authorized_seen_at = 0.0
    app.minimize_behavior = "tray"
    app.close_behavior = "ask"
    app.tray_icon = None
    app.session_start = 0.0
    app.active_threads = []
    app.current_user = "alice"
    app._refresh_user_list = Mock()
    app._stop_monitoring = Mock()
    app._activate_security_lock = Mock()
    app._release_security_lock = Mock()
    app._quit_application = Mock()
    app._minimize_to_tray = Mock()
    app._auto_release_self_unlock = Mock()
    app._has_registered_users = Mock(return_value=True)
    return app


def test_require_admin_password_accepts_valid_master_password(monkeypatch, app):
    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def show(self):
            return "valid-pass"

    error_mock = Mock()
    monkeypatch.setattr(app_module, "PasswordDialog", Dialog)
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(showerror=error_mock))

    assert app._require_admin_password("Admin-Test") is True
    app.master_auth.verify_admin_password.assert_called_once_with("valid-pass")
    error_mock.assert_not_called()


def test_require_admin_password_rejects_invalid_password(monkeypatch, app):
    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def show(self):
            return "invalid-pass"

    app.master_auth.verify_admin_password.return_value = False
    error_mock = Mock()
    monkeypatch.setattr(app_module, "PasswordDialog", Dialog)
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(showerror=error_mock))

    assert app._require_admin_password("Admin-Test") is False
    error_mock.assert_called_once()


def test_on_ui_behavior_changed_reverts_ui_when_admin_auth_fails(app):
    app._require_admin_password = Mock(return_value=False)

    app._on_ui_behavior_changed("normal", "quit")

    app.ui.set_ui_behavior.assert_called_once_with("tray", "ask")
    assert app.minimize_behavior == "tray"
    assert app.close_behavior == "ask"


def test_on_ui_behavior_changed_updates_state_when_authorized(app):
    app._require_admin_password = Mock(return_value=True)

    app._on_ui_behavior_changed("normal", "quit")

    assert app.minimize_behavior == "normal"
    assert app.close_behavior == "quit"


def test_add_additional_admin_password_happy_path(monkeypatch, app):
    responses = iter(["primary-pass", "new-pass-123", "new-pass-123"])

    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def show(self):
            return next(responses)

    info_mock = Mock()
    error_mock = Mock()
    monkeypatch.setattr(app_module, "PasswordDialog", Dialog)
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(showinfo=info_mock, showerror=error_mock))

    app._add_additional_admin_password()

    app.master_auth.verify.assert_called_once_with("primary-pass")
    app.master_auth.add_admin_password.assert_called_once_with("primary-pass", "new-pass-123")
    info_mock.assert_called_once()
    error_mock.assert_not_called()


def test_start_monitoring_is_blocked_without_users(monkeypatch, app):
    warning_mock = Mock()
    error_mock = Mock()
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(showwarning=warning_mock, showerror=error_mock))
    app._has_registered_users.return_value = False

    app._start_monitoring()

    assert app.monitoring_active is False
    app.ui.update_monitoring_button.assert_called_once_with(False)
    app.ui.add_security_log.assert_called_once()
    warning_mock.assert_called_once()
    app.camera_manager.start.assert_not_called()


def test_delete_user_requires_confirmation(monkeypatch, app):
    app._require_admin_password = Mock(return_value=True)
    monkeypatch.setattr(
        app_module,
        "messagebox",
        types.SimpleNamespace(askyesno=Mock(return_value=False), showinfo=Mock(), showwarning=Mock(), showerror=Mock()),
    )

    app._delete_user("alice")

    app.db_manager.delete_user.assert_not_called()


def test_delete_last_user_stops_monitoring_and_forces_admin_unlock(monkeypatch, app):
    messagebox_stub = types.SimpleNamespace(
        askyesno=Mock(return_value=True),
        showinfo=Mock(),
        showwarning=Mock(),
        showerror=Mock(),
    )
    monkeypatch.setattr(app_module, "messagebox", messagebox_stub)
    app._require_admin_password = Mock(return_value=True)
    app.monitoring_active = True
    app._has_registered_users.return_value = False

    app._delete_user("alice")

    app.db_manager.delete_user.assert_called_once_with("alice")
    app._stop_monitoring.assert_called_once()
    app._activate_security_lock.assert_called_once_with(
        "Keine Benutzer mehr vorhanden. Entsperren nur mit Admin-Passwort.",
        force_admin_password=True,
    )


def test_prompt_lock_unlock_uses_admin_password(monkeypatch, app):
    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def show(self):
            return "admin-pass"

    app.security_lock_active = True
    app.deadman_triggered = True
    monkeypatch.setattr(app_module, "PasswordDialog", Dialog)
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(showerror=Mock()))

    app._prompt_lock_unlock()

    app.master_auth.verify_admin_password.assert_called_once_with("admin-pass")
    app._release_security_lock.assert_called_once_with("Admin")
    assert app.deadman_triggered is False


def test_on_user_seen_self_unlock_skips_auto_release_when_admin_unlock_required(app):
    app.security_lock_active = True
    app.security_mode = "self_unlock"
    app.force_admin_unlock_required = True
    app.deadman_triggered = True

    app._on_user_seen("alice")

    assert app.deadman_triggered is False
    assert app.root.after_calls == []


@pytest.mark.parametrize(
    ("close_behavior", "dialog_result", "expect_quit", "expect_tray"),
    [
        ("tray", None, False, True),
        ("quit", None, True, False),
        ("ask", True, True, False),
        ("ask", False, False, True),
        ("ask", None, False, False),
    ],
)
def test_on_closing_respects_configured_close_behavior(monkeypatch, app, close_behavior, dialog_result, expect_quit, expect_tray):
    app.close_behavior = close_behavior
    ask_mock = Mock(return_value=dialog_result)
    monkeypatch.setattr(app_module, "messagebox", types.SimpleNamespace(askyesnocancel=ask_mock))

    app._on_closing()

    assert app._quit_application.called is expect_quit
    assert app._minimize_to_tray.called is expect_tray

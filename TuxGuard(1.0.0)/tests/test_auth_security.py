import json
import stat

import pytest

from auth import MasterAuthError, normalize_recovery_code


def test_initialize_writes_hashed_credentials_only(master_auth):
    recovery = master_auth.initialize("SuperSicher123")
    assert recovery
    assert master_auth.path.exists()

    data = json.loads(master_auth.path.read_text(encoding="utf-8"))
    assert data["password"].startswith("pbkdf2_sha256$")
    assert data["recovery"].startswith("pbkdf2_sha256$")
    assert "SuperSicher123" not in master_auth.path.read_text(encoding="utf-8")


def test_initialize_sets_file_permissions_0600(master_auth):
    master_auth.initialize("TopSecret99")
    mode = stat.S_IMODE(master_auth.path.stat().st_mode)
    assert mode == 0o600


def test_initialize_fails_if_already_initialized(master_auth):
    master_auth.initialize("Secret1234")
    with pytest.raises(MasterAuthError):
        master_auth.initialize("AnotherSecret123")


def test_verify_master_password_accepts_only_correct_password(master_auth):
    master_auth.initialize("Secret1234")
    assert master_auth.verify("Secret1234") is True
    assert master_auth.verify("wrong") is False


def test_verify_recovery_is_whitespace_and_case_tolerant(master_auth):
    recovery = master_auth.initialize("Secret1234")
    altered = "  " + recovery.lower().replace("-", " - ") + "\n"
    assert master_auth.verify_recovery(altered) is True


def test_change_password_with_recovery_rotates_password_and_recovery(master_auth):
    recovery = master_auth.initialize("Secret1234")
    new_recovery = master_auth.change_password_with_recovery(recovery, "BrandNewPass9")

    assert new_recovery != recovery
    assert master_auth.verify("Secret1234") is False
    assert master_auth.verify("BrandNewPass9") is True
    assert master_auth.verify_recovery(recovery) is False
    assert master_auth.verify_recovery(new_recovery) is True


def test_verify_admin_password_accepts_primary_and_additional(master_auth):
    master_auth.initialize("PrimarySecret9")
    total = master_auth.add_admin_password("PrimarySecret9", "BackupSecret9")

    assert total == 2
    assert master_auth.verify_admin_password("PrimarySecret9") is True
    assert master_auth.verify_admin_password("BackupSecret9") is True
    assert master_auth.verify_admin_password("nope") is False


def test_add_admin_password_requires_primary_master_password(master_auth):
    master_auth.initialize("PrimarySecret9")

    with pytest.raises(MasterAuthError):
        master_auth.add_admin_password("WrongPrimary", "AnotherSecret9")


def test_add_admin_password_rejects_duplicate_passwords(master_auth):
    master_auth.initialize("PrimarySecret9")

    with pytest.raises(MasterAuthError):
        master_auth.add_admin_password("PrimarySecret9", "PrimarySecret9")

    master_auth.add_admin_password("PrimarySecret9", "BackupSecret9")
    with pytest.raises(MasterAuthError):
        master_auth.add_admin_password("PrimarySecret9", "BackupSecret9")


def test_change_password_with_recovery_keeps_additional_admin_passwords(master_auth):
    recovery = master_auth.initialize("PrimarySecret9")
    master_auth.add_admin_password("PrimarySecret9", "BackupSecret9")

    master_auth.change_password_with_recovery(recovery, "NewPrimarySecret9")

    assert master_auth.verify_admin_password("BackupSecret9") is True
    assert master_auth.verify_admin_password("NewPrimarySecret9") is True


def test_normalize_recovery_code_keeps_only_alnum_uppercase():
    assert normalize_recovery_code("ab-c1 d\n") == "ABC1D"

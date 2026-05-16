import hashlib

import numpy as np
import pytest

from config import Config
from database import SecurityUtils


def test_hash_pin_pbkdf2_format_and_verify_roundtrip():
    hashed = SecurityUtils.hash_pin_pbkdf2("123456")
    assert hashed.startswith("pbkdf2_sha256$")
    assert SecurityUtils.verify_pin("123456", hashed) is True
    assert SecurityUtils.verify_pin("bad", hashed) is False


def test_verify_pin_supports_legacy_sha256_hashes():
    legacy = hashlib.sha256("123456".encode("utf-8")).hexdigest()
    assert SecurityUtils.verify_pin("123456", legacy) is True
    assert SecurityUtils.verify_pin("wrong", legacy) is False


def test_add_user_enforces_min_lengths(db_manager):
    with pytest.raises(ValueError):
        db_manager.add_user("alice", "123")

    with pytest.raises(ValueError):
        db_manager.add_user("alice", "123456", password="short")


def test_add_user_and_verify_password(db_manager):
    db_manager.add_user("alice", "123456", password="Password123", is_admin=True)
    assert db_manager.verify_user_password("alice", "Password123") is True
    assert db_manager.verify_user_password("alice", "wrong") is False


def test_find_user_by_password_admin_only_filters_non_admins(db_manager):
    db_manager.add_user("admin", "123456", password="AdminPass123", is_admin=True)
    db_manager.add_user("user", "654321", password="UserPass123", is_admin=False)

    assert db_manager.find_user_by_password("AdminPass123", admin_only=True)[1] == "admin"
    assert db_manager.find_user_by_password("UserPass123", admin_only=True) is None


def test_verify_user_pin_for_user_is_user_specific(db_manager):
    db_manager.add_user("alice", "111111", password="Password123", is_admin=False)
    db_manager.add_user("bob", "222222", password="Password456", is_admin=False)

    assert db_manager.verify_user_pin_for_user("alice", "111111") is True
    assert db_manager.verify_user_pin_for_user("alice", "222222") is False
    assert db_manager.verify_user_pin_for_user("bob", "222222") is True


def test_verify_user_pin_upgrades_legacy_hash_to_pbkdf2(db_manager):
    legacy = hashlib.sha256("123456".encode("utf-8")).hexdigest()
    db_manager.cursor.execute(
        "INSERT INTO users (name, pin_hash, password_hash, is_admin) VALUES (?, ?, ?, ?)",
        ("legacy_user", legacy, None, 0),
    )
    db_manager.conn.commit()

    assert db_manager.verify_user_pin("123456") is True

    db_manager.cursor.execute("SELECT pin_hash FROM users WHERE name = ?", ("legacy_user",))
    upgraded_hash = db_manager.cursor.fetchone()[0]
    assert upgraded_hash.startswith("pbkdf2_sha256$")


def test_add_and_read_face_records_with_image_data(db_manager):
    user_id = db_manager.add_user("alice", "123456", password="Password123")
    encoding = np.arange(128, dtype=np.float64)
    image_data = b"fake-image-bytes"

    db_manager.add_face_encoding(
        user_id,
        encoding,
        description="alice face",
        image_data=image_data,
        source_filename="alice.jpg",
    )

    records = db_manager.get_user_face_records("alice")
    assert len(records) == 1
    _, desc, stored_image, filename, _created_at = records[0]
    assert desc == "alice face"
    assert stored_image == image_data
    assert filename == "alice.jpg"


def test_delete_user_removes_face_encodings_cascade(db_manager):
    user_id = db_manager.add_user("alice", "123456", password="Password123")
    db_manager.add_face_encoding(user_id, np.arange(128, dtype=np.float64), description="face")

    assert len(db_manager.get_all_face_encodings()) == 1
    assert db_manager.delete_user("alice") is True
    assert len(db_manager.get_all_face_encodings()) == 0


def test_has_admin_and_metadata_flags(db_manager):
    db_manager.add_user("admin", "123456", password="AdminPass123", is_admin=True)
    db_manager.add_user("user", "654321", password="UserPass123", is_admin=False)

    assert db_manager.has_admin() is True
    users_meta = db_manager.get_users_with_meta()
    by_name = {name: (is_admin, has_pw) for _uid, name, is_admin, has_pw in users_meta}
    assert by_name["admin"] == (True, True)
    assert by_name["user"] == (False, True)


def test_set_user_admin_and_password_updates_security_state(db_manager):
    db_manager.add_user("user", "123456", password="UserPass123", is_admin=False)
    assert db_manager.has_admin() is False

    assert db_manager.set_user_admin("user", True) is True
    assert db_manager.has_admin() is True

    assert db_manager.set_user_password("user", "AnotherPass123") is True
    assert db_manager.verify_user_password("user", "AnotherPass123") is True


def test_pbkdf2_iterations_follow_config():
    hashed = SecurityUtils.hash_pin_pbkdf2("123456")
    parts = hashed.split("$")
    assert int(parts[1]) == Config.PBKDF2_ITERATIONS

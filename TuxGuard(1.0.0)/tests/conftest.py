from pathlib import Path

import pytest

from auth import MasterAuth
from database import DatabaseManager


@pytest.fixture
def master_auth(tmp_path: Path) -> MasterAuth:
    return MasterAuth(path=tmp_path / "master_credentials_test.json")


@pytest.fixture
def db_manager(tmp_path: Path):
    db = DatabaseManager(db_path=tmp_path / "tuxguard_test.db")
    db.connect()
    try:
        yield db
    finally:
        db.disconnect()

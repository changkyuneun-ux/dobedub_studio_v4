from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# session.py binds its engine at import time, so configure the test database first.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="dobedub-tests-"))
os.environ.setdefault("STUDIO_DATA_DIR", str(_TEST_ROOT / "data"))
(_TEST_ROOT / "data").mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"

from backend.app.db.base import Base  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402


def _create_test_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


@pytest.fixture
def db_session():
    _create_test_schema()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    _create_test_schema()
    with TestClient(create_app()) as client:
        yield client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def fake_runpod():
    class FakeRunpod:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []
            self.submit_response: dict = {"id": "runpod_job_test_1"}
            self.status_response: dict = {"status": "IN_QUEUE"}

        def __call__(self, method: str, path: str, payload=None):
            self.calls.append((method, path, payload))
            if path == "/run":
                return dict(self.submit_response)
            if path.startswith("/status/"):
                return dict(self.status_response)
            if path == "/health":
                return {"workers": {"idle": 1, "ready": 1}}
            raise AssertionError(f"unexpected RunPod path: {path}")

    return FakeRunpod()

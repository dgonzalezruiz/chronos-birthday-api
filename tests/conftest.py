from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_db


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def client(mock_db):
    def override_get_db():
        try:
            yield mock_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.main.init_db"):
        with TestClient(app) as test_client:
            yield test_client
    app.dependency_overrides.clear()

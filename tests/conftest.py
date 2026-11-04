import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from helpers import SpyClassifier


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def spy():
    return SpyClassifier()


@pytest.fixture
def client(db_path, spy):
    return TestClient(create_app(db_path, spy))

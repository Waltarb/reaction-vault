import pytest
from fastapi.testclient import TestClient

from vault.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    from vault.main import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_health_reports_schema_and_empty_vault(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["schema"] == 1
    assert body["items"] == 0


def test_sqlite_vec_is_loaded(client):
    db = client.app.state.db
    assert db.execute("SELECT vec_version()").fetchone()[0]

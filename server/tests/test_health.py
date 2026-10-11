def test_health_reports_schema_and_empty_vault(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["schema"] == 1
    assert body["items"] == 0


def test_sqlite_vec_is_loaded():
    from vault.config import get_settings
    from vault.db.connection import connect

    db = connect(get_settings().db_path) if get_settings().db_path.exists() else connect(":memory:")
    assert db.execute("SELECT vec_version()").fetchone()[0]

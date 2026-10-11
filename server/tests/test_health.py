def test_health_reports_schema_and_empty_vault(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["schema"] == 2
    assert body["items"] == 0


def test_sqlite_vec_is_loaded():
    from vault.config import get_settings
    from vault.db.connection import connect

    db = connect(get_settings().db_path) if get_settings().db_path.exists() else connect(":memory:")
    assert db.execute("SELECT vec_version()").fetchone()[0]


def test_web_ui_is_served_without_auth(make_client):
    c = make_client(auth_disabled=False)
    page = c.get("/")
    assert page.status_code == 200 and "Reaction Vault" in page.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/app.css").status_code == 200

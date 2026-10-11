from vault.api import deps


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_wrong_tokens_are_rate_limited(make_client):
    deps.failures._hits.clear()
    c = make_client(auth_disabled=False)
    codes = [c.get("/api/items", headers={"Authorization": "Bearer nope"}).status_code for _ in range(25)]
    assert codes[0] == 401 and codes[-1] == 429
    deps.failures._hits.clear()


def test_missing_token_does_not_count_as_failure(make_client):
    deps.failures._hits.clear()
    c = make_client(auth_disabled=False)
    codes = {c.get("/api/items").status_code for _ in range(30)}
    assert codes == {401}


def test_cookie_is_secure_only_over_https(make_client):
    deps.failures._hits.clear()
    from vault.api.deps import hash_token

    c = make_client(auth_disabled=False)
    from vault.config import get_settings
    from vault.db.connection import connect

    db = connect(get_settings().db_path)
    db.execute("INSERT INTO devices (name, token_hash) VALUES ('t', ?)", (hash_token("tok"),))
    db.commit()
    db.close()
    plain = c.post("/api/session", json={"token": "tok"})
    assert plain.status_code == 204 and "secure" not in plain.headers["set-cookie"].lower()
    tls = c.post("/api/session", json={"token": "tok"}, headers={"x-forwarded-proto": "https"})
    assert tls.status_code == 204

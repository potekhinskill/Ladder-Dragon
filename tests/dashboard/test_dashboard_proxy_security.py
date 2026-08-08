from fastapi.testclient import TestClient

from tests.support.module_loaders import load_dashboard


def _enable_proxy_auth(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_TRUST_PROXY_AUTH", "1")
    monkeypatch.setenv("DASHBOARD_PROXY_AUTH_SECRET", "a" * 64)


def test_proxy_auth_requires_shared_secret(monkeypatch):
    _enable_proxy_auth(monkeypatch)
    module = load_dashboard(monkeypatch, "proxy_dashboard", auth_token=None)

    with TestClient(module.app, client=("127.0.0.1", 50000)) as client:
        forged = client.get(
            "/api/does-not-exist",
            headers={"X-Authenticated-User": "dashboard"},
        )
        trusted = client.get(
            "/api/does-not-exist",
            headers={
                "X-Authenticated-User": "dashboard",
                "X-Dashboard-Proxy-Secret": "a" * 64,
            },
        )

    assert forged.status_code == 401
    assert trusted.status_code == 404


def test_proxy_auth_rejects_a_non_loopback_peer(monkeypatch):
    _enable_proxy_auth(monkeypatch)
    module = load_dashboard(monkeypatch, "remote_proxy_dashboard", auth_token=None)
    headers = {
        "X-Authenticated-User": "dashboard",
        "X-Dashboard-Proxy-Secret": "a" * 64,
        "X-Real-IP": "198.51.100.8",
    }

    with TestClient(module.app, client=("198.51.100.7", 50000)) as client:
        response = client.get("/api/does-not-exist", headers=headers)

    assert response.status_code == 401
    assert "a" * 64 not in response.text


def test_untrusted_peer_cannot_split_rate_limit_with_real_ip(monkeypatch):
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MIN", "1")
    module = load_dashboard(monkeypatch, "untrusted_real_ip_dashboard")
    auth = {"Authorization": "Bearer test-secret-token"}

    with TestClient(module.app, client=("198.51.100.7", 50000)) as client:
        first = client.get(
            "/api/does-not-exist",
            headers={**auth, "X-Real-IP": "198.51.100.8"},
        )
        forged = client.get(
            "/api/does-not-exist",
            headers={**auth, "X-Real-IP": "198.51.100.9"},
        )

    assert first.status_code == 404
    assert forged.status_code == 429


def test_proxy_rate_limit_uses_only_authenticated_nginx_client_ip(monkeypatch):
    _enable_proxy_auth(monkeypatch)
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MIN", "1")
    module = load_dashboard(monkeypatch, "proxy_rate_dashboard", auth_token=None)
    headers = {
        "X-Authenticated-User": "dashboard",
        "X-Dashboard-Proxy-Secret": "a" * 64,
        "X-Real-IP": "198.51.100.8",
    }

    with TestClient(module.app, client=("127.0.0.1", 50000)) as client:
        first = client.get("/api/does-not-exist", headers=headers)
        repeated = client.get("/api/does-not-exist", headers=headers)
        other = client.get(
            "/api/does-not-exist",
            headers={**headers, "X-Real-IP": "198.51.100.9"},
        )

    assert first.status_code == 404
    assert repeated.status_code == 429
    assert other.status_code == 404

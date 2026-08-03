import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest
from fastapi.testclient import TestClient

from src.server.main import app
from src.server.router_auth import _hash_password


@pytest.fixture
def provider_client(test_db):
    client = TestClient(app)
    app.state.db = test_db
    for account_id, username, role in [
        ("provider-admin", "provider_admin", "admin"),
        ("provider-host", "provider_host", "host"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s)",
            (account_id, username, _hash_password("test123"), username, role),
        )
    return client


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "test123"},
    )
    return response.json()["token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides) -> dict:
    value = {
        "name": "Configured GPT",
        "api_base_url": "https://api.example.com/v1",
        "protocol": "responses",
        "model": "gpt-5.4",
        "api_key": "sk-route-secret-1234",
        "supports_image": True,
    }
    value.update(overrides)
    return value


def test_provider_routes_require_admin(provider_client):
    host_token = _login(provider_client, "provider_host")

    response = provider_client.get(
        "/api/admin/ai/providers",
        headers=_headers(host_token),
    )

    assert response.status_code == 403


def test_admin_crud_never_returns_or_stores_plaintext_key(provider_client, test_db):
    token = _login(provider_client, "provider_admin")

    created = provider_client.post(
        "/api/admin/ai/providers",
        json=_payload(),
        headers=_headers(token),
    )

    assert created.status_code == 200, created.text
    body = created.json()
    config_id = body["provider_config_id"]
    assert body["key_mask"] == "••••1234"
    assert "api_key" not in body
    listed = provider_client.get(
        "/api/admin/ai/providers",
        headers=_headers(token),
    ).json()
    stored = test_db.execute(
        "SELECT api_key_ciphertext FROM ai_provider_configs WHERE provider_config_id = %s",
        (config_id,),
    ).fetchone()
    assert "sk-route-secret-1234" not in json.dumps(listed)
    assert "api_key_ciphertext" not in json.dumps(listed)
    assert "sk-route-secret-1234" not in stored["api_key_ciphertext"]

    updated = provider_client.patch(
        f"/api/admin/ai/providers/{config_id}",
        json={"name": "Renamed", "api_key": ""},
        headers=_headers(token),
    )
    assert updated.status_code == 200
    assert updated.json()["key_mask"] == "••••1234"

    deleted = provider_client.delete(
        f"/api/admin/ai/providers/{config_id}",
        headers=_headers(token),
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "was_active": False}


def test_admin_must_test_saved_config_before_activation(
    provider_client,
    monkeypatch,
):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    token = _login(provider_client, "provider_admin")
    created = provider_client.post(
        "/api/admin/ai/providers",
        json=_payload(),
        headers=_headers(token),
    ).json()
    config_id = created["provider_config_id"]

    blocked = provider_client.post(
        f"/api/admin/ai/providers/{config_id}/activate",
        headers=_headers(token),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "provider_test_required"

    async def passed_test(self):
        return {
            "ok": True,
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": 15,
            "text": {"ok": True, "latency_ms": 8},
            "image": {"required": True, "ok": True, "latency_ms": 7},
        }

    monkeypatch.setattr(ConfiguredOpenAIProvider, "test_connection", passed_test)
    tested = provider_client.post(
        f"/api/admin/ai/providers/{config_id}/test",
        headers=_headers(token),
    )
    assert tested.status_code == 200
    assert tested.json()["ok"] is True

    activated = provider_client.post(
        f"/api/admin/ai/providers/{config_id}/activate",
        headers=_headers(token),
    )
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True


def test_failed_provider_test_returns_only_sanitized_error_code(
    provider_client,
    monkeypatch,
):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    token = _login(provider_client, "provider_admin")
    config_id = provider_client.post(
        "/api/admin/ai/providers",
        json=_payload(),
        headers=_headers(token),
    ).json()["provider_config_id"]

    async def failed_test(self):
        return {
            "ok": False,
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": 9,
            "text": {"ok": False, "latency_ms": 9, "error_code": "auth_failed"},
            "image": {"required": True, "ok": False, "error_code": "auth_failed"},
        }

    monkeypatch.setattr(ConfiguredOpenAIProvider, "test_connection", failed_test)
    response = provider_client.post(
        f"/api/admin/ai/providers/{config_id}/test",
        headers=_headers(token),
    )

    serialized = json.dumps(response.json())
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "auth_failed" in serialized
    assert "sk-route-secret" not in serialized


def test_deleting_active_config_restores_legacy_chain(provider_client, monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    token = _login(provider_client, "provider_admin")
    config_id = provider_client.post(
        "/api/admin/ai/providers",
        json=_payload(supports_image=False),
        headers=_headers(token),
    ).json()["provider_config_id"]

    async def passed_test(self):
        return {
            "ok": True,
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": 3,
            "text": {"ok": True, "latency_ms": 3},
            "image": {"required": False, "ok": True},
        }

    monkeypatch.setattr(ConfiguredOpenAIProvider, "test_connection", passed_test)
    provider_client.post(
        f"/api/admin/ai/providers/{config_id}/test",
        headers=_headers(token),
    )
    provider_client.post(
        f"/api/admin/ai/providers/{config_id}/activate",
        headers=_headers(token),
    )

    deleted = provider_client.delete(
        f"/api/admin/ai/providers/{config_id}",
        headers=_headers(token),
    )

    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "was_active": True}


def test_provider_test_holds_actor_lifecycle_until_audit_is_written(
    provider_client,
    test_db,
    monkeypatch,
):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    test_db.execute(
        "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
        "VALUES ('governance-deleter', 'governance_deleter', %s, 'deleter', 'admin')",
        (_hash_password("test123"),),
    )
    test_db.commit()
    actor_token = _login(provider_client, "provider_admin")
    deleter_client = TestClient(app)
    deleter_token = _login(deleter_client, "governance_deleter")
    config_id = provider_client.post(
        "/api/admin/ai/providers",
        json=_payload(supports_image=False),
        headers=_headers(actor_token),
    ).json()["provider_config_id"]

    started = threading.Event()
    release = threading.Event()

    async def delayed_test(self):
        started.set()
        await asyncio.to_thread(release.wait)
        return {
            "ok": True,
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": 3,
            "text": {"ok": True, "latency_ms": 3},
            "image": {"required": False, "ok": True},
        }

    monkeypatch.setattr(ConfiguredOpenAIProvider, "test_connection", delayed_test)
    deletion_blocked = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        provider_future = executor.submit(
            provider_client.post,
            f"/api/admin/ai/providers/{config_id}/test",
            headers=_headers(actor_token),
        )
        assert started.wait(timeout=2)
        deletion_future = executor.submit(
            deleter_client.delete,
            "/api/admin/accounts/provider-admin",
            headers=_headers(deleter_token),
        )
        try:
            deletion_future.result(timeout=0.25)
        except TimeoutError:
            deletion_blocked = True
        finally:
            release.set()
        provider_response = provider_future.result(timeout=3)
        deletion_response = deletion_future.result(timeout=3)

    assert deletion_blocked is True
    assert provider_response.status_code == 200, provider_response.text
    assert deletion_response.status_code == 200, deletion_response.text
    assert test_db.execute(
        "SELECT 1 FROM accounts WHERE account_id = 'provider-admin'"
    ).fetchone() is None
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM ai_provider_config_audits "
        "WHERE actor_id = 'provider-admin'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM ai_provider_configs "
        "WHERE created_by = 'provider-admin' OR updated_by = 'provider-admin'"
    ).fetchone()["count"] == 0

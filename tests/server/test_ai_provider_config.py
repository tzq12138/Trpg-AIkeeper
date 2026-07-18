import pytest


def _config_payload(**overrides):
    payload = {
        "name": "Primary GPT",
        "api_base_url": "https://api.example.com/v1",
        "protocol": "responses",
        "model": "gpt-5.4",
        "api_key": "sk-test-secret-1234",
        "supports_image": True,
    }
    payload.update(overrides)
    return payload


def test_secret_cipher_encrypts_and_authenticates_api_keys():
    from src.server.ai.provider_config import SecretCipher

    cipher = SecretCipher("master-secret")
    encrypted = cipher.encrypt("sk-test-secret-1234")

    assert "sk-test-secret-1234" not in encrypted
    assert cipher.decrypt(encrypted) == "sk-test-secret-1234"


def test_secret_cipher_rejects_wrong_master_key():
    from src.server.ai.provider_config import SecretCipher, SecretDecryptionError

    encrypted = SecretCipher("master-secret").encrypt("sk-test-secret-1234")

    with pytest.raises(SecretDecryptionError):
        SecretCipher("different-secret").decrypt(encrypted)


def test_secret_cipher_rejects_tampered_ciphertext():
    from src.server.ai.provider_config import SecretCipher, SecretDecryptionError

    cipher = SecretCipher("master-secret")
    encrypted = cipher.encrypt("sk-test-secret-1234")
    midpoint = len(encrypted) // 2
    replacement = "A" if encrypted[midpoint] != "A" else "B"
    tampered = encrypted[:midpoint] + replacement + encrypted[midpoint + 1:]

    with pytest.raises(SecretDecryptionError):
        cipher.decrypt(tampered)


def test_secret_cipher_requires_configured_master_secret(monkeypatch):
    from src.server.ai.provider_config import (
        ProviderConfigStateError,
        secret_cipher_from_env,
    )

    monkeypatch.delenv("AI_CONFIG_MASTER_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ProviderConfigStateError, match="config_master_key_unavailable"):
        secret_cipher_from_env()


def test_store_lists_masked_configs_without_a_master_secret(test_db, monkeypatch):
    from src.server.ai.provider_config import AiProviderConfigStore, SecretCipher

    created = AiProviderConfigStore(test_db, SecretCipher("master-secret")).create(
        _config_payload(),
        actor_id="admin-1",
    )
    monkeypatch.delenv("AI_CONFIG_MASTER_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    listed = AiProviderConfigStore(test_db).list_public()

    assert listed == [created]
    assert "api_key_ciphertext" not in listed[0]


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://127.0.0.1:11434/v1",
        "http://192.168.1.25:8000/v1",
    ],
)
def test_api_base_url_allows_https_and_lan_http(url):
    from src.server.ai.provider_config import validate_api_base_url

    assert validate_api_base_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/provider",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?token=secret",
        "https://example.com/v1#fragment",
        "http://8.8.8.8/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/v1",
        "https://100.100.100.200/v1",
        "http://[fe80::1]/v1",
        "http://[::ffff:169.254.169.254]/v1",
        "http://224.0.0.1/v1",
    ],
)
def test_api_base_url_blocks_unsafe_targets(url):
    from src.server.ai.provider_config import ProviderConfigValidationError, validate_api_base_url

    with pytest.raises(ProviderConfigValidationError):
        validate_api_base_url(url)


def test_store_encrypts_key_and_returns_only_masked_metadata(test_db):
    from src.server.ai.provider_config import AiProviderConfigStore, SecretCipher

    store = AiProviderConfigStore(test_db, SecretCipher("master-secret"))
    created = store.create(_config_payload(), actor_id="admin-1")

    stored = test_db.execute(
        "SELECT api_key_ciphertext FROM ai_provider_configs WHERE provider_config_id = %s",
        (created["provider_config_id"],),
    ).fetchone()
    serialized = str(created)
    assert "sk-test-secret-1234" not in serialized
    assert "api_key_ciphertext" not in created
    assert created["has_api_key"] is True
    assert created["key_mask"] == "••••1234"
    assert "sk-test-secret-1234" not in stored["api_key_ciphertext"]
    assert store.get_secret(created["provider_config_id"]) == "sk-test-secret-1234"


def test_store_blank_key_preserves_secret_and_resets_test_status(test_db):
    from src.server.ai.provider_config import AiProviderConfigStore, SecretCipher

    store = AiProviderConfigStore(test_db, SecretCipher("master-secret"))
    created = store.create(_config_payload(), actor_id="admin-1")
    store.record_test(created["provider_config_id"], passed=True, latency_ms=25, actor_id="admin-1")

    updated = store.update(
        created["provider_config_id"],
        {"name": "Renamed", "model": "gpt-5.4-mini", "api_key": ""},
        actor_id="admin-2",
    )

    assert updated["name"] == "Renamed"
    assert updated["test_status"] == "untested"
    assert store.get_secret(created["provider_config_id"]) == "sk-test-secret-1234"


def test_store_requires_passed_test_before_atomic_activation(test_db):
    from src.server.ai.provider_config import (
        AiProviderConfigStore,
        ProviderConfigStateError,
        SecretCipher,
    )

    store = AiProviderConfigStore(test_db, SecretCipher("master-secret"))
    first = store.create(_config_payload(name="First"), actor_id="admin-1")
    second = store.create(
        _config_payload(name="Second", api_key="sk-second-secret-5678"),
        actor_id="admin-1",
    )

    with pytest.raises(ProviderConfigStateError):
        store.activate(first["provider_config_id"], actor_id="admin-1")

    store.record_test(first["provider_config_id"], passed=True, latency_ms=10, actor_id="admin-1")
    store.activate(first["provider_config_id"], actor_id="admin-1")
    store.record_test(second["provider_config_id"], passed=True, latency_ms=11, actor_id="admin-1")
    store.activate(second["provider_config_id"], actor_id="admin-1")

    active = store.get_active_internal()
    rows = test_db.execute(
        "SELECT provider_config_id, is_active FROM ai_provider_configs ORDER BY name",
    ).fetchall()
    assert active["provider_config_id"] == second["provider_config_id"]
    assert sum(bool(row["is_active"]) for row in rows) == 1


def test_config_audit_never_records_secret(test_db):
    from src.server.ai.provider_config import AiProviderConfigStore, SecretCipher

    store = AiProviderConfigStore(test_db, SecretCipher("master-secret"))
    created = store.create(_config_payload(), actor_id="admin-1")
    store.record_test(created["provider_config_id"], passed=False, latency_ms=7, actor_id="admin-1")

    audits = test_db.execute(
        "SELECT action, details FROM ai_provider_config_audits ORDER BY created_at",
    ).fetchall()
    serialized = str(audits)
    assert [row["action"] for row in audits] == ["create", "test"]
    assert "sk-test-secret-1234" not in serialized
    assert "api_key" not in serialized

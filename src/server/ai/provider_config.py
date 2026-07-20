"""Encrypted persistence for administrator-managed AI provider configurations."""

import base64
import ipaddress
import json
import os
import socket
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


PROTOCOLS = {"responses", "chat_completions"}
FORBIDDEN_HOSTS = {
    "metadata.google.internal",
    "metadata.google.internal.",
    "instance-data",
    "instance-data.",
}
CLOUD_METADATA_ADDRESSES = {
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("192.0.0.192"),
}


class ProviderConfigError(RuntimeError):
    pass


class ProviderConfigValidationError(ProviderConfigError):
    pass


class ProviderConfigStateError(ProviderConfigError):
    pass


class SecretDecryptionError(ProviderConfigError):
    pass


class SecretCipher:
    def __init__(self, master_secret: str):
        if not master_secret:
            raise ValueError("master_secret is required")
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"aikeeper-ai-provider-config-v1",
        ).derive(master_secret.encode("utf-8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: str) -> str:
        if not value:
            raise ValueError("secret value is required")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise SecretDecryptionError("key_unavailable") from exc


def secret_cipher_from_env() -> SecretCipher:
    master_secret = (
        os.getenv("AI_CONFIG_MASTER_KEY", "").strip()
        or os.getenv("JWT_SECRET", "").strip()
    )
    if not master_secret:
        raise ProviderConfigStateError("config_master_key_unavailable")
    return SecretCipher(master_secret)


def validate_api_base_url(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise ProviderConfigValidationError("invalid_api_base_url") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigValidationError("invalid_api_base_url")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderConfigValidationError("unsafe_api_base_url")
    try:
        parsed.port
    except ValueError as exc:
        raise ProviderConfigValidationError("invalid_api_base_url") from exc
    host = parsed.hostname.rstrip(".").lower()
    if host in FORBIDDEN_HOSTS:
        raise ProviderConfigValidationError("unsafe_api_base_url")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and _is_forbidden_address(address):
        raise ProviderConfigValidationError("unsafe_api_base_url")
    if parsed.scheme == "http":
        if address is None:
            if host not in {"localhost", "localhost.localdomain"}:
                raise ProviderConfigValidationError("unsafe_api_base_url")
        else:
            address = _canonical_address(address)
            if not (address.is_private or address.is_loopback):
                raise ProviderConfigValidationError("unsafe_api_base_url")
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def assert_api_target_safe(value: str) -> str:
    normalized = validate_api_base_url(value)
    parsed = urlsplit(normalized)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if _is_forbidden_address(address):
            raise ProviderConfigValidationError("unsafe_api_base_url")
        return normalized
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderConfigValidationError("api_host_unresolved") from exc
    for info in addresses:
        try:
            resolved = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_forbidden_address(resolved):
            raise ProviderConfigValidationError("unsafe_api_base_url")
    return normalized


class AiProviderConfigStore:
    def __init__(self, conn, cipher: SecretCipher | None = None):
        self.conn = conn
        self.cipher = cipher

    def _cipher(self) -> SecretCipher:
        if self.cipher is None:
            self.cipher = secret_cipher_from_env()
        return self.cipher

    def list_public(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM ai_provider_configs ORDER BY is_active DESC, updated_at DESC, name"
        ).fetchall()
        return [self._public(row) for row in rows]

    def create(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        config = self._validated(payload, require_key=True)
        provider_config_id = str(uuid.uuid4())
        ciphertext = self._cipher().encrypt(config["api_key"])
        key_mask = _key_mask(config["api_key"])
        self.conn.execute(
            """
            INSERT INTO ai_provider_configs (
                provider_config_id, name, api_base_url, protocol, model,
                supports_image, api_key_ciphertext, key_mask, created_by, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                provider_config_id,
                config["name"],
                config["api_base_url"],
                config["protocol"],
                config["model"],
                config["supports_image"],
                ciphertext,
                key_mask,
                actor_id,
                actor_id,
            ),
        )
        self._audit(provider_config_id, "create", actor_id, {
            "protocol": config["protocol"],
            "supports_image": config["supports_image"],
        })
        return self.get_public(provider_config_id)

    def get_public(self, provider_config_id: str) -> dict[str, Any]:
        return self._public(self._get(provider_config_id))

    def get_internal(self, provider_config_id: str) -> dict[str, Any]:
        row = self._get(provider_config_id)
        result = dict(row)
        result["api_key"] = self.get_secret(provider_config_id)
        result.pop("api_key_ciphertext", None)
        return result

    def get_secret(self, provider_config_id: str) -> str:
        row = self._get(provider_config_id)
        try:
            return self._cipher().decrypt(row["api_key_ciphertext"])
        except SecretDecryptionError:
            self.conn.execute(
                "UPDATE ai_provider_configs SET test_status = 'key_unavailable', "
                "updated_at = NOW() WHERE provider_config_id = %s",
                (provider_config_id,),
            )
            raise

    def update(
        self,
        provider_config_id: str,
        payload: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        existing = self._get(provider_config_id)
        merged = {
            "name": payload.get("name", existing["name"]),
            "api_base_url": payload.get("api_base_url", existing["api_base_url"]),
            "protocol": payload.get("protocol", existing["protocol"]),
            "model": payload.get("model", existing["model"]),
            "supports_image": payload.get("supports_image", existing["supports_image"]),
            "api_key": payload.get("api_key") or "preserved",
        }
        config = self._validated(merged, require_key=True)
        new_key = str(payload.get("api_key") or "").strip()
        ciphertext = existing["api_key_ciphertext"]
        key_mask = existing["key_mask"]
        if new_key:
            ciphertext = self._cipher().encrypt(new_key)
            key_mask = _key_mask(new_key)
        critical_changed = bool(new_key) or any(
            field in payload and payload[field] != existing[field]
            for field in ("api_base_url", "protocol", "model", "supports_image")
        )
        test_status = "untested" if critical_changed else existing["test_status"]
        self.conn.execute(
            """
            UPDATE ai_provider_configs
            SET name = %s, api_base_url = %s, protocol = %s, model = %s,
                supports_image = %s, api_key_ciphertext = %s, key_mask = %s,
                test_status = %s,
                last_tested_at = CASE WHEN %s THEN NULL ELSE last_tested_at END,
                last_test_latency_ms = CASE WHEN %s THEN NULL ELSE last_test_latency_ms END,
                updated_by = %s, updated_at = NOW()
            WHERE provider_config_id = %s
            """,
            (
                config["name"], config["api_base_url"], config["protocol"],
                config["model"], config["supports_image"], ciphertext, key_mask,
                test_status, critical_changed, critical_changed, actor_id,
                provider_config_id,
            ),
        )
        self._audit(provider_config_id, "update", actor_id, {
            "test_status_reset": critical_changed,
        })
        return self.get_public(provider_config_id)

    def record_test(
        self,
        provider_config_id: str,
        passed: bool,
        latency_ms: int,
        actor_id: str,
    ) -> dict[str, Any]:
        self._get(provider_config_id)
        status = "passed" if passed else "failed"
        self.conn.execute(
            """
            UPDATE ai_provider_configs
            SET test_status = %s, last_tested_at = NOW(),
                last_test_latency_ms = %s, updated_by = %s, updated_at = NOW()
            WHERE provider_config_id = %s
            """,
            (status, max(0, int(latency_ms)), actor_id, provider_config_id),
        )
        self._audit(provider_config_id, "test", actor_id, {"status": status})
        return self.get_public(provider_config_id)

    def activate(self, provider_config_id: str, actor_id: str) -> dict[str, Any]:
        row = self._get(provider_config_id)
        if row["test_status"] != "passed":
            raise ProviderConfigStateError("provider_test_required")
        with self.conn.transaction() as tx:
            tx.execute("UPDATE ai_provider_configs SET is_active = FALSE WHERE is_active = TRUE")
            tx.execute(
                "UPDATE ai_provider_configs SET is_active = TRUE, updated_by = %s, "
                "updated_at = NOW() WHERE provider_config_id = %s",
                (actor_id, provider_config_id),
            )
            self._audit(provider_config_id, "activate", actor_id, {}, tx=tx)
        return self.get_public(provider_config_id)

    def delete(self, provider_config_id: str, actor_id: str) -> None:
        self._get(provider_config_id)
        with self.conn.transaction() as tx:
            tx.execute(
                "DELETE FROM ai_provider_configs WHERE provider_config_id = %s",
                (provider_config_id,),
            )
            self._audit(provider_config_id, "delete", actor_id, {}, tx=tx)

    def get_active_internal(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM ai_provider_configs WHERE is_active = TRUE LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self.get_internal(row["provider_config_id"])

    def _validated(self, payload: dict[str, Any], require_key: bool) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        model = str(payload.get("model") or "").strip()
        protocol = str(payload.get("protocol") or "responses").strip()
        api_key = str(payload.get("api_key") or "").strip()
        if not name or len(name) > 120:
            raise ProviderConfigValidationError("invalid_name")
        if not model or len(model) > 200:
            raise ProviderConfigValidationError("invalid_model")
        if protocol not in PROTOCOLS:
            raise ProviderConfigValidationError("invalid_protocol")
        if require_key and not api_key:
            raise ProviderConfigValidationError("api_key_required")
        return {
            "name": name,
            "api_base_url": validate_api_base_url(str(payload.get("api_base_url") or "")),
            "protocol": protocol,
            "model": model,
            "supports_image": bool(payload.get("supports_image", False)),
            "api_key": api_key,
        }

    def _get(self, provider_config_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM ai_provider_configs WHERE provider_config_id = %s",
            (provider_config_id,),
        ).fetchone()
        if not row:
            raise ProviderConfigStateError("provider_config_not_found")
        return dict(row)

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_config_id": row["provider_config_id"],
            "name": row["name"],
            "api_base_url": row["api_base_url"],
            "protocol": row["protocol"],
            "model": row["model"],
            "supports_image": bool(row["supports_image"]),
            "has_api_key": bool(row.get("api_key_ciphertext")),
            "key_mask": row["key_mask"],
            "is_active": bool(row["is_active"]),
            "test_status": row["test_status"],
            "last_tested_at": str(row.get("last_tested_at") or ""),
            "last_test_latency_ms": row.get("last_test_latency_ms"),
            "created_by": row["created_by"],
            "updated_by": row["updated_by"],
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    def _audit(
        self,
        provider_config_id: str,
        action: str,
        actor_id: str,
        details: dict[str, Any],
        tx=None,
    ) -> None:
        executor = tx or self.conn
        executor.execute(
            """
            INSERT INTO ai_provider_config_audits (
                audit_id, provider_config_id, action, actor_id, details
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()), provider_config_id, action, actor_id,
                json.dumps(details, ensure_ascii=False),
            ),
        )


def _key_mask(api_key: str) -> str:
    return "••••" + api_key[-4:]


def _is_forbidden_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    address = _canonical_address(address)
    return (
        address in CLOUD_METADATA_ADDRESSES
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _canonical_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address

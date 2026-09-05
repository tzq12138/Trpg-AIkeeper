"""Encrypted configuration storage for administrator-managed image generators."""

import base64
import json
import time
import uuid
from typing import Any

import httpx

from .provider_config import (
    ProviderConfigStateError,
    ProviderConfigValidationError,
    SecretCipher,
    SecretDecryptionError,
    _key_mask,
    assert_api_target_safe,
    secret_cipher_from_env,
    validate_api_base_url,
)


ALLOWED_IMAGE_SIZES = {
    "256x256",
    "512x512",
    "1024x1024",
    "1536x1024",
    "1024x1536",
}
MAX_GENERATED_IMAGE_SIZE = 50 * 1024 * 1024


class ImageGenerationError(RuntimeError):
    pass


class ImageGenerationProvider:
    def __init__(self, config: dict[str, Any], timeout_seconds: float = 30.0):
        self.config = dict(config)
        self.timeout_seconds = timeout_seconds

    async def generate(self, prompt: str, size: str | None = None) -> dict[str, Any]:
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt or len(normalized_prompt) > 8_000:
            raise ImageGenerationError("invalid_image_prompt")
        normalized_size = str(size or self.config.get("default_size") or "").strip()
        if normalized_size not in ALLOWED_IMAGE_SIZES:
            raise ImageGenerationError("invalid_image_size")
        try:
            base_url = assert_api_target_safe(str(self.config.get("api_base_url") or ""))
        except ProviderConfigValidationError as exc:
            raise ImageGenerationError(str(exc)) from exc
        endpoint = f"{base_url.rstrip('/')}/images/generations"
        started_at = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.config.get('api_key') or ''}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": str(self.config.get("model") or "").strip(),
                        "prompt": normalized_prompt,
                        "size": normalized_size,
                        "response_format": "b64_json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise ImageGenerationError("timeout") from exc
        except httpx.RequestError as exc:
            raise ImageGenerationError("invalid_response") from exc

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            raise ImageGenerationError(_status_error_code(status_code))
        try:
            response.raise_for_status()
            response_body = response.json()
        except Exception as exc:
            raise ImageGenerationError("invalid_response") from exc
        content = _decode_generated_image(response_body)
        return {
            "content": content,
            "mime_type": _image_mime_type(content),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def test_connection(self) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            await self.generate("minimal abstract investigation clue, no text", "256x256")
        except ImageGenerationError as exc:
            return {
                "ok": False,
                "error_code": str(exc),
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
            }
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }


def _decode_generated_image(response_body: Any) -> bytes:
    if not isinstance(response_body, dict):
        raise ImageGenerationError("invalid_response")
    values = response_body.get("data")
    if not isinstance(values, list) or not values or not isinstance(values[0], dict):
        raise ImageGenerationError("invalid_response")
    encoded = values[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ImageGenerationError("invalid_response")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImageGenerationError("invalid_response") from exc
    if not content or len(content) > MAX_GENERATED_IMAGE_SIZE:
        raise ImageGenerationError("invalid_response")
    _image_mime_type(content)
    return content


def _image_mime_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    raise ImageGenerationError("invalid_response")


def _status_error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth_failed"
    if status_code == 404:
        return "model_not_found"
    if status_code == 429:
        return "rate_limited"
    return "invalid_response"


class ImageGenerationConfigStore:
    def __init__(self, conn, cipher: SecretCipher | None = None):
        self.conn = conn
        self.cipher = cipher or secret_cipher_from_env()

    def list_public(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM image_generation_configs "
            "ORDER BY is_active DESC, updated_at DESC, name"
        ).fetchall()
        return [self._public(row) for row in rows]

    def create(self, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        config = self._validated(payload, require_key=True)
        config_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO image_generation_configs (
                image_generation_config_id, name, api_base_url, model,
                default_size, api_key_ciphertext, key_mask, created_by, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                config_id,
                config["name"],
                config["api_base_url"],
                config["model"],
                config["default_size"],
                self.cipher.encrypt(config["api_key"]),
                _key_mask(config["api_key"]),
                actor_id,
                actor_id,
            ),
        )
        self._audit(config_id, "create", actor_id, {"default_size": config["default_size"]})
        return self.get_public(config_id)

    def get_public(self, config_id: str) -> dict[str, Any]:
        return self._public(self._get(config_id))

    def get_internal(self, config_id: str) -> dict[str, Any]:
        row = self._get(config_id)
        row["api_key"] = self.get_secret(config_id)
        row.pop("api_key_ciphertext", None)
        return row

    def get_secret(self, config_id: str) -> str:
        row = self._get(config_id)
        try:
            return self.cipher.decrypt(row["api_key_ciphertext"])
        except SecretDecryptionError:
            self.conn.execute(
                "UPDATE image_generation_configs SET test_status = 'key_unavailable', "
                "updated_at = NOW() WHERE image_generation_config_id = %s",
                (config_id,),
            )
            raise

    def update(self, config_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
        existing = self._get(config_id)
        merged = {
            "name": payload.get("name", existing["name"]),
            "api_base_url": payload.get("api_base_url", existing["api_base_url"]),
            "model": payload.get("model", existing["model"]),
            "default_size": payload.get("default_size", existing["default_size"]),
            "api_key": payload.get("api_key") or "preserved",
        }
        config = self._validated(merged, require_key=True)
        new_key = str(payload.get("api_key") or "").strip()
        ciphertext = existing["api_key_ciphertext"]
        key_mask = existing["key_mask"]
        if new_key:
            ciphertext = self.cipher.encrypt(new_key)
            key_mask = _key_mask(new_key)
        critical_changed = bool(new_key) or any(
            field in payload and payload[field] != existing[field]
            for field in ("api_base_url", "model", "default_size")
        )
        self.conn.execute(
            """
            UPDATE image_generation_configs
            SET name = %s, api_base_url = %s, model = %s, default_size = %s,
                api_key_ciphertext = %s, key_mask = %s,
                test_status = CASE WHEN %s THEN 'untested' ELSE test_status END,
                last_tested_at = CASE WHEN %s THEN NULL ELSE last_tested_at END,
                last_test_latency_ms = CASE WHEN %s THEN NULL ELSE last_test_latency_ms END,
                updated_by = %s, updated_at = NOW()
            WHERE image_generation_config_id = %s
            """,
            (
                config["name"],
                config["api_base_url"],
                config["model"],
                config["default_size"],
                ciphertext,
                key_mask,
                critical_changed,
                critical_changed,
                critical_changed,
                actor_id,
                config_id,
            ),
        )
        self._audit(config_id, "update", actor_id, {"test_status_reset": critical_changed})
        return self.get_public(config_id)

    def record_test(self, config_id: str, passed: bool, latency_ms: int, actor_id: str) -> dict[str, Any]:
        self._get(config_id)
        status = "passed" if passed else "failed"
        self.conn.execute(
            """
            UPDATE image_generation_configs
            SET test_status = %s, last_tested_at = NOW(), last_test_latency_ms = %s,
                updated_by = %s, updated_at = NOW()
            WHERE image_generation_config_id = %s
            """,
            (status, max(0, int(latency_ms)), actor_id, config_id),
        )
        self._audit(config_id, "test", actor_id, {"status": status})
        return self.get_public(config_id)

    def activate(self, config_id: str, actor_id: str) -> dict[str, Any]:
        row = self._get(config_id)
        if row["test_status"] != "passed":
            raise ProviderConfigStateError("provider_test_required")
        with self.conn.transaction() as tx:
            tx.execute("UPDATE image_generation_configs SET is_active = FALSE WHERE is_active = TRUE")
            tx.execute(
                "UPDATE image_generation_configs SET is_active = TRUE, updated_by = %s, "
                "updated_at = NOW() WHERE image_generation_config_id = %s",
                (actor_id, config_id),
            )
            self._audit(config_id, "activate", actor_id, {}, tx=tx)
        return self.get_public(config_id)

    def delete(self, config_id: str, actor_id: str) -> None:
        self._get(config_id)
        with self.conn.transaction() as tx:
            tx.execute(
                "DELETE FROM image_generation_configs WHERE image_generation_config_id = %s",
                (config_id,),
            )
            self._audit(config_id, "delete", actor_id, {}, tx=tx)

    def get_active_internal(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM image_generation_configs WHERE is_active = TRUE LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self.get_internal(row["image_generation_config_id"])

    def _validated(self, payload: dict[str, Any], require_key: bool) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        model = str(payload.get("model") or "").strip()
        default_size = str(payload.get("default_size") or "1024x1024").strip()
        api_key = str(payload.get("api_key") or "").strip()
        if not name or len(name) > 120:
            raise ProviderConfigValidationError("invalid_name")
        if not model or len(model) > 200:
            raise ProviderConfigValidationError("invalid_model")
        if default_size not in ALLOWED_IMAGE_SIZES:
            raise ProviderConfigValidationError("invalid_image_size")
        if require_key and not api_key:
            raise ProviderConfigValidationError("api_key_required")
        return {
            "name": name,
            "api_base_url": validate_api_base_url(str(payload.get("api_base_url") or "")),
            "model": model,
            "default_size": default_size,
            "api_key": api_key,
        }

    def _get(self, config_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM image_generation_configs WHERE image_generation_config_id = %s",
            (config_id,),
        ).fetchone()
        if not row:
            raise ProviderConfigStateError("provider_config_not_found")
        return dict(row)

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "image_generation_config_id": row["image_generation_config_id"],
            "name": row["name"],
            "api_base_url": row["api_base_url"],
            "model": row["model"],
            "default_size": row["default_size"],
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
        config_id: str,
        action: str,
        actor_id: str,
        details: dict[str, Any],
        tx=None,
    ) -> None:
        target = tx or self.conn
        target.execute(
            """
            INSERT INTO image_generation_config_audits (
                audit_id, image_generation_config_id, action, actor_id, details
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), config_id, action, actor_id, json.dumps(details)),
        )

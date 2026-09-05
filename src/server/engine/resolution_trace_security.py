"""Encryption and integrity checks for the short-lived full resolution trace."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


TRACE_ENCRYPTION_KEY_VERSION = "trace-v1"
FULL_TRACE_RETENTION_DAYS = 30
REDACTED_TRACE_RETENTION_DAYS = 180


class ResolutionTraceSecurityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _canonical_payload(trace: dict[str, Any]) -> bytes:
    return json.dumps(
        trace,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _cipher() -> Fernet:
    master_secret = (
        os.getenv("AI_CONFIG_MASTER_KEY", "").strip()
        or os.getenv("JWT_SECRET", "aikeeper-change-me-in-production")
    )
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"aikeeper-resolution-trace-v1",
    ).derive(master_secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_resolution_trace(trace: dict[str, Any]) -> tuple[str, str]:
    payload = _canonical_payload(trace)
    return _cipher().encrypt(payload).decode("ascii"), hashlib.sha256(payload).hexdigest()


def decrypt_resolution_trace(ciphertext: str, payload_hash: str) -> dict[str, Any]:
    try:
        payload = _cipher().decrypt(str(ciphertext).encode("ascii"))
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ResolutionTraceSecurityError("resolution_trace_decryption_failed") from exc
    if hashlib.sha256(payload).hexdigest() != str(payload_hash or ""):
        raise ResolutionTraceSecurityError("resolution_trace_integrity_failed")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResolutionTraceSecurityError("resolution_trace_payload_invalid") from exc
    if not isinstance(value, dict):
        raise ResolutionTraceSecurityError("resolution_trace_payload_invalid")
    return value

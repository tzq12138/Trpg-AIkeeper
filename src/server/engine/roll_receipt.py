import copy
import hashlib
import hmac
import json
import os


def create_roll_receipt(
    *,
    action_id: str,
    rule_set_version: str,
    rolled_at: str,
    raw_rolls: list[dict],
    secret: str | None = None,
) -> dict:
    payload = {
        "version": "v1",
        "algorithm": "HMAC-SHA256",
        "action_id": action_id,
        "rule_set_version": rule_set_version,
        "rolled_at": rolled_at,
        "raw_rolls": copy.deepcopy(raw_rolls),
    }
    payload["signature"] = _sign(payload, secret)
    return payload


def verify_roll_receipt(receipt: dict, *, secret: str | None = None) -> bool:
    if not isinstance(receipt, dict):
        return False
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not signature:
        return False
    payload = {key: copy.deepcopy(value) for key, value in receipt.items() if key != "signature"}
    return hmac.compare_digest(signature, _sign(payload, secret))


def _sign(payload: dict, secret: str | None) -> str:
    key = _derive_key(secret or _receipt_secret())
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(b"aikeeper-roll-receipt-v1\x00" + secret.encode("utf-8")).digest()


def _receipt_secret() -> str:
    secret = os.getenv("ROLL_RECEIPT_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("ROLL_RECEIPT_SECRET or JWT_SECRET is required")
    return secret

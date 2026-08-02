import copy
import hashlib
import hmac
import json
import os


def create_roll_receipt(
    *,
    action_id: str,
    rule_set_version: str,
    rolled_at: str | None = None,
    raw_rolls: list[dict] | None = None,
    version: str = "v1",
    room_id: str | None = None,
    state_version: int | None = None,
    purpose: str | None = None,
    locked_inputs: dict | None = None,
    raw_draws: list[dict] | None = None,
    idempotency_key: str | None = None,
    secret: str | None = None,
) -> dict:
    if version == "v1":
        if not isinstance(rolled_at, str) or not isinstance(raw_rolls, list):
            raise ValueError("v1 receipt requires rolled_at and raw_rolls")
        payload = {
            "version": "v1",
            "algorithm": "HMAC-SHA256",
            "action_id": action_id,
            "rule_set_version": rule_set_version,
            "rolled_at": rolled_at,
            "raw_rolls": copy.deepcopy(raw_rolls),
        }
    elif version == "v2":
        if (
            not isinstance(room_id, str)
            or not room_id
            or not isinstance(state_version, int)
            or isinstance(state_version, bool)
            or state_version < 0
            or not isinstance(purpose, str)
            or not purpose
            or not isinstance(locked_inputs, dict)
            or not isinstance(raw_draws, list)
            or not isinstance(idempotency_key, str)
            or not idempotency_key
        ):
            raise ValueError("v2 receipt requires authoritative context")
        payload = {
            "version": "v2",
            "algorithm": "HMAC-SHA256",
            "room_id": room_id,
            "state_version": state_version,
            "action_id": action_id,
            "purpose": purpose,
            "rule_set_version": rule_set_version,
            "locked_inputs": copy.deepcopy(locked_inputs),
            "raw_draws": copy.deepcopy(raw_draws),
            "idempotency_key": idempotency_key,
        }
    else:
        raise ValueError("unsupported receipt version")
    payload["signature"] = _sign(payload, secret)
    return payload


def verify_roll_receipt(receipt: dict, *, secret: str | None = None) -> bool:
    if not isinstance(receipt, dict):
        return False
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not signature:
        return False
    payload = {key: copy.deepcopy(value) for key, value in receipt.items() if key != "signature"}
    if not _valid_payload_shape(payload):
        return False
    return hmac.compare_digest(signature, _sign(payload, secret))


def _sign(payload: dict, secret: str | None) -> str:
    version = str(payload.get("version") or "")
    key = _derive_key(secret or _receipt_secret(), version)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def _derive_key(secret: str, version: str) -> bytes:
    domain = (
        b"aikeeper-roll-receipt-v1\x00"
        if version == "v1"
        else b"aikeeper-roll-receipt-v2\x00"
    )
    return hashlib.sha256(domain + secret.encode("utf-8")).digest()


def _valid_payload_shape(payload: dict) -> bool:
    version = payload.get("version")
    if version == "v1":
        return (
            payload.get("algorithm") == "HMAC-SHA256"
            and isinstance(payload.get("action_id"), str)
            and isinstance(payload.get("rule_set_version"), str)
            and isinstance(payload.get("rolled_at"), str)
            and isinstance(payload.get("raw_rolls"), list)
        )
    if version == "v2":
        return (
            payload.get("algorithm") == "HMAC-SHA256"
            and isinstance(payload.get("room_id"), str)
            and isinstance(payload.get("state_version"), int)
            and not isinstance(payload.get("state_version"), bool)
            and payload["state_version"] >= 0
            and isinstance(payload.get("action_id"), str)
            and isinstance(payload.get("purpose"), str)
            and isinstance(payload.get("rule_set_version"), str)
            and isinstance(payload.get("locked_inputs"), dict)
            and isinstance(payload.get("raw_draws"), list)
            and isinstance(payload.get("idempotency_key"), str)
        )
    return False


def _receipt_secret() -> str:
    secret = os.getenv("ROLL_RECEIPT_SECRET") or os.getenv("JWT_SECRET")
    if not secret and os.getenv("AIKEEPER_DEV_MODE", "").lower() in ("1", "true", "yes"):
        return "aikeeper-local-development-roll-receipt-v1"
    if not secret:
        raise RuntimeError("ROLL_RECEIPT_SECRET or JWT_SECRET is required")
    return secret

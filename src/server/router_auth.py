import uuid
import hashlib
import hmac
import json
import base64
import time
import logging
import os
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

JWT_SECRET = os.getenv("JWT_SECRET", "aikeeper-change-me-in-production")
JWT_EXPIRY = 86400 * 7  # 7 days
PBKDF2_ITERATIONS = 100_000


BOOTSTRAP_ADMIN_CODE = os.getenv("BOOTSTRAP_ADMIN_CODE", "")


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    admin_code: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with random salt — replaces insecure SHA-256."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF2_ITERATIONS)
    return salt.hex() + ':' + key.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split(':')
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(new_key, expected_key)
    except (ValueError, TypeError):
        return False


def _create_token(account_id: str, username: str) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    payload_data = {
        "sub": account_id,
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_data).encode()
    ).decode().rstrip("=")
    sig_input = f"{header}.{payload}"
    signature = hmac.new(
        JWT_SECRET.encode(), sig_input.encode(), hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{header}.{payload}.{sig_b64}"


def verify_token(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig_b64 = parts
        sig_input = f"{header}.{payload}"
        expected_sig = hmac.new(
            JWT_SECRET.encode(), sig_input.encode(), hashlib.sha256
        ).digest()
        actual_sig = base64.urlsafe_b64decode(sig_b64 + "==")
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload_json = base64.urlsafe_b64decode(payload + "==")
        data = json.loads(payload_json)
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def get_account_from_token(request: Request) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.headers.get("X-Account-Token", "")
    if not token:
        return None
    data = verify_token(token)
    if not data:
        return None
    conn = request.app.state.db
    row = conn.execute(
        "SELECT account_id, username, display_name, role, last_seen_at, created_at "
        "FROM accounts WHERE account_id = %s", (data["sub"],)
    ).fetchone()
    return dict(row) if row else None


@router.post("/register")
async def register(request: Request, body: RegisterRequest):
    conn = request.app.state.db

    existing = conn.execute(
        "SELECT account_id FROM accounts WHERE username = %s", (body.username,)
    ).fetchone()
    if existing:
        raise HTTPException(409, "用户名已存在")

    account_id = str(uuid.uuid4())[:8]
    password_hash = _hash_password(body.password)
    display_name = body.display_name or body.username

    # First registered account becomes admin — but if BOOTSTRAP_ADMIN_CODE is
    # configured in production, the caller must provide the matching code.
    existing_count = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
    role = "admin" if existing_count == 0 else "player"

    if existing_count == 0 and BOOTSTRAP_ADMIN_CODE:
        code = (body.admin_code or "").strip()
        if code != BOOTSTRAP_ADMIN_CODE:
            raise HTTPException(400, "admin_code required for first account registration")

    conn.execute(
        "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
        "VALUES (%s, %s, %s, %s, %s)",
        (account_id, body.username, password_hash, display_name, role),
    )
    conn.commit()

    token = _create_token(account_id, body.username)
    logger.info("register: username=%s role=%s account_id=%s", body.username, role, account_id)
    return {
        "account_id": account_id,
        "username": body.username,
        "display_name": display_name,
        "role": role,
        "token": token,
    }


@router.post("/login")
async def login(request: Request, body: LoginRequest):
    conn = request.app.state.db

    account = conn.execute(
        "SELECT * FROM accounts WHERE username = %s", (body.username,)
    ).fetchone()
    if not account:
        logger.warning("login: failed — unknown user=%s", body.username)
        raise HTTPException(401, "用户名或密码错误")

    account = dict(account)
    if not _verify_password(body.password, account["password_hash"]):
        logger.warning("login: failed — bad password user=%s", body.username)
        raise HTTPException(401, "用户名或密码错误")

    conn.execute("UPDATE accounts SET last_seen_at = NOW() WHERE account_id = %s",
                 (account["account_id"],))
    conn.commit()

    logger.info("login: success user=%s role=%s", body.username, account.get("role", "player"))
    token = _create_token(account["account_id"], account["username"])
    return {
        "account_id": account["account_id"],
        "username": account["username"],
        "display_name": account.get("display_name", ""),
        "role": account.get("role", "player"),
        "token": token,
    }


@router.get("/me")
async def get_me(request: Request):
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    # Touch last_seen_at
    try:
        conn = request.app.state.db
        conn.execute("UPDATE accounts SET last_seen_at = NOW() WHERE account_id = %s",
                     (account["account_id"],))
        conn.commit()
    except Exception:
        pass
    return {
        "account_id": account["account_id"],
        "username": account["username"],
        "display_name": account.get("display_name", ""),
        "role": account.get("role", "player"),
    }


@router.get("/me/characters")
async def get_my_characters(request: Request):
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")

    conn = request.app.state.db
    rows = conn.execute(
        "SELECT character_id, room_id, player_name, xlsx_data "
        "FROM characters WHERE account_id = %s ORDER BY character_id DESC",
        (account["account_id"],),
    ).fetchall()

    characters = []
    for row in dict_row(rows):
        xlsx = _json_value(row.get("xlsx_data")) or {}
        characters.append({
            "character_id": row["character_id"],
            "room_id": row["room_id"],
            "name": row.get("player_name", ""),
            "occupation": xlsx.get("occupation", ""),
            "background": xlsx.get("background", ""),
            "hp": xlsx.get("hp", 0),
            "max_hp": xlsx.get("max_hp", 0),
            "san": xlsx.get("san", 0),
            "max_san": xlsx.get("max_san", 0),
        })
    return characters


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def dict_row(rows):
    return [dict(r) for r in (rows or [])]

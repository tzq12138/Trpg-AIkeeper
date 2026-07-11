import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class PrivateDataDecryptionError(ValueError):
    pass


class PrivateDataCipher:
    def __init__(self, master_secret: str):
        if not master_secret:
            raise ValueError("master_secret is required")
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"aikeeper-player-private-data-v1",
        ).derive(master_secret.encode("utf-8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise PrivateDataDecryptionError("private data key is unavailable") from exc

    def encrypt_bytes(self, value: bytes) -> str:
        return self._fernet.encrypt(value).decode("ascii")

    def decrypt_bytes(self, ciphertext: str) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise PrivateDataDecryptionError("private data key is unavailable") from exc


def private_data_cipher_from_env() -> PrivateDataCipher:
    master_secret = (
        os.getenv("AI_CONFIG_MASTER_KEY", "").strip()
        or os.getenv("JWT_SECRET", "aikeeper-change-me-in-production")
    )
    return PrivateDataCipher(master_secret)

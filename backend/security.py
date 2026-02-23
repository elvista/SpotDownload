"""Token encryption at rest using Fernet (symmetric encryption)."""

import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("spotdownload.security")

# Prefix for values that are stored encrypted (so we can distinguish from legacy plaintext)
ENCRYPTED_PREFIX = "enc:"


def _get_fernet(key: str | None):
    """Build Fernet instance from key. Key must be 32 url-safe base64-encoded bytes or a password string."""
    if not key or not key.strip():
        return None
    key = key.strip()
    # If it looks like base64 (Fernet key), use directly
    if len(key) == 44 and key.replace("-", "").replace("_", "").isalnum():
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            pass
    # Otherwise derive key from password
    try:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"spotdownload_token_salt",
            iterations=480000,
        )
        derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
        return Fernet(derived)
    except Exception as e:
        logger.warning("Failed to build Fernet from key: %s", e)
        return None


def encrypt_token(value: str, encryption_key: str | None) -> str:
    """Encrypt a token for storage. Returns plain value if encryption_key is empty or encryption fails."""
    if not value:
        return value
    f = _get_fernet(encryption_key)
    if not f:
        return value
    try:
        encrypted = f.encrypt(value.encode())
        return ENCRYPTED_PREFIX + encrypted.decode()
    except Exception as e:
        logger.warning("Token encryption failed: %s", e)
        return value


def decrypt_token(value: str, encryption_key: str | None) -> str:
    """Decrypt a stored token. Returns value as-is if not encrypted or decryption fails."""
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value
    f = _get_fernet(encryption_key)
    if not f:
        return value
    try:
        raw = value[len(ENCRYPTED_PREFIX) :].encode()
        return f.decrypt(raw).decode()
    except InvalidToken:
        logger.warning("Token decryption failed (invalid token or wrong key)")
        return value
    except Exception as e:
        logger.warning("Token decryption failed: %s", e)
        return value

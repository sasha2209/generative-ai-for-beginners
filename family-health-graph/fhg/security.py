"""Encryption at rest, token handling and pseudonymisation."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)


class FieldCipher:
    """Authenticated symmetric encryption (Fernet: AES-128-CBC + HMAC-SHA256).

    In production the key should come from a KMS/HSM (envelope encryption with a
    per-tenant data key), never from a file on the application host.
    """

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode("utf-8")


def load_cipher(key: Optional[str], key_file: Path) -> FieldCipher:
    if key:
        return FieldCipher(key.encode())
    if key_file.exists():
        return FieldCipher(key_file.read_bytes().strip())
    log.warning(
        "FHG_ENCRYPTION_KEY not set; generating a development key at %s. "
        "Do not use this in production.", key_file,
    )
    key_file.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key()
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(new_key)
    return FieldCipher(new_key)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pseudonym(secret: str, user_id: str) -> str:
    """Stable, non-reversible research ID (keyed so it can't be brute-forced)."""
    return hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:16]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

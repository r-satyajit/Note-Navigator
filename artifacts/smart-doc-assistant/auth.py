from __future__ import annotations

import hashlib
import hmac
import re
import secrets


PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_HASH_LENGTH = 64
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_DUMMY_SALT = bytes.fromhex("91d7c6604678899f8c81c86b6d35e8d4")
_DUMMY_HASH = hashlib.scrypt(
    b"not-a-real-password",
    salt=_DUMMY_SALT,
    n=PASSWORD_SCRYPT_N,
    r=PASSWORD_SCRYPT_R,
    p=PASSWORD_SCRYPT_P,
    dklen=PASSWORD_HASH_LENGTH,
    maxmem=64 * 1024 * 1024,
)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def is_valid_email(email: str) -> bool:
    normalized = normalize_email(email)
    return len(normalized) <= 254 and EMAIL_PATTERN.fullmatch(normalized) is not None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use no more than {MAX_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > 1024:
        return "That password is too long."
    return None


def hash_password(password: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_LENGTH,
        maxmem=64 * 1024 * 1024,
    )
    return salt, password_hash


def verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    if len(password.encode("utf-8")) > 1024:
        return False
    actual_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_LENGTH,
        maxmem=64 * 1024 * 1024,
    )
    return hmac.compare_digest(actual_hash, expected_hash)


def perform_dummy_password_check(password: str) -> None:
    candidate = password.encode("utf-8")[:1024]
    hashlib.scrypt(
        candidate,
        salt=_DUMMY_SALT,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_LENGTH,
        maxmem=64 * 1024 * 1024,
    )

"""
auth.py — Parol xeshlash va tekshirish
"""
import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    """Parolni PBKDF2-SHA256 + tasodifiy salt bilan xeshlaydi."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return salt.hex() + ":" + key.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    """Kiritilgan parolni saqlangan xesh bilan solishtiradi (timing-safe)."""
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False
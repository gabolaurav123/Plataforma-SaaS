import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
from typing import Protocol
from urllib.parse import parse_qsl
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, UnidentifiedImageError
from .errors import DomainError
from .models.base import now


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def validate_init_data(raw: str, token: str, max_age: int = 300, timestamp: int | None = None) -> dict:
    if not token or len(raw) > 16384:
        raise DomainError("INVALID_AUTH", "Autenticación de Telegram no válida.", 401)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(pairs) != len(data):
            raise ValueError("duplicate")
        received = data.pop("hash")
        check = "\n".join(f"{key}={data[key]}" for key in sorted(data))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        age = (timestamp if timestamp is not None else now()) - int(data["auth_date"])
        if not hmac.compare_digest(expected, received) or not -30 <= age <= max_age:
            raise ValueError("expired or invalid")
        user = json.loads(data["user"])
        if type(user.get("id")) is not int or user["id"] <= 0 or user.get("is_bot"):
            raise ValueError("invalid user")
        return user
    except (ValueError, KeyError, TypeError):
        raise DomainError("INVALID_AUTH", "Abre de nuevo la Mini App desde Telegram.", 401) from None


class KeyWrapper(Protocol):
    """Implement with KMS GenerateDataKey/Encrypt/Decrypt for production vaults."""

    def wrap(self, key: bytes, aad: bytes) -> dict: ...
    def unwrap(self, envelope: dict, aad: bytes) -> bytes: ...


class LocalKeyring:
    def __init__(self, keys: dict[str, str], active: str):
        self.keys = {k: base64.b64decode(v, validate=True) for k, v in keys.items()}
        self.active = active
        if active not in self.keys or any(len(v) != 32 for v in self.keys.values()):
            raise ValueError("Configure a 32-byte base64 encryption keyring")

    def wrap(self, key, aad):
        nonce = os.urandom(12)
        return {
            "key_version": self.active,
            "wrapped_key": base64.b64encode(
                nonce + AESGCM(self.keys[self.active]).encrypt(nonce, key, aad)
            ).decode(),
        }

    def unwrap(self, envelope, aad):
        raw = base64.b64decode(envelope["wrapped_key"])
        return AESGCM(self.keys[envelope["key_version"]]).decrypt(raw[:12], raw[12:], aad)


class Vault:
    def __init__(self, wrapper: KeyWrapper):
        self.wrapper = wrapper

    def encrypt(self, value: str, context: str) -> dict:
        key, nonce, aad = os.urandom(32), os.urandom(12), context.encode()
        return {
            **self.wrapper.wrap(key, aad),
            "ciphertext": base64.b64encode(nonce + AESGCM(key).encrypt(nonce, value.encode(), aad)).decode(),
            "algorithm": "AES-256-GCM",
        }

    def decrypt(self, envelope: dict, context: str) -> str:
        aad = context.encode()
        raw = base64.b64decode(envelope["ciphertext"])
        return AESGCM(self.wrapper.unwrap(envelope, aad)).decrypt(raw[:12], raw[12:], aad).decode()


SECRET_FIELDS = re.compile(
    r"token|secret|ciphertext|authorization|init.?data|account|clabe|payload|password", re.I
)
TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b")


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_FIELDS.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return TOKEN_PATTERN.sub("[REDACTED]", value)
    return value


def random_secret():
    return secrets.token_urlsafe(32)


def inspect_image(data: bytes, limit: int):
    if not data or len(data) > limit:
        raise DomainError("UPLOAD_SIZE", "La imagen supera el tamaño permitido.", 413)
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"JPEG", "PNG", "WEBP"} or picture.width * picture.height > 20_000_000:
                raise ValueError("format or dimensions")
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            normalized = picture.convert("RGB")
            pixels = list(normalized.resize((9, 8)).convert("L").get_flattened_data())
            bits = sum(
                (pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x) for y in range(8) for x in range(8)
            )
            clean = io.BytesIO()
            normalized.save(clean, format="JPEG", quality=90)
            return {
                "sha256": digest(data),
                "perceptual_hash": f"{bits:016x}",
                "bytes": clean.getvalue(),
                "media_type": "image/jpeg",
            }
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise DomainError("UPLOAD_FORMAT", "Usa una imagen JPG, PNG o WebP válida.") from None


ROLES = {
    "OWNER": {"read", "configure", "payments", "sales", "support", "team", "export", "billing"},
    "SUPERVISOR": {"read", "configure", "payments", "sales", "support", "export"},
    "PAYMENTS": {"read", "payments"},
    "SALES": {"read", "sales"},
    "SUPPORT": {"read", "support"},
    "READ_ONLY": {"read"},
}


def require_role(role, permission):
    if permission not in ROLES.get(role, set()):
        raise DomainError("FORBIDDEN", "Tu rol no permite esta acción.", 403)

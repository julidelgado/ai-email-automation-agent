from __future__ import annotations

import base64
import hashlib
import hmac
import os

from app.config import Settings, get_settings


class CredentialCryptoService:
    """Lightweight symmetric encryption for integration credentials at rest."""

    _VERSION_PREFIX = "v1"
    _NONCE_SIZE = 16
    _MAC_SIZE = 32

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        key_material = (self.settings.credentials_encryption_key or "").strip()
        self._raw_key_material = key_material
        self._enc_key = hashlib.sha256(f"{key_material}:enc".encode("utf-8")).digest() if key_material else b""
        self._mac_key = hashlib.sha256(f"{key_material}:mac".encode("utf-8")).digest() if key_material else b""

    def is_configured(self) -> bool:
        return bool(self._raw_key_material)

    def require_configured(self) -> None:
        if not self.is_configured():
            raise RuntimeError(
                "Credential encryption key is not configured. Set APP_CREDENTIALS_ENCRYPTION_KEY."
            )

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None:
            return None
        self.require_configured()

        payload = plaintext.encode("utf-8")
        nonce = os.urandom(self._NONCE_SIZE)
        keystream = self._keystream(nonce=nonce, length=len(payload))
        ciphertext = _xor_bytes(payload, keystream)
        signed = self._sign_payload(nonce + ciphertext)
        encoded = _urlsafe_b64encode(signed)
        return f"{self._VERSION_PREFIX}.{encoded}"

    def decrypt(self, token: str | None) -> str | None:
        if token is None:
            return None
        self.require_configured()

        try:
            version, encoded = token.split(".", maxsplit=1)
        except ValueError as exc:
            raise RuntimeError("Encrypted value format is invalid.") from exc
        if version != self._VERSION_PREFIX:
            raise RuntimeError("Encrypted value version is unsupported.")

        signed = _urlsafe_b64decode(encoded)
        if len(signed) < (self._NONCE_SIZE + self._MAC_SIZE):
            raise RuntimeError("Encrypted value payload is invalid.")

        data = signed[:-self._MAC_SIZE]
        provided_mac = signed[-self._MAC_SIZE :]
        expected_mac = hmac.new(self._mac_key, data, hashlib.sha256).digest()
        if not hmac.compare_digest(provided_mac, expected_mac):
            raise RuntimeError("Encrypted value integrity check failed.")

        nonce = data[: self._NONCE_SIZE]
        ciphertext = data[self._NONCE_SIZE :]
        keystream = self._keystream(nonce=nonce, length=len(ciphertext))
        plaintext = _xor_bytes(ciphertext, keystream)
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Encrypted value could not be decoded.") from exc

    def _keystream(self, *, nonce: bytes, length: int) -> bytes:
        chunks = []
        produced = 0
        counter = 0
        while produced < length:
            block = hashlib.sha256(self._enc_key + nonce + counter.to_bytes(4, "big")).digest()
            chunks.append(block)
            produced += len(block)
            counter += 1
        return b"".join(chunks)[:length]

    def _sign_payload(self, data: bytes) -> bytes:
        mac = hmac.new(self._mac_key, data, hashlib.sha256).digest()
        return data + mac


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))

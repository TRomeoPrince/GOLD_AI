from __future__ import annotations

import os
from cryptography.fernet import Fernet, InvalidToken
from .owner_paths import service_home, state_directory


def _state_dir() -> Path:
    return state_directory(service_home())


KEY_PATH = _state_dir() / "credential_vault.key"


def _load_or_create_key() -> bytes:
    env_key = os.getenv("GOLD_AI_CREDENTIAL_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")

    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()

    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("Secret cannot be empty.")
    return Fernet(_load_or_create_key()).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return Fernet(_load_or_create_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt hosted MT5 credential.") from exc

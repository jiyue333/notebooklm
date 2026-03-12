from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings


class CredentialCrypto:
    # TODO 项目安全性调研 补充
    def __init__(self, settings: Settings) -> None:
        derived = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")


@lru_cache
def get_credential_crypto() -> CredentialCrypto:
    return CredentialCrypto(get_settings())

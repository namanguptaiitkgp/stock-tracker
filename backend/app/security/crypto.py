"""Field-level encryption for sensitive credentials (Kite/Gemini/Anthropic keys, tokens).

Production: requires `FIELD_ENCRYPTION_KEY` env var (32-byte url-safe base64; generate via
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

Development (`APP_ENV=development`) without `FIELD_ENCRYPTION_KEY` set: derives a stable
dev-only key from `APP_SECRET_KEY` so local setups keep working without yet another env var.

Stored values are Fernet tokens (`gAAAAA...`). The `EncryptedStr` TypeDecorator transparently
encrypts on write and decrypts on read. It also tolerates plaintext rows (`is_token=False`)
so a one-shot data migration can run idempotently.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

logger = logging.getLogger(__name__)

_FERNET_PREFIX = "gAAAAA"  # All Fernet tokens start with this magic.


def _derive_dev_key(seed: str) -> bytes:
    """Stable 32-byte key derived from APP_SECRET_KEY for dev-only fallback."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    settings = get_settings()
    raw = (getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "FIELD_ENCRYPTION_KEY is set but invalid. Generate a new one with "
                "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
            ) from exc

    if (settings.APP_ENV or "development").lower() == "development":
        logger.warning(
            "FIELD_ENCRYPTION_KEY not set; using dev-only key derived from APP_SECRET_KEY. "
            "Do NOT use this in production."
        )
        return Fernet(_derive_dev_key(settings.APP_SECRET_KEY))

    raise RuntimeError(
        "FIELD_ENCRYPTION_KEY env var is required in non-development mode. "
        "Generate via `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
    )


def is_token(value: str | None) -> bool:
    """True if the value looks like a Fernet ciphertext."""
    return bool(value) and isinstance(value, str) and value.startswith(_FERNET_PREFIX)


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return plaintext
    if is_token(plaintext):
        return plaintext  # already encrypted; idempotent
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None or ciphertext == "":
        return ciphertext
    if not is_token(ciphertext):
        # Pre-migration plaintext row — tolerate, log once.
        logger.debug("decrypt(): value is not a Fernet token; returning as plaintext")
        return ciphertext
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.exception("decrypt(): InvalidToken — wrong FIELD_ENCRYPTION_KEY?")
        raise


class EncryptedStr(TypeDecorator):
    """SQLAlchemy column type that encrypts on write, decrypts on read.

    Underlying storage is `String(length)` (default 512). Fernet tokens for short
    inputs (<64 chars) land around 100 chars; 512 leaves comfortable headroom.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, **kwargs):
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value, dialect):  # noqa: D401
        return encrypt(value)

    def process_result_value(self, value, dialect):  # noqa: D401
        return decrypt(value)

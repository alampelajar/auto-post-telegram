from cryptography.fernet import Fernet

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()

    if not settings.session_encryption_key:
        raise RuntimeError(
            "SESSION_ENCRYPTION_KEY belum diatur di .env"
        )

    try:
        return Fernet(
            settings.session_encryption_key.encode()
        )
    except Exception as exc:
        raise RuntimeError(
            "SESSION_ENCRYPTION_KEY tidak valid."
        ) from exc


def encrypt_session(value: str) -> str:
    return _get_fernet().encrypt(
        value.encode()
    ).decode()


def decrypt_session(value: str) -> str:
    return _get_fernet().decrypt(
        value.encode()
    ).decode()
import os, base64
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash
hasher = PasswordHash.recommended()
def _fernet():
    raw = os.getenv('CREDENTIAL_ENCRYPTION_KEY', '')
    if not raw: raise RuntimeError('CREDENTIAL_ENCRYPTION_KEY must be configured to store credentials')
    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
        if len(decoded) != 32: raise ValueError()
        key = base64.urlsafe_b64encode(decoded)
    except Exception as exc: raise RuntimeError('CREDENTIAL_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key') from exc
    return Fernet(key)
def encrypt_secret(value: str) -> str: return _fernet().encrypt(value.encode()).decode()
def decrypt_secret(value: str) -> str: return _fernet().decrypt(value.encode()).decode()

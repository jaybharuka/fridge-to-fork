"""
Seals the Swiggy access token so the browser never holds it in readable form.

Swiggy issues no refresh token and the app has no persistent store (Render free plan: one instance, ephemeral disk), so
the session stays stateless and travels with the client, but ENCRYPTED: Fernet = AES-128-CBC + HMAC-SHA256 with an
issue timestamp, keyed from SECRET_KEY. The same sealed blob is what the session cookie holds and what
/auth/session-token hands the page as its bearer, so neither is a plaintext (or merely signed, hence decodable) token.

Tradeoffs, deliberately accepted (see the 2026-10 security discussion): no server-side revocation (a leaked blob works
until it expires; logout only clears the cookie), and rotating SECRET_KEY invalidates every session (one re-login).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret: str) -> Fernet:
    # Domain-separated from the cookie signer's use of the same SECRET_KEY.
    key = hashlib.sha256(b"f2f-token-vault:v1:" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(access_token: str, expires_at: str, secret: str) -> str:
    """Encrypts the token with its expiry. `expires_at` is an ISO-8601 timestamp."""
    payload = json.dumps({"t": access_token, "exp": expires_at}).encode()
    return _fernet(secret).encrypt(payload).decode()


def unseal(blob: str | None, secret: str, max_age_seconds: int) -> tuple[str, str] | None:
    """(access_token, expires_at) if `blob` is authentic, younger than `max_age_seconds` and not past its own expiry;
    None for anything else (tampered, wrong key, malformed, too old, expired). Never raises."""
    if not blob or not isinstance(blob, str):
        return None
    try:
        data = json.loads(_fernet(secret).decrypt(blob.encode(), ttl=max_age_seconds))
        token, expires_at = data["t"], data["exp"]
        if not token or not isinstance(token, str) or not isinstance(expires_at, str):
            return None
        if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            return None
        return token, expires_at
    except (InvalidToken, ValueError, KeyError, TypeError):
        return None

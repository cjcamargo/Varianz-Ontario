from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

# Stable identity for the credential-free demo. Every anonymous caller shares it,
# so the public demo keeps working while sessions still carry a concrete owner.
DEMO_USER_ID = uuid5(NAMESPACE_URL, "varianz:demo-user")

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    anonymous: bool


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def verify_supabase_jwt(token: str, secret: str, *, now: float | None = None) -> dict:
    """Verify a Supabase-issued HS256 access token without external dependencies.

    Only the signature and expiry are enforced; downstream authorization relies on
    the ``sub`` claim mapped to ``auth.users`` by the database RLS policies.
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise HTTPException(401, "invalid_token") from exc
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(401, "invalid_token") from exc
    if header.get("alg") != "HS256":
        raise HTTPException(401, "unsupported_token_alg")
    expected = hmac.new(
        secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "invalid_token_signature")
    expiry = claims.get("exp")
    if isinstance(expiry, (int, float)) and expiry < (now or time.time()):
        raise HTTPException(401, "token_expired")
    return claims


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None or not credentials.credentials:
        if settings.auth_required:
            raise HTTPException(401, "authentication_required")
        return Principal(DEMO_USER_ID, anonymous=True)
    if not settings.supabase_jwt_secret:
        raise HTTPException(503, "auth_not_configured")
    claims = verify_supabase_jwt(credentials.credentials, settings.supabase_jwt_secret)
    subject = claims.get("sub")
    try:
        user_id = UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise HTTPException(401, "token_missing_subject") from exc
    return Principal(user_id, anonymous=False)

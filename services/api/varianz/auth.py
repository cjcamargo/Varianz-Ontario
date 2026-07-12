from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

# Stable identity for the credential-free demo. Every anonymous caller shares it,
# so the public demo keeps working while sessions still carry a concrete owner.
DEMO_USER_ID = uuid5(NAMESPACE_URL, "varianz:demo-user")

_bearer = HTTPBearer(auto_error=False)
_verified_tokens: dict[str, tuple[float, dict]] = {}


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


def verify_supabase_access_token(
    token: str,
    supabase_url: str,
    publishable_key: str,
    *,
    now: float | None = None,
) -> dict:
    """Verify a hosted Supabase token with Auth, independent of its signing algorithm."""
    checked_at = now or time.time()
    cached = _verified_tokens.get(token)
    if cached and cached[0] > checked_at:
        return cached[1]
    try:
        response = httpx.get(
            f"{supabase_url.rstrip('/')}/auth/v1/user",
            headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.RequestError as exc:
        raise HTTPException(503, "auth_provider_unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(401, "invalid_or_expired_token")
    user = response.json()
    subject = user.get("id")
    if not subject:
        raise HTTPException(401, "token_missing_subject")
    claims = {"sub": subject, "email": user.get("email")}
    _verified_tokens[token] = (checked_at + 60, claims)
    if len(_verified_tokens) > 1000:
        expired = [key for key, (expiry, _) in _verified_tokens.items() if expiry <= checked_at]
        for key in expired:
            _verified_tokens.pop(key, None)
    return claims


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if credentials is None or not credentials.credentials:
        if settings.auth_required:
            raise HTTPException(401, "authentication_required")
        return Principal(DEMO_USER_ID, anonymous=True)
    if settings.supabase_url and settings.supabase_publishable_key:
        claims = verify_supabase_access_token(
            credentials.credentials,
            settings.supabase_url,
            settings.supabase_publishable_key,
        )
    elif settings.supabase_jwt_secret:
        claims = verify_supabase_jwt(credentials.credentials, settings.supabase_jwt_secret)
    else:
        raise HTTPException(503, "auth_not_configured")
    subject = claims.get("sub")
    try:
        user_id = UUID(str(subject))
    except (TypeError, ValueError) as exc:
        raise HTTPException(401, "token_missing_subject") from exc
    return Principal(user_id, anonymous=False)

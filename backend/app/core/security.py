from __future__ import annotations

import hashlib
import hmac
import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import datetime
from time import time
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import User
from backend.app.db.session import get_db


ADMIN_ROLES = {"SUPER_ADMIN", "ADMIN"}
ROLE_ORDER = {"VIEWER": 10, "OPERATOR": 20, "ADMIN": 30, "SUPER_ADMIN": 40}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    name: str
    role: str
    permissions: list[str]


def normalize_role(role: str | None) -> str:
    normalized = str(role or "OPERATOR").strip().upper()
    return normalized if normalized in ROLE_ORDER else "OPERATOR"


def normalize_permissions(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": normalize_role(user.role),
        "permissions": normalize_permissions(user.permissions_json),
        "isActive": bool(user.is_active),
        **timestamp_fields("lastLoginAt", user.last_login_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
        **timestamp_fields("createdAt", user.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
        **timestamp_fields("updatedAt", user.updated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
    }


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_access_token(payload: dict) -> dict:
    settings = get_settings()
    now = int(time())
    expires_at = now + max(1, settings.auth_token_ttl_minutes) * 60
    claims = {
        "sub": str(payload.get("id") or ""),
        "name": str(payload.get("name") or payload.get("id") or ""),
        "role": normalize_role(str(payload.get("role") or "VIEWER")),
        "iat": now,
        "exp": expires_at,
    }
    if not claims["sub"]:
        raise ValueError("Token subject is required")
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([
        _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _base64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
    ])
    signature = hmac.new(settings.auth_jwt_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return {
        "accessToken": f"{signing_input}.{_base64url_encode(signature)}",
        "tokenType": "bearer",
        "expiresAt": datetime.utcfromtimestamp(expires_at).isoformat() + "Z",
    }


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        header_part, claims_part, signature_part = token.split(".", 2)
        signing_input = f"{header_part}.{claims_part}"
        expected = _base64url_encode(
            hmac.new(settings.auth_jwt_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature_part, expected):
            raise ValueError("Invalid token signature")
        header = json.loads(_base64url_decode(header_part))
        if header.get("alg") != "HS256":
            raise ValueError("Unsupported token algorithm")
        claims = json.loads(_base64url_decode(claims_part))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    try:
        expired = int(claims.get("exp") or 0) < int(time())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    if expired:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return claims


def ensure_admin_user(session: Session) -> User:
    user = session.get(User, "dobedub")
    if user:
        if not user.is_active or normalize_role(user.role) != "SUPER_ADMIN":
            user.is_active = True
            user.role = "SUPER_ADMIN"
            user.updated_at = utc_now().replace(tzinfo=None)
            session.commit()
        return user
    user = User(
        id="dobedub",
        name="장균은",
        email=None,
        role="SUPER_ADMIN",
        password_hash=None,
        permissions_json=["admin:*"],
        is_active=True,
    )
    session.add(user)
    session.commit()
    return user


def current_user_from_headers(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        claims = decode_access_token(token)
        return _current_user_from_claims(db, claims)
    raise HTTPException(status_code=401, detail="Authentication is required")


def _current_user_from_claims(session: Session, claims: dict) -> CurrentUser:
    from backend.app.services.permission_service import effective_permission_codes

    user = session.get(User, str(claims.get("sub") or ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return CurrentUser(
        id=user.id,
        name=user.name or user.id,
        role=normalize_role(user.role),
        permissions=effective_permission_codes(session, user),
    )


def require_admin(current_user: CurrentUser) -> CurrentUser:
    if current_user.role not in ADMIN_ROLES and "admin:*" not in current_user.permissions:
        raise HTTPException(status_code=403, detail="Admin permission is required")
    return current_user


def has_permission(permission_codes: list[str], required_permission: str) -> bool:
    if "admin:*" in permission_codes:
        return True
    if required_permission in permission_codes:
        return True
    domain = required_permission.split(":", 1)[0]
    return f"{domain}:*" in permission_codes


def require_permission(required_permission: str):
    def dependency(current_user: CurrentUser = Depends(current_user_from_headers)) -> CurrentUser:
        if has_permission(current_user.permissions, required_permission):
            return current_user
        raise HTTPException(status_code=403, detail=f"Permission is required: {required_permission}")

    return dependency


def require_any_permission(required_permissions: list[str] | tuple[str, ...]):
    def dependency(current_user: CurrentUser = Depends(current_user_from_headers)) -> CurrentUser:
        if any(has_permission(current_user.permissions, permission) for permission in required_permissions):
            return current_user
        joined = ", ".join(required_permissions)
        raise HTTPException(status_code=403, detail=f"One of permissions is required: {joined}")

    return dependency

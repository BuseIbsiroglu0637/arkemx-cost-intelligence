"""Pilot auth. Before public rollout add rate limiting, invitations, MFA and cookie-based sessions."""
import os
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

HASHER = PasswordHasher()
BEARER = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"
DEV_KEY = "INSECURE-DEV-ONLY-CHANGE-BEFORE-DEPLOY"


def key():
    secret = os.getenv("JWT_SECRET")
    if not secret or secret == "REPLACE_WITH_LONG_RANDOM_SECRET":
        if os.getenv("ENVIRONMENT", "development") != "development":
            raise RuntimeError("JWT_SECRET must be configured outside development")
        return DEV_KEY
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must have >=32 characters")
    return secret


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return HASHER.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False


def create_token(user: User) -> str:
    return jwt.encode({"sub": user.id, "org": user.organization_id,
                       "exp": datetime.now(timezone.utc) + timedelta(hours=8)},
                      key(), algorithm=ALGORITHM)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(BEARER),
                 db: Session = Depends(get_db)) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = jwt.decode(credentials.credentials, key(), algorithms=[ALGORITHM],
                            options={"require": ["sub", "exp", "org"]})
        user = db.get(User, claims["sub"])
        if user is None or user.organization_id != claims["org"]:
            raise ValueError("Invalid token owner")
        return user
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

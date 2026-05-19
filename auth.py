"""
Authentication utilities: JWT tokens, password hashing, user CRUD, audit logging.
"""
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import AuditLog, Subscription, User, get_db

_SECRET_KEY = os.getenv("SECRET_KEY")
if not _SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set before starting the server")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Minimum password requirements
_PASSWORD_MIN_LEN = 8
_PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
http_bearer = HTTPBearer()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def validate_password_strength(password: str) -> None:
    if len(password) < _PASSWORD_MIN_LEN:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LEN} characters")
    if not _PASSWORD_PATTERN.match(password):
        raise ValueError("Password must contain uppercase, lowercase, and a digit")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "access"},
        _SECRET_KEY, algorithm=ALGORITHM,
    )


def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "refresh"},
        _SECRET_KEY, algorithm=ALGORITHM,
    )


def _decode(token: str, expected_type: str) -> int:
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid token type")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Malformed token")
    return int(sub)


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, email: str, password: str, full_name: str = "") -> User:
    validate_password_strength(password)
    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name.strip() or None,
        verification_token=secrets.token_urlsafe(32),
    )
    db.add(user)
    db.flush()
    db.add(Subscription(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user:
        # Constant-time compare even for missing user to prevent enumeration
        pwd_context.dummy_verify()
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = _decode(credentials.credentials, "access")
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


def refresh_access_token(refresh_token: str, db: Session) -> str:
    user_id = _decode(refresh_token, "refresh")
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return create_access_token(user.id)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def log_audit(
    db: Session,
    action: str,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[str] = None,
    success: bool = True,
) -> None:
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
        details=details,
        success=success,
    ))
    db.commit()

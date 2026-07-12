"""비밀번호 해시 + JWT 발급/검증 유틸 (작업 3-1).

api-spec.md §2 계약:
- access 토큰 수명 = jwt_access_expires_seconds(기본 900초) = 응답의 expires_in
- refresh 토큰은 여기서 다루지 않는다 (원문은 클라이언트에게만, DB엔 해시만 — 작업 3-3에서 별도 구현)
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_JWT_ALGORITHM = "HS256"
_ACCESS_TOKEN_TYPE = "access"

# bcrypt 알고리즘 자체의 상한 (UTF-8 바이트 기준). 한글은 1자=3바이트라
# 24자만 넘어도 초과할 수 있으므로, signup 스키마의 문자 수 제한과 별개로 방어한다.
_MAX_PASSWORD_BYTES = 72


# ============================================================
# 비밀번호 해시
# ============================================================

class PasswordTooLongError(ValueError):
    """비밀번호가 bcrypt 한계(72바이트, UTF-8 기준)를 초과함. 라우터에서 400으로 변환."""


def hash_password(plain_password: str) -> str:
    """bcrypt로 비밀번호를 해시한다. users.password_hash에 저장할 값."""
    encoded = plain_password.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"비밀번호는 최대 {_MAX_PASSWORD_BYTES}바이트(UTF-8)까지 가능합니다 "
            f"(입력: {len(encoded)}바이트, 한글은 1자당 3바이트)."
        )
    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """로그인 시 입력 비밀번호와 저장된 해시를 비교한다.

    72바이트 초과 입력은 애초에 그 길이로 해시된 적이 없으므로 예외 대신 False.
    (로그인 시도 한 번으로 서버가 죽으면 안 되므로 hash_password와 달리 조용히 거부)
    """
    encoded = plain_password.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))


# ============================================================
# JWT access 토큰
# ============================================================

class TokenExpiredError(Exception):
    """access 토큰 만료. 라우터에서 401 TOKEN_EXPIRED로 변환한다 (api-spec §6.2)."""


class TokenInvalidError(Exception):
    """서명 위조/형식 오류 등 만료 외의 모든 토큰 오류."""


def create_access_token(user_id: str) -> tuple[str, int]:
    """access 토큰을 발급한다. 반환: (토큰 문자열, 수명 초) — 후자는 응답의 expires_in에 그대로 쓴다."""
    now = datetime.now(timezone.utc)
    expires_in = settings.jwt_access_expires_seconds
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": _ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)
    return token, expires_in


# ============================================================
# refresh 토큰 (JWT 아님 — 불투명 랜덤값 + DB 해시 대조, db-schema refresh_tokens)
# ============================================================

def generate_refresh_token() -> str:
    """refresh 토큰 원문을 생성한다. 원문은 클라이언트에게만 주고 DB엔 해시만 저장."""
    return secrets.token_urlsafe(48)  # 64자 URL-safe 랜덤


def hash_refresh_token(token: str) -> str:
    """refresh_tokens.token_hash에 저장/대조할 SHA-256 해시(hex 64자)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_access_token(token: str) -> str:
    """access 토큰을 검증하고 user_id(sub)를 반환한다.

    실패 시 TokenExpiredError(만료) 또는 TokenInvalidError(그 외)를 던진다.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError() from e
    except jwt.InvalidTokenError as e:
        raise TokenInvalidError(str(e)) from e

    if payload.get("type") != _ACCESS_TOKEN_TYPE:
        raise TokenInvalidError("access 토큰이 아님")
    return payload["sub"]

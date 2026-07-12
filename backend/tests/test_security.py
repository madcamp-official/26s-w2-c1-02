"""app/core/security.py 회귀 테스트 (작업 3-1).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_security.py -v

DB 접속이 필요 없다 — 이 모듈은 순수 함수(해시·JWT)만 다룬다.
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from app.core.config import settings
from app.core.security import (
    PasswordTooLongError,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ============================================================
# 비밀번호 해시
# ============================================================

class TestPasswordHashing:
    def test_hash_is_salted_differently_each_time(self):
        """같은 비밀번호도 해시할 때마다 값이 달라야 한다 (salt 적용 확인)."""
        pw = "s3cret-p@ssw0rd"
        assert hash_password(pw) != hash_password(pw)

    def test_hash_does_not_contain_plaintext(self):
        pw = "s3cret-p@ssw0rd"
        assert pw not in hash_password(pw)

    def test_correct_password_verifies(self):
        pw = "s3cret-p@ssw0rd"
        assert verify_password(pw, hash_password(pw)) is True

    def test_wrong_password_rejected(self):
        h = hash_password("correct-password")
        assert verify_password("wrong-password", h) is False

    def test_korean_password_roundtrip(self):
        """실사용자 대부분이 한글 비밀번호를 쓸 것이므로 반드시 확인."""
        pw = "안녕하세요반갑습니다1234!"
        assert verify_password(pw, hash_password(pw)) is True

    def test_password_over_72_bytes_raises_on_hash(self):
        """bcrypt 알고리즘 자체의 72바이트(UTF-8) 상한.

        한글은 1자=3바이트라 24자만 넘어도 걸릴 수 있다.
        회원가입 라우터(3-2)는 이 예외를 400으로 변환해야 한다.
        """
        too_long = "가" * 30  # 90바이트
        with pytest.raises(PasswordTooLongError):
            hash_password(too_long)

    def test_password_over_72_bytes_rejected_on_verify_not_crash(self):
        """길이 초과 입력으로 로그인을 시도해도 서버가 죽지 않고 조용히 실패해야 한다."""
        normal_hash = hash_password("normal-password")
        too_long = "가" * 30
        assert verify_password(too_long, normal_hash) is False

    def test_72_byte_boundary_does_not_truncate_silently(self):
        """71바이트까지 같고 72바이트째만 다른 두 비밀번호가 같다고 오판하면 안 된다."""
        base = "a" * 71
        pw_a, pw_b = base + "X", base + "Y"
        assert verify_password(pw_b, hash_password(pw_a)) is False


# ============================================================
# JWT access 토큰
# ============================================================

class TestAccessToken:
    def test_expires_in_matches_config(self):
        _, expires_in = create_access_token(user_id="usr_test123")
        assert expires_in == settings.jwt_access_expires_seconds

    def test_token_has_jwt_shape(self):
        token, _ = create_access_token(user_id="usr_test123")
        assert token.count(".") == 2  # header.payload.signature

    def test_decode_recovers_user_id(self):
        token, _ = create_access_token(user_id="usr_test123")
        assert decode_access_token(token) == "usr_test123"

    def test_non_ascii_user_id_roundtrip(self):
        token, _ = create_access_token(user_id="usr_한글아이디테스트")
        assert decode_access_token(token) == "usr_한글아이디테스트"

    def test_tampered_signature_rejected(self):
        token, _ = create_access_token(user_id="usr_test123")
        tampered = token[:-4] + "abcd"
        with pytest.raises(TokenInvalidError):
            decode_access_token(tampered)

    def test_token_signed_with_wrong_secret_rejected(self):
        forged = pyjwt.encode(
            {"sub": "usr_evil", "type": "access"}, "wrong-secret", algorithm="HS256"
        )
        with pytest.raises(TokenInvalidError):
            decode_access_token(forged)

    def test_expired_token_raises_expired_not_invalid(self):
        """만료는 반드시 TokenExpiredError여야 한다 — 라우터가 이걸로 401 TOKEN_EXPIRED를 낸다."""
        payload = {
            "sub": "usr_test123",
            "type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(seconds=1000),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=100),
        }
        expired = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(TokenExpiredError):
            decode_access_token(expired)

    @pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c"])
    def test_malformed_token_raises_invalid_not_crash(self, garbage):
        """빈 문자열이나 형식이 아예 다른 값도 500이 아니라 TokenInvalidError여야 한다."""
        with pytest.raises(TokenInvalidError):
            decode_access_token(garbage)

    @pytest.mark.parametrize("bad_sub", [None, 12345, "", {"nested": "x"}])
    def test_missing_or_nonstring_sub_rejected_not_crash(self, bad_sub):
        """sub가 없거나 문자열이 아니면 KeyError(→500)가 아니라 TokenInvalidError여야 한다.
        (재검증에서 발견: sub 없는 유효 서명 토큰이 500을 유발했음)"""
        payload = {
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=900),
        }
        if bad_sub is not None:
            payload["sub"] = bad_sub
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(TokenInvalidError):
            decode_access_token(token)

    def test_alg_none_token_rejected(self):
        """alg=none(서명 없는) 토큰은 반드시 거부해야 한다 (JWT 고전 취약점)."""
        import base64
        import json

        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
        body = base64.urlsafe_b64encode(
            json.dumps({"sub": "usr_x", "type": "access"}).encode()
        ).rstrip(b"=")
        forged = f"{header.decode()}.{body.decode()}."
        with pytest.raises(TokenInvalidError):
            decode_access_token(forged)

    def test_refresh_type_token_rejected_as_access(self):
        """type이 access가 아니면(예: 나중에 만들 refresh 토큰) 거부해야 한다."""
        payload = {
            "sub": "usr_test123",
            "type": "refresh",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=900),
        }
        wrong_type = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(TokenInvalidError):
            decode_access_token(wrong_type)

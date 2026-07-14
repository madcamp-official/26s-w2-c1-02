"""마이페이지(/users/me) 스키마 검증 (Step 4 작업 1). 순수 Pydantic — DB 불필요.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_user_schemas.py -v

api-spec §2.1 계약. GET 응답은 auth.UserOut 재사용, 요청은 여기 2종.
"""

import pytest
from pydantic import ValidationError

from app.schemas.auth import UserOut
from app.schemas.user import PasswordChangeRequest, ProfileUpdateRequest
from app.schemas.user import UserOut as ReexportedUserOut


class TestGetResponseReuse:
    """GET /users/me 응답 = UserOut 재사용 (id·name·username·email·email_verified)."""

    def test_user_out_is_reexported_same_class(self):
        """user.py가 auth.UserOut을 그대로 재노출 — 별도 사본을 만들지 않는다."""
        assert ReexportedUserOut is UserOut

    def test_shape_matches_spec_fields(self):
        u = UserOut(id="usr_1", name="박준서", username="junseo",
                    email="bjsbest0326@gmail.com", email_verified=True)
        dumped = u.model_dump()
        # api-spec §2.1 예시의 키 집합과 일치
        assert set(dumped) == {"id", "name", "username", "email", "email_verified"}
        assert dumped["email_verified"] is True

    def test_email_verified_false(self):
        u = UserOut(id="usr_1", name="아무개", username="nobody",
                    email="a@b.com", email_verified=False)
        assert u.email_verified is False


class TestProfileUpdate:
    def test_valid_parses(self):
        assert ProfileUpdateRequest(name="새닉네임").name == "새닉네임"

    def test_name_stripped(self):
        """SignupRequest와 동일 규약 — 앞뒤 공백 제거."""
        assert ProfileUpdateRequest(name="  새닉네임  ").name == "새닉네임"

    @pytest.mark.parametrize("value", [
        "",           # 빈 이름
        "   ",        # 공백만 → strip 후 빈값
        "\t\n ",      # 공백류만
        "가" * 31,    # 30자 초과
    ])
    def test_invalid_name_rejected(self, value):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(name=value)

    def test_boundaries_ok(self):
        assert len(ProfileUpdateRequest(name="가" * 30).name) == 30
        assert ProfileUpdateRequest(name="가").name == "가"

    def test_name_length_checked_after_strip(self):
        """30자 + 뒤 공백 → strip 후 30자라 통과 (검사 순서 고정)."""
        assert len(ProfileUpdateRequest(name="가" * 30 + "  ").name) == 30

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest()

    def test_unknown_field_rejected(self):
        """오타 필드(nmae)를 조용히 무시하지 않고 422 (extra=forbid)."""
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(nmae="오타")


class TestPasswordChange:
    def test_valid_parses(self):
        pw = PasswordChangeRequest(current_password="old-pass", new_password="new-pass-123")
        assert pw.current_password == "old-pass"
        assert pw.new_password == "new-pass-123"

    def test_new_password_min_length(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="old", new_password="short7!")  # 7자

    def test_new_password_boundary_8_ok(self):
        assert PasswordChangeRequest(current_password="o", new_password="12345678").new_password == "12345678"

    def test_new_password_max_length(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="old", new_password="a" * 129)

    def test_whitespace_preserved_in_passwords(self):
        """비밀번호는 공백도 유효 문자 — 절대 스트립하지 않는다."""
        pw = PasswordChangeRequest(current_password="  a b  ", new_password="  keeps  space")
        assert pw.current_password == "  a b  "
        assert pw.new_password == "  keeps  space"

    def test_whitespace_only_new_password_ok_if_long_enough(self):
        """공백만 8자 이상이어도 스트립하지 않으므로 통과 (동작 고정)."""
        assert PasswordChangeRequest(current_password="o", new_password=" " * 8).new_password == " " * 8

    @pytest.mark.parametrize("body", [
        {"new_password": "new-pass-123"},                        # current 누락
        {"current_password": "old"},                             # new 누락
        {"current_password": "", "new_password": "new-pass-1"},  # current 빈값
    ])
    def test_missing_or_empty_rejected(self, body):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(**body)

    def test_unknown_field_rejected(self):
        """new_pasword 같은 오타를 조용히 흘리면 위험 → 422 (extra=forbid)."""
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="old", new_pasword="new-pass-123")

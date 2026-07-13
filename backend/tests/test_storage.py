"""파일 스토리지 + 서명 URL 회귀 테스트 (작업 5).

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_storage.py -v

디스크에 실제로 쓰고 읽는다. 테스트 키는 전부 'sessions/ses_storagetest/'
아래에 두고, 끝나면 그 디렉터리를 통째로 지운다.
"""

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.core.storage import _BASE_DIR
from app.main import app

client = TestClient(app)

SES = "ses_storagetest"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    target = _BASE_DIR / "sessions" / SES
    if target.exists():
        shutil.rmtree(target)


class TestKeyConventions:
    def test_key_builders_match_spec(self):
        assert storage.material_key(SES) == f"sessions/{SES}/material.pdf"
        assert storage.recording_key(SES, "m4a") == f"sessions/{SES}/recording.m4a"
        assert storage.tts_key(SES, "q_1") == f"sessions/{SES}/tts/q_1.wav"
        assert storage.answer_key(SES, "q_1", "m4a") == f"sessions/{SES}/answers/q_1.m4a"

    def test_ext_leading_dot_normalized(self):
        assert storage.recording_key(SES, ".wav") == f"sessions/{SES}/recording.wav"


class TestSaveLoadDelete:
    def test_save_then_load_roundtrip(self):
        key = storage.material_key(SES)
        storage.save(key, b"%PDF-1.4 fake")
        assert storage.load(key) == b"%PDF-1.4 fake"
        assert storage.exists(key) is True

    def test_delete_is_idempotent(self):
        key = storage.recording_key(SES, "wav")
        storage.save(key, b"audio")
        assert storage.delete(key) is True
        assert storage.delete(key) is False  # 두 번째는 조용히 False
        assert storage.exists(key) is False

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            storage.load(f"sessions/{SES}/nope.pdf")


class TestPathTraversal:
    """경로 탈출 방어 — 스토리지에서 가장 중요한 보안 지점."""

    @pytest.mark.parametrize("evil", [
        "../../../etc/passwd",
        "sessions/../../secret",
        "/etc/passwd",
        "sessions/\x00/x",
        "..\\..\\windows",
    ])
    def test_evil_keys_rejected(self, evil):
        with pytest.raises(storage.StorageError):
            storage._resolve(evil)

    def test_save_cannot_escape_base(self):
        with pytest.raises(storage.StorageError):
            storage.save("../escaped.txt", b"x")


class TestSignedUrl:
    def test_signed_url_shape(self):
        url = storage.signed_url(storage.material_key(SES))
        assert url.startswith(f"/api/v1/files/sessions/{SES}/material.pdf?")
        assert "expires=" in url and "sig=" in url

    def test_verify_accepts_valid(self):
        key = storage.material_key(SES)
        url = storage.signed_url(key, expires_in=60)
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        storage.verify(key, int(q["expires"]), q["sig"])  # 예외 없어야 함

    def test_tampered_signature_rejected(self):
        key = storage.material_key(SES)
        url = storage.signed_url(key, expires_in=60)
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        with pytest.raises(storage.StorageError):
            storage.verify(key, int(q["expires"]), "deadbeef")

    def test_signature_bound_to_key(self):
        """A 파일 서명을 B 파일에 재사용 불가 (서명은 key에 묶임)."""
        url = storage.signed_url(storage.material_key(SES), expires_in=60)
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        with pytest.raises(storage.StorageError):
            storage.verify(storage.recording_key(SES, "wav"), int(q["expires"]), q["sig"])

    def test_expired_url_rejected(self):
        key = storage.material_key(SES)
        expires = int(time.time()) - 10  # 이미 만료
        sig = storage._sign(key, expires)
        with pytest.raises(storage.StorageError):
            storage.verify(key, expires, sig)


class TestDownloadEndpoint:
    def test_valid_signed_url_downloads(self):
        key = storage.material_key(SES)
        storage.save(key, b"%PDF-1.4 hello")
        res = client.get(storage.signed_url(key))
        assert res.status_code == 200
        assert res.content == b"%PDF-1.4 hello"
        assert res.headers["content-type"] == "application/pdf"

    def test_no_signature_403(self):
        key = storage.material_key(SES)
        storage.save(key, b"x")
        res = client.get(f"/api/v1/files/{key}")  # expires/sig 없음 → 422 (필수 쿼리)
        assert res.status_code == 422

    def test_tampered_signature_403(self):
        key = storage.material_key(SES)
        storage.save(key, b"x")
        res = client.get(f"/api/v1/files/{key}?expires={int(time.time())+60}&sig=bad")
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "INVALID_SIGNATURE"

    def test_expired_signed_url_410(self):
        key = storage.material_key(SES)
        storage.save(key, b"x")
        expires = int(time.time()) - 5
        res = client.get(f"/api/v1/files/{key}?expires={expires}&sig={storage._sign(key, expires)}")
        assert res.status_code == 410
        assert res.json()["error"]["code"] == "URL_EXPIRED"

    def test_valid_signature_missing_file_404(self):
        key = storage.tts_key(SES, "q_ghost")
        res = client.get(storage.signed_url(key))  # 서명은 유효, 파일은 없음
        assert res.status_code == 404

    def test_traversal_via_url_blocked(self):
        """서명을 억지로 맞춰도 경로 탈출 키는 로드 단계에서 막힌다."""
        evil = "../../secret.txt"
        res = client.get(f"/api/v1/files/{evil}?expires={int(time.time())+60}"
                         f"&sig={storage._sign(evil, int(time.time())+60)}")
        assert res.status_code in (403, 404)  # StorageError → 403, 혹은 라우팅 자체 회피

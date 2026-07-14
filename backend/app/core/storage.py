"""파일 스토리지 + 서명 URL (작업 5, api-spec A10 · db-schema §5).

방식(스코프 컷 최소안): KCLOUD VM 로컬 디스크에 저장하고, DB에는 storage_key(경로)만
둔다. 재생용 `*_url`은 만료시각 + HMAC 서명이 붙은 자체 다운로드 URL로 그때그때 발급한다
(S3 presigned URL의 흉내). 서명이 맞고 안 만료됐을 때만 GET /files/{key}가 파일을 준다.

storage_key 규약 (팀원3 TTS 저장·삭제 cascade가 공유):
    sessions/{session_id}/material.pdf
    sessions/{session_id}/recording.{ext}
    sessions/{session_id}/tts/{question_id}.{ext}
    sessions/{session_id}/answers/{question_id}.{ext}
"""

import hashlib
import hmac
from pathlib import Path

from app.core.config import settings

# 상대 storage_dir은 backend/ (이 파일의 3단계 상위) 기준으로 고정 — 실행 위치와 무관.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BASE_DIR = Path(settings.storage_dir)
if not _BASE_DIR.is_absolute():
    _BASE_DIR = _BACKEND_ROOT / _BASE_DIR


class StorageError(Exception):
    """스토리지 계층 오류 (경로 위반·서명 불일치·만료). 라우터에서 4xx로 변환."""


# ── storage_key 빌더 (규약 한 곳에서만 생성) ──────────────────────────

def material_key(session_id: str, ext: str = "pdf") -> str:
    return f"sessions/{session_id}/material.{ext.lstrip('.')}"


def recording_key(session_id: str, ext: str) -> str:
    return f"sessions/{session_id}/recording.{ext.lstrip('.')}"


def recording_chunk_key(session_id: str, seq: int, ext: str = "wav") -> str:
    return f"sessions/{session_id}/chunks/{seq:04d}.{ext.lstrip('.')}"


def tts_key(session_id: str, question_id: str, ext: str = "wav") -> str:
    return f"sessions/{session_id}/tts/{question_id}.{ext.lstrip('.')}"


def answer_key(session_id: str, question_id: str, ext: str) -> str:
    return f"sessions/{session_id}/answers/{question_id}.{ext.lstrip('.')}"


# ── 경로 안전 ────────────────────────────────────────────────────────

def _resolve(key: str) -> Path:
    """storage_key를 실제 파일 경로로 변환하되, 베이스 디렉터리 밖은 거부한다.

    '../../etc/passwd' 같은 경로 탈출(traversal)을 **키 컴포넌트 검증**으로 차단한다.
    .resolve()(파일시스템 접근)에 의존하지 않는다 — 동시 업로드로 디렉터리가
    생성되는 중 .resolve()가 간헐적으로 다른 경로를 반환해 정상 키를 오판하는
    레이스가 있었다(4-1 재검증에서 발견). 순수 문자열 검증이라 그 레이스가 없다.
    """
    if not key or key.startswith("/") or "\\" in key or "\x00" in key:
        raise StorageError(f"허용되지 않는 키: {key!r}")
    # 빈 컴포넌트("a//b")·상위(".."), 현재(".") 참조를 거부 → base 밖으로 못 나감
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise StorageError(f"허용되지 않는 키 컴포넌트: {key!r}")
    return _BASE_DIR / key


# ── 저장 / 조회 / 삭제 ───────────────────────────────────────────────

def save(key: str, data: bytes) -> str:
    """바이트를 key 위치에 저장하고 key를 그대로 반환 (DB에 넣을 storage_key)."""
    path = _resolve(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def load(key: str) -> bytes:
    path = _resolve(key)
    if not path.is_file():
        raise FileNotFoundError(key)
    return path.read_bytes()


def local_path(key: str) -> Path:
    """서빙용 실제 파일 경로 (없으면 FileNotFoundError — load와 동일 계약).

    파일 라우트가 FileResponse로 스트리밍(Range/206)할 때 쓴다 — 오디오 재생은
    iOS AVPlayer가 Range 요청을 요구하므로 bytes 통짜 응답으로는 안 된다."""
    path = _resolve(key)
    if not path.is_file():
        raise FileNotFoundError(key)
    return path


def exists(key: str) -> bool:
    try:
        return _resolve(key).is_file()
    except StorageError:
        return False


def delete(key: str) -> bool:
    """파일 삭제. 없으면 False (멱등). 삭제 cascade에서 사용."""
    path = _resolve(key)
    if path.is_file():
        path.unlink()
        return True
    return False


# ── 서명 URL (presigned URL 흉내) ────────────────────────────────────

def _sign(key: str, expires: int) -> str:
    msg = f"{key}\n{expires}".encode("utf-8")
    return hmac.new(settings.storage_url_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def signed_url(key: str, expires_in: int | None = None) -> str:
    """만료·서명이 붙은 다운로드 경로를 발급한다. api-spec의 *_url 값이 이것."""
    import time

    ttl = expires_in if expires_in is not None else settings.signed_url_expires_seconds
    expires = int(time.time()) + ttl
    return f"/api/v1/files/{key}?expires={expires}&sig={_sign(key, expires)}"


def verify(key: str, expires: int, sig: str) -> None:
    """다운로드 요청의 서명·만료를 검증한다. 실패 시 StorageError."""
    import time

    if not hmac.compare_digest(sig, _sign(key, expires)):  # 위조·변조 차단 (타이밍 안전 비교)
        raise StorageError("서명이 올바르지 않아요.")
    if expires < int(time.time()):
        raise StorageError("만료된 링크예요.")

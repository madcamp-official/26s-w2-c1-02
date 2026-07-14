"""서명 URL 기반 파일 다운로드 (작업 5).

GET /api/v1/files/{key}?expires=..&sig=.. — 서명이 맞고 안 만료됐을 때만 파일을 준다.
storage.signed_url()이 발급한 URL만 통과하므로, 인증 토큰 없이도 이 링크를 아는
클라이언트(재생 중인 오디오 태그 등)가 파일을 받을 수 있다. 링크 자체가 곧 접근권.
"""

import mimetypes

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app.core import storage
from app.core.errors import ApiError

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{key:path}")
def download(key: str, expires: int = Query(...), sig: str = Query(...)) -> Response:
    try:
        storage.verify(key, expires, sig)
        path = storage.local_path(key)
    except storage.StorageError as e:
        # 만료/서명오류 구분: 만료는 410(다시 발급받으면 됨), 그 외는 403
        code, status = ("URL_EXPIRED", 410) if "만료" in str(e) else ("INVALID_SIGNATURE", 403)
        raise ApiError(status, code, str(e))
    except FileNotFoundError:
        raise ApiError(404, "FILE_NOT_FOUND", "파일을 찾을 수 없어요.")

    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    # FileResponse가 Range(206 부분 응답)·Accept-Ranges를 처리한다 —
    # iOS AVPlayer는 오디오 스트리밍에 Range를 요구해 통짜 응답이면 -11850으로 실패.
    return FileResponse(path, media_type=content_type)

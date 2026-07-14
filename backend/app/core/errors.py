"""API 에러 공통 규격 (api-spec.md §1.1).

모든 실패 응답은 아래 형태로 나간다:
    { "error": { "code": "TEAM_NOT_FOUND", "message": "...", "details": {} } }

라우터에서는 raise ApiError(409, "USERNAME_TAKEN", "이미 사용 중인 아이디예요.")
처럼 던지면 main.py에 등록된 핸들러가 위 형태의 JSON으로 변환한다.
"""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,  # 예: 429의 Retry-After (spec §2)
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers
        super().__init__(message)


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        headers=exc.headers,
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 필드 검증 실패(422)도 spec §1.1 포맷으로 통일한다.

    FastAPI 기본 응답({"detail": [...]})을 그대로 두면 FE가 error.code를 파싱하는
    계약과 어긋나므로, VALIDATION_ERROR 코드로 감싸고 원본 상세는 details에 담는다.
    """
    errors = [
        {"field": ".".join(str(part) for part in e["loc"] if part != "body"), "reason": e["msg"]}
        for e in exc.errors()
    ]
    first = errors[0]["field"] if errors else ""
    return JSONResponse(
        status_code=422,
        content={"error": {
            "code": "VALIDATION_ERROR",
            "message": f"입력값이 올바르지 않아요: {first}",
            "details": {"errors": errors},
        }},
    )

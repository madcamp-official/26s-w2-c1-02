"""PDF → slides.json 파서 (PyMuPDF).

발표 자료 PDF에서 페이지별 텍스트를 추출해 materials.slides JSONB 형식
(db-schema §6.1: [{"page": 1, "text": "..."}]) 으로 변환한다.

팀원2의 백그라운드 파싱 잡(POST /sessions/{id}/material → 202)에서 호출:

    try:
        slides = parse_pdf_to_slides(pdf_bytes)
    except UnprocessablePdfError:
        # → status="failed", error_code="UNPROCESSABLE_PDF" (api-spec §4.2)
    except PdfParseError:
        # → 재시도 또는 실패 처리

동기(CPU-bound) 함수이므로 async 잡에서는 run_in_executor 등으로 감싼다.
"""

from pathlib import Path

import fitz  # PyMuPDF

# api-spec §1.3: 자료 PDF 최대 50페이지 (업로드 시 FE/라우터가 1차 검증)
MAX_PAGES = 50


class PdfParseError(Exception):
    """PDF 파싱 실패(손상 파일 등). 잡에서 실패/재시도 처리."""


class UnprocessablePdfError(PdfParseError):
    """텍스트 추출 불가(스캔본·이미지 PDF·암호화). → 422 UNPROCESSABLE_PDF."""


def parse_pdf_to_slides(pdf: bytes | str | Path) -> list[dict]:
    """PDF에서 페이지별 텍스트를 추출한다.

    Args:
        pdf: PDF 파일의 bytes 또는 경로.

    Returns:
        [{"page": 1, "text": "..."}] — page는 1부터, 텍스트 없는 페이지는
        text=""로 포함해 page 번호가 실제 PDF와 항상 일치하게 유지한다
        (질문 evidence.slides가 이 번호를 참조, db-schema §6.3).

    Raises:
        UnprocessablePdfError: 전 페이지에서 텍스트를 못 얻은 경우(스캔본),
            암호화된 PDF, 페이지 수 초과.
        PdfParseError: 파일이 PDF가 아니거나 손상된 경우.
    """
    try:
        if isinstance(pdf, bytes):
            doc = fitz.open(stream=pdf, filetype="pdf")
        else:
            doc = fitz.open(str(pdf))
    except Exception as e:
        raise PdfParseError(f"PDF를 열 수 없음: {e}") from e

    try:
        if doc.needs_pass:
            raise UnprocessablePdfError("암호화된 PDF")
        if doc.page_count > MAX_PAGES:
            raise UnprocessablePdfError(f"페이지 수 초과: {doc.page_count} > {MAX_PAGES}")

        slides = [
            {"page": i + 1, "text": _clean_text(page.get_text("text"))}
            for i, page in enumerate(doc)
        ]
    finally:
        doc.close()

    if not slides or all(not s["text"] for s in slides):
        raise UnprocessablePdfError("텍스트 레이어 없음(스캔본 추정)")
    return slides


def _clean_text(raw: str) -> str:
    """줄 단위 공백 정리 + 연속 빈 줄 제거. 줄 순서는 보존."""
    lines = [line.strip() for line in raw.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip()

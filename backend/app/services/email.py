"""인증코드 메일 발송 — mock(로그 출력) | smtp(Gmail 실발송).

EMAIL_PROVIDER 설정으로 전환한다 (llm factory의 LLM_PROVIDER 관례와 동일):
- mock(기본): 발송 대신 서버 로그에 코드를 출력 — 개발 중엔 tmux 로그에서 코드를
  읽어 인증한다. SMTP 계정 없이 전체 개발·테스트 가능.
- smtp: Gmail SMTP(STARTTLS, 앱 비밀번호)로 실발송. 배포 VM에서만 켠다 (plan §7-1).

표준 라이브러리 smtplib만 사용 — requirements 추가 없음.

호출부는 FastAPI BackgroundTasks라 예외가 응답에 영향을 주지 않는다 —
실패는 EmailSendError로 감싸 로그만 남기고, 유저는 "재발송"으로 복구한다.

    background_tasks.add_task(send_verification_email, user.email, code)
"""

import logging
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger("rehearsal.email")

_SMTP_TIMEOUT = 10.0  # 접속·발송 상한(초). 배경 작업이 SMTP 장애에 매달리지 않게


class EmailSendError(Exception):
    """메일 발송 실패(접속·인증·전송 오류). 배경 작업에서 로그로만 소비된다."""


def send_verification_email(to_email: str, code: str) -> None:
    """인증코드 메일 발송. mock 모드는 로그로 대체. 실패 시 EmailSendError."""
    provider = settings.email_provider.lower()
    if provider == "mock":
        logger.info("[MOCK 메일] to=%s code=%s", to_email, code)
        return
    if provider != "smtp":
        raise EmailSendError(f"알 수 없는 EMAIL_PROVIDER: {settings.email_provider}")

    msg = MIMEText(
        f"Rehearsal.io 인증코드: {code}\n10분 안에 입력해주세요.", _charset="utf-8"
    )
    msg["Subject"] = "[Rehearsal.io] 이메일 인증코드"
    msg["From"] = settings.smtp_user
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT) as smtp:
            smtp.starttls()  # Gmail 587은 STARTTLS 필수 — 평문 구간에 인증정보 안 태움
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # OSError: DNS 실패·접속 거부·타임아웃. 코드 평문은 로그에 남기지 않는다.
        logger.error("인증 메일 발송 실패 to=%s: %s", to_email, e)
        raise EmailSendError(f"인증 메일 발송 실패: {e}") from e

    logger.info("인증 메일 발송 완료 to=%s", to_email)

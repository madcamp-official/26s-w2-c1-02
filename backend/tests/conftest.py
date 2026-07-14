"""테스트 공통 설정.

테스트는 결정론적 mock LLM을 전제한다(스냅샷·꼬리질문 생성 여부 단언).
개발용 .env가 LLM_PROVIDER=gemini여도 테스트가 실 API를 때리지 않도록
환경변수를 기본 mock으로 고정한다 — 셸에서 LLM_PROVIDER=gemini를 명시하면
그쪽이 우선이라 라이브 검수도 가능하다. (env var > .env, pydantic-settings)

app 모듈 임포트 전에 실행돼야 하므로 여기(conftest 최상단)에서 설정한다.
"""

import os

os.environ.setdefault("LLM_PROVIDER", "mock")

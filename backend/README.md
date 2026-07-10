# Rehearsal.io — Backend (FastAPI)

LLM 기반 프레젠테이션 질의응답 생성/분석 서비스의 API 서버.

## 실행 방법

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # 필요 시 값 수정

uvicorn app.main:app --reload --port 8000
```

- API 문서(Swagger): http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health

## 구조

```
app/
├── main.py            # FastAPI 엔트리포인트 + CORS
├── core/config.py     # 환경설정(.env)
├── schemas/           # Pydantic 모델 (Flutter 모델과 1:1)
├── db/store.py        # 인메모리 저장소 (추후 실제 DB로 교체)
├── services/llm/      # LLM 제공자 추상화 (mock → Gemini 교체 예정)
└── api/routes/        # auth / teams / speeches 라우터
```

## 현재 상태 (스캐폴드)

- 인증: Mock (실제 OAuth/이메일 로그인 추후 연동)
- 저장소: 인메모리 (재시작 시 초기화, Figma 시드 데이터 포함)
- LLM: Mock 제공자 (질문 더미 생성). `LLM_PROVIDER=gemini` 는 미구현.

## 주요 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| POST | `/auth/login` | Mock 로그인 |
| POST | `/auth/login/{provider}` | 소셜 로그인(mock) |
| GET | `/teams` | 팀 목록 |
| POST | `/teams` | 팀 생성 |
| GET | `/teams/{id}` | 팀 상세 |
| DELETE | `/teams/{id}` | 팀 나가기 |
| GET | `/teams/{id}/speeches` | 스피치 목록 |
| POST | `/teams/{id}/speeches` | 스피치(발표) 생성 |
| GET | `/speeches/{id}` | 스피치 상세 |
| POST | `/speeches/{id}/qna` | 질의응답 질문 생성(LLM) |

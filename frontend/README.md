# Rehearsal.io — Frontend (Flutter)

크로스플랫폼(Android / iOS / Web) 프레젠테이션 리허설 & 질의응답 앱.

## 실행 방법

```bash
cd frontend
flutter pub get

# 웹
flutter run -d chrome

# 모바일 (에뮬레이터/기기 연결 후)
flutter run
```

기본은 **Mock 모드**라 백엔드 없이도 전체 플로우가 동작한다.
실제 FastAPI 백엔드에 붙이려면:

```bash
flutter run -d chrome \
  --dart-define=USE_MOCK=false \
  --dart-define=API_BASE_URL=http://localhost:8000
```

## 화면 ↔ 라우트 (Figma 기준)

| 화면 | 라우트 | 파일 |
|---|---|---|
| 로그인 | `/login` | `features/auth/login_page.dart` |
| 메인페이지 | `/` | `features/home/home_page.dart` |
| 마이페이지 | `/me` | `features/profile/my_page.dart` |
| 새 프레젠테이션 만들기 | `/teams/new` | `features/team/create_team_page.dart` |
| 프레젠테이션 팀 화면 | `/teams/:teamId` | `features/team/team_detail_page.dart` |
| 발표 만들기 | `/teams/:teamId/speeches/new` | `features/speech/create_speech_page.dart` |
| 발표중 / 질의응답 여부 | `/speeches/:speechId/present` | `features/speech/presenting_page.dart` |
| 질의응답 | `/speeches/:speechId/qna` | `features/speech/qna_page.dart` |

## 구조

```
lib/
├── main.dart / app.dart      # 엔트리포인트 + Provider/라우터 주입
├── core/
│   ├── theme/                # 색상/테마 (Figma 팔레트)
│   ├── router/               # go_router (웹 URL 딥링크 지원)
│   ├── config/env.dart       # USE_MOCK / API_BASE_URL
│   └── network/api_client.dart
├── data/
│   ├── models/               # User/Team/Speech/Qna + enum
│   └── repositories/         # Mock*Repository (→ 추후 Api*Repository로 교체)
├── state/                    # ChangeNotifier 컨트롤러 (provider)
└── features/                 # 화면별 위젯
```

## 아키텍처 원칙

- **UI ↔ 데이터 분리**: 화면은 `state/*Controller`만 알고, 컨트롤러는 `repositories` 인터페이스만 안다.
  Mock → 실제 API 전환 시 `app.dart`의 repository 주입부만 교체하면 된다.
- **크로스플랫폼**: 모바일 우선 디자인을 `ResponsivePage`로 감싸 웹/태블릿에서 가운데 정렬.

## 스캐폴드 단계에서 비워둔 부분 (TODO)

- 인증: 지금은 Mock 더미 로그인. 실제 카카오/네이버/구글 OAuth 연동 예정.
- 발표 녹음: `발표 시작하기` 시 타이머만 동작. 실제 오디오 녹음/STT 미연동.
- PDF: 파일 선택(파일명 저장)만. 슬라이드 렌더링/텍스트 추출 미구현.
- 질의응답 캐릭터 이미지(테토/에겐/꼰대교수) assets 미포함(플레이스홀더).
- LLM 질문 생성: 백엔드 Mock 제공자. Gemini 등 실제 연동 예정.

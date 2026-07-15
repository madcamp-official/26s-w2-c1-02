#!/usr/bin/env bash
# 배포용 Android APK 빌드 — 프로덕션 서버 주소를 박아 넣는다.
#
# 사용법(본인 개발 머신, Flutter/안드로이드 SDK 설치된 곳에서):
#   ./build-apk.sh
#
# 결과물: build/app/outputs/flutter-apk/app-release.apk
#
# 업데이트를 낼 때는 먼저 pubspec.yaml 의 version 을 올린다(+뒤 숫자 반드시 증가):
#   version: 0.1.0+1  →  0.1.1+2
set -euo pipefail

cd "$(dirname "$0")"

flutter build apk --release \
  --dart-define=USE_MOCK=false \
  --dart-define=API_BASE_URL=https://malggori.madcamp-kaist.org

echo
echo "✅ 빌드 완료: build/app/outputs/flutter-apk/app-release.apk"
echo "   이 파일을 테스터에게 직접 전달하면 된다(카톡/드라이브 등)."

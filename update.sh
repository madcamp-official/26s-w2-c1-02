#!/usr/bin/env bash
# Rehearsal.io VM 업데이트 스크립트 — git pull 후 바뀐 부분만 반영한다.
#
# 사용법 (VM에서):
#   ./update.sh          # main 최신화 → 백엔드/프론트 중 바뀐 쪽만 반영
#   ./update.sh --back   # 백엔드 강제 재시작 (pull 변경 없어도)
#   ./update.sh --front  # 프론트 강제 빌드·배포 (pull 변경 없어도)
#
# 반영 방식:
#   백엔드  = pip install + systemd 서비스 재시작 (rehearsal-backend, 포트 8000)
#             로그 보기: journalctl -u rehearsal-backend -f
#   프론트  = flutter build web → /var/www/rehearsal 로 동기화 (nginx가 서빙)
#   .env    = 절대 건드리지 않음 (SMTP·JWT 등 시크릿은 수동 관리)
#
# ⚠️ backend/migrations/ 에 새 SQL이 들어오면 자동 적용하지 않고 경고만 한다 —
#    migrations/README.md 절차대로 (필요 시 데이터 SQL 먼저 → 코드 반영) 직접 실행할 것.
#    (예: 이메일 인증 배포 때 §7-2 일괄 인증 SQL을 서버 재시작 전에 실행해야 했음)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$REPO/backend"
WEB_ROOT="/var/www/rehearsal"
FLUTTER=/opt/flutter/bin/flutter
HEALTH_URL=http://127.0.0.1:8000/health
# 배포 중인 웹 빌드와 동일한 정의 (main.dart.js에서 역추적해 고정)
DART_DEFINES=(--dart-define=USE_MOCK=false
              --dart-define=API_BASE_URL=https://malggori.madcamp-kaist.org)

FORCE_BACK=false
FORCE_FRONT=false
for arg in "$@"; do
  case "$arg" in
    --back)  FORCE_BACK=true ;;
    --front) FORCE_FRONT=true ;;
    *) echo "알 수 없는 옵션: $arg (사용법은 파일 상단 주석)"; exit 1 ;;
  esac
done

cd "$REPO"

# ── 1) 코드 최신화 ────────────────────────────────────────────────────
OLD=$(git rev-parse HEAD)
echo "▶ git pull (현재: $(git log -1 --oneline))"
git pull --ff-only origin main
NEW=$(git rev-parse HEAD)
CHANGED=$(git diff --name-only "$OLD" "$NEW" || true)
[ "$OLD" = "$NEW" ] && echo "  변경 없음" || echo "  변경 파일 $(echo "$CHANGED" | wc -l)개 → $(git log -1 --oneline)"

# ── 2) 마이그레이션 경고 (자동 적용 안 함) ────────────────────────────
if echo "$CHANGED" | grep -q '^backend/migrations/'; then
  echo ""
  echo "⚠️⚠️  새 마이그레이션 감지 — 서버 반영 전에 직접 적용해야 할 수 있음:"
  echo "$CHANGED" | grep '^backend/migrations/' | sed 's/^/     /'
  echo "     backend/migrations/README.md 절차 확인 후 계속하세요."
  read -rp "     계속할까요? [y/N] " ok
  [ "${ok,,}" = "y" ] || { echo "중단됨"; exit 1; }
fi

# ── 3) 백엔드 ────────────────────────────────────────────────────────
if $FORCE_BACK || echo "$CHANGED" | grep -q '^backend/'; then
  echo "▶ 백엔드 반영"
  "$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements.txt"
  systemctl restart rehearsal-backend
  echo -n "  health 대기"
  for _ in $(seq 1 30); do
    if curl -sf -o /dev/null --max-time 2 "$HEALTH_URL"; then
      echo " → OK ($(curl -s "$HEALTH_URL"))"
      break
    fi
    echo -n "."
    sleep 1
  done
  curl -sf -o /dev/null --max-time 2 "$HEALTH_URL" \
    || { echo " → ❌ 서버가 안 뜸! journalctl -u rehearsal-backend -n 50 으로 로그 확인"; exit 1; }
else
  echo "▶ 백엔드 변경 없음 — 재시작 생략 (강제: --back)"
fi

# ── 4) 프론트엔드 ────────────────────────────────────────────────────
if $FORCE_FRONT || echo "$CHANGED" | grep -q '^frontend/'; then
  echo "▶ 프론트 빌드 (수 분 소요)"
  (cd "$REPO/frontend" && "$FLUTTER" build web --release "${DART_DEFINES[@]}")
  if command -v rsync >/dev/null; then
    rsync -a --delete "$REPO/frontend/build/web/" "$WEB_ROOT/"
  else
    rm -rf "$WEB_ROOT"/* && cp -r "$REPO/frontend/build/web/." "$WEB_ROOT/"
  fi
  # Cloudflare가 .js를 4시간 엣지 캐시 + 브라우저 max-age 강제하므로
  # 커밋 해시를 쿼리스트링으로 붙여 배포마다 URL을 바꾼다 (index.html은 no-cache라 항상 신선).
  BUILD_V=$(git rev-parse --short HEAD)
  sed -i "s|src=\"flutter_bootstrap\.js\"|src=\"flutter_bootstrap.js?v=$BUILD_V\"|" "$WEB_ROOT/index.html"
  sed -i "s|\"main\.dart\.js\"|\"main.dart.js?v=$BUILD_V\"|g" "$WEB_ROOT/flutter_bootstrap.js"
  echo "  → $WEB_ROOT 배포 완료 (캐시버스트 v=$BUILD_V, nginx는 정적 파일이라 재시작 불필요)"
else
  echo "▶ 프론트 변경 없음 — 빌드 생략 (강제: --front)"
fi

echo ""
echo "✅ 업데이트 완료 — https://malggori.madcamp-kaist.org 에서 확인"

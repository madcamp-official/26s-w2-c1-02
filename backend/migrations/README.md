# DB 마이그레이션

수동 적용(numbered SQL). 전용 러너(Alembic 등)는 없다 — 번호 순서대로 `psql`로 직접 적용한다.

```
psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/<파일>.sql
```

각 마이그레이션은 **각 DB(로컬 dev · 공용 dev · 테스트 · 배포)마다 한 번씩** 적용해야 한다.
git push는 이 `.sql` 파일을 배포할 뿐 DB에 실행하지 않는다 — 적용은 DB 접근 권한자가 별도로 실행한다.

## 적용 현황

| # | 파일 | 내용 | 상태 |
|---|------|------|------|
| 001 | `001_init.sql` | 초기 스키마 (db-schema.md v1.0) | 적용됨 |
| 002 | `002_recording_chunks.sql` | 실시간 녹음 청크 파이프라인: `recording_chunks` 테이블 + `recordings.total_chunks` 컬럼 (api-spec §4.3.1) | ⚠️ **미적용 — `recording` 브랜치 병합과 함께 적용 필요** |
| 003 | `003_password_resets.sql` | 비밀번호 재설정: `password_resets` 테이블 (아이디·비밀번호 찾기, api-spec §2) | ⚠️ **미적용 — 이 브랜치 병합과 함께 각 DB에 적용 필요** (역방향 무해: 새 테이블 추가뿐, 구 코드 무영향) |

## ⚠️ 002 — 반드시 읽고 적용 (병합 담당·DB 담당 필독)

> **한 줄 요약: `recording` 브랜치 코드가 도는 모든 DB에 002가 적용돼 있어야 한다.
> "신(新) 코드 라이브 + 002 미적용" 상태가 단 한순간도 없게 한다.**

### 왜 반드시 필요한가 (정방향 결합)

`recording` 브랜치의 SQLAlchemy 모델이 `recordings.total_chunks` 컬럼과 `recording_chunks`
테이블을 매핑한다. 002가 없는 DB에서 이 코드를 돌리면 **새 엔드포인트뿐 아니라 기존
`POST /recording`(일괄 업로드)의 단순 조회까지** `column "total_chunks" does not exist`로
**500 에러**가 난다. → 코드와 002는 **한 세트**다.

### 먼저 적용해도 안전하다 (역방향 무해)

002는 **새 테이블 + nullable 컬럼 추가뿐**이다. 백필·잠금·기존 데이터 변경이 없고,
**구(舊) 코드는 `total_chunks`를 SELECT하지 않으므로** 002가 적용된 DB에서도 아무 영향 없이
그대로 돈다. 기존 녹음 행은 `total_chunks = NULL`(= 일괄 업로드 의미)로 유지된다.
→ 002는 **병합 전에 미리 적용해도 되고, 그게 더 안전하다.**

### 권장 순서

1. **DB 담당**: 공용 DB(dev·테스트·배포)에 002를 **먼저** 적용한다(구 코드 무영향).
   ```
   psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/002_recording_chunks.sql
   ```
2. 적용 확인:
   ```
   psql ... -c "\d recording_chunks"          # 테이블 존재
   psql ... -c "\d recordings" | grep total_chunks   # 컬럼 존재
   ```
3. **테스트**(002 적용된 DB에서): 배치 경로 무회귀 + 신규 파이프라인 검증
   ```
   cd backend && .venv/bin/python -m pytest tests/test_recordings.py tests/test_recording_chunks.py -v
   ```
4. 위가 초록이면 `recording` → `main` 병합.

> 부득이 **병합을 먼저** 해야 하면(예: DB 담당이 main에서만 마이그레이션을 돌리는 절차),
> 병합 직후 **즉시** 002를 적용하고, 신 코드가 그 DB로 서비스되기 **전에** 위 테스트를 돌린다.
> 초록이 아니면 병합을 되돌린다(clean 8-commit 범위라 revert 용이).

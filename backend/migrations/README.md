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
| 002 | `002_recording_chunks.sql` | 실시간 녹음 청크 파이프라인: `recording_chunks` 테이블 + `recordings.total_chunks` 컬럼 (api-spec §4.3.1) | ⚠️ **`recording` 브랜치 병합 후 적용 필요** |

## 002 적용 안내 (병합 후)

- **필수**: SQLAlchemy 모델이 `recording_chunks`·`recordings.total_chunks`를 매핑하므로,
  미적용 DB에서는 기존 `POST /recording` 조회까지 `column does not exist`로 실패한다.
  즉 코드 병합과 002 적용은 **함께** 이뤄져야 한다.
- **안전**: 새 테이블 + nullable 컬럼 추가뿐 — 백필·잠금·기존 데이터 변경 없음.
  기존 녹음 행은 `total_chunks = NULL`(일괄 업로드 의미)로 그대로 유지된다.

```
psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/002_recording_chunks.sql
```

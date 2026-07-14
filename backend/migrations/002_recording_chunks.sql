-- Rehearsal.io — 002: 실시간 녹음 청크 전송 파이프라인 (api-spec §4.3.1)
-- 적용: psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f 002_recording_chunks.sql
-- 선행: 001_init.sql (async_status·sessions·recordings·set_updated_at() 재사용)

SET client_encoding = 'UTF8';

-- ============================================================
-- 실시간 녹음 청크 (api-spec §4.3.1 · §0.8 살릴 때 챙길 4가지)
-- ============================================================
--
-- 발표 중 순차 업로드되는 60초+4초 겹침 청크. (session_id, seq)를 PK로 두어
-- 같은 seq 재전송이 upsert로 덮어써지게 한다(멱등성 ①). 청크별 STT 결과는
-- seq-로컬 타임스탬프 그대로 segments(jsonb)에 쌓고, /recording/complete에서
-- 오프셋 보정 + 앞겹침 절단으로 병합한다(④).
--
-- 겹침 방향 주의(③): FE 청크는 겹침이 **앞**에 붙는다(청크 i = [60i−4, 60(i+1))).
-- offset_seconds/overlap_seconds를 그대로 저장해 병합 시 절단창을 이 값으로
-- 계산한다 — stt.py의 뒤겹침 하드코딩 산식(60·4)을 재사용하지 않는다.

CREATE TABLE recording_chunks (
    session_id       text NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq              integer NOT NULL CHECK (seq >= 0),            -- 0-base 순번
    offset_seconds   real NOT NULL CHECK (offset_seconds >= 0),    -- 녹음 시작 기준 시작 오프셋(겹침 포함)
    overlap_seconds  real NOT NULL DEFAULT 0 CHECK (overlap_seconds >= 0),  -- 앞 청크와의 겹침(첫 청크 0)
    duration_seconds real NOT NULL CHECK (duration_seconds > 0),
    storage_key      text NOT NULL,
    status           async_status NOT NULL DEFAULT 'queued',       -- 청크별 STT 상태
    segments         jsonb,                             -- 청크-로컬 [{"start":..,"end":..,"text":..}]
    error_code       text,
    error_message    text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);

CREATE TRIGGER recording_chunks_updated_at BEFORE UPDATE ON recording_chunks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- /recording/complete가 보고한 기대 청크 수. 누락 seq 검출(0..total_chunks−1)에 쓴다(②).
-- 일괄/파일 업로드(§4.3) 경로는 NULL로 남는다.
ALTER TABLE recordings ADD COLUMN total_chunks integer CHECK (total_chunks >= 0);

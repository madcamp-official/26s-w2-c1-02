-- Rehearsal.io — 003: 비밀번호 재설정 (아이디·비밀번호 찾기, api-spec §2)
-- 적용: psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f 003_password_resets.sql
-- 선행: 001_init.sql (users 테이블 재사용)

SET client_encoding = 'UTF8';

-- ============================================================
-- 비밀번호 재설정 코드 (api-spec §2 · 아이디/비밀번호 찾기)
-- ============================================================
--
-- email_verifications와 구조·규율이 동일하지만 **테이블을 분리한다**: 한쪽은
-- "이메일 인증(email_verified_at 설정)", 한쪽은 "비밀번호 교체"라 목적이 다르다.
-- 한 테이블을 공유하면 인증용 코드로 비밀번호를 바꾸거나 그 반대가 가능해져
-- 목적 혼동(confused deputy)이 생긴다. 코드 평문은 메일로만 나가고 DB엔 bcrypt 해시만.
--
-- 검증(대조·만료·시도 제한)은 POST /auth/password/reset이 수행한다.
CREATE TABLE password_resets (
    id            text PRIMARY KEY,                  -- 'pwr_'
    user_id       text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash     text NOT NULL,                     -- 재설정 코드 bcrypt 해시
    expires_at    timestamptz NOT NULL,
    consumed_at   timestamptz,
    attempt_count smallint NOT NULL DEFAULT 0,       -- 브루트포스 방지 (email_verifications와 동일)
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_resets_user_idx ON password_resets (user_id) WHERE consumed_at IS NULL;

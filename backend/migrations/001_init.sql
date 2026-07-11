-- Rehearsal.io — 초기 스키마 (docs/db-schema.md v1.0)
-- 적용: psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f 001_init.sql
-- 순서: ENUM(§2) → 유저·인증(§3.1) → 팀(§3.2) → 세션(§3.3) → 1:1 자식(§3.4)
--       → 질문·답변(§3.5) → 리포트(§3.6) → updated_at 트리거(§3.7)

SET client_encoding = 'UTF8';

-- ============================================================
-- §2. ENUM 정의 (12종)
-- ============================================================

CREATE TYPE client_platform    AS ENUM ('web', 'ios', 'android');
CREATE TYPE social_provider    AS ENUM ('google', 'kakao', 'naver');
CREATE TYPE invite_status      AS ENUM ('pending', 'accepted', 'declined', 'canceled');
CREATE TYPE session_status     AS ENUM ('draft', 'recording_in_progress', 'transcribing',
                                        'generating_questions', 'qna', 'completed', 'failed');
CREATE TYPE session_mode       AS ENUM ('realtime', 'upload');
CREATE TYPE questioner_persona AS ENUM ('egen', 'teto', 'kkondae', 'mungcheong', 'jammin');
CREATE TYPE question_strategy  AS ENUM ('detail_probe', 'big_picture', 'basic_concept',
                                        'numeric_verification');
CREATE TYPE async_status       AS ENUM ('queued', 'processing', 'ready', 'failed');
CREATE TYPE answer_status      AS ENUM ('processing', 'ready', 'failed');  -- 'pending'은 row 부재로 표현(§5)
CREATE TYPE answer_kind        AS ENUM ('answered', 'passed');
CREATE TYPE follow_up_status   AS ENUM ('pending', 'generated', 'none');
CREATE TYPE ended_reason       AS ENUM ('user_end', 'count_reached', 'timeout');

-- ============================================================
-- §3.1 유저 · 인증
-- ============================================================

CREATE TABLE users (
    id                text PRIMARY KEY,              -- 'usr_' || base62(20)
    username          text,                          -- 로그인 아이디 (소셜 전용 가입자는 NULL)
    password_hash     text,                          -- bcrypt/argon2 (소셜 전용은 NULL)
    name              text,                          -- 닉네임 (탈퇴 시 NULL → '탈퇴한 사용자' 표기)
    email             text,                          -- 탈퇴 시 NULL (재가입 허용)
    email_verified_at timestamptz,
    deleted_at        timestamptz,                   -- D4: 익명화 시각
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (deleted_at IS NOT NULL OR name IS NOT NULL)   -- 활성 유저는 name 필수
);
-- 대소문자 무시 유니크 (NULL 다중 허용 → 탈퇴자와 충돌 없음)
CREATE UNIQUE INDEX users_username_key ON users (lower(username)) WHERE username IS NOT NULL;
CREATE UNIQUE INDEX users_email_key    ON users (lower(email))    WHERE email    IS NOT NULL;

CREATE TABLE social_accounts (
    id               text PRIMARY KEY,               -- 'soc_'
    user_id          text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider         social_provider NOT NULL,
    provider_user_id text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)              -- 같은 소셜 계정 재연결 금지
);
CREATE INDEX social_accounts_user_idx ON social_accounts (user_id);

CREATE TABLE refresh_tokens (
    id         text PRIMARY KEY,                     -- 'rt_'
    user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,                 -- SHA-256(token) — 원문 저장 금지
    platform   client_platform NOT NULL,             -- A1/B: web=쿠키, native=본문
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,                          -- 로그아웃/회전 시
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (user_id) WHERE revoked_at IS NULL;

CREATE TABLE email_verifications (
    id            text PRIMARY KEY,                  -- 'emv_'
    user_id       text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash     text NOT NULL,                     -- 인증코드 해시
    expires_at    timestamptz NOT NULL,
    consumed_at   timestamptz,
    attempt_count smallint NOT NULL DEFAULT 0,       -- 브루트포스 방지
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX email_verifications_user_idx ON email_verifications (user_id) WHERE consumed_at IS NULL;

-- ============================================================
-- §3.2 팀 · 멤버십 · 초대
-- ============================================================

CREATE TABLE teams (
    id         text PRIMARY KEY,                     -- 'team_'
    name       text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 20),  -- 중복 허용(유니크 없음)
    leader_id  text NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE team_members (
    team_id   text NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id   text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at timestamptz NOT NULL DEFAULT now(),    -- D5: 승계 순서 기준
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX team_members_user_idx ON team_members (user_id);

-- 무결성: 팀장은 반드시 그 팀의 멤버 (팀 생성/승계 트랜잭션 커밋 시점에 검사)
ALTER TABLE teams
    ADD CONSTRAINT teams_leader_is_member_fk
    FOREIGN KEY (id, leader_id) REFERENCES team_members (team_id, user_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE team_email_invites (
    id           text PRIMARY KEY,                   -- 'inv_'
    team_id      text NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    email        text NOT NULL,
    token        text NOT NULL UNIQUE,               -- 메일 속 수락 링크용 (§3.1 /invites/{token})
    invited_by   text REFERENCES users(id) ON DELETE SET NULL,
    status       invite_status NOT NULL DEFAULT 'pending',
    expires_at   timestamptz NOT NULL,
    responded_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
-- 같은 팀·같은 이메일 pending 중복 금지 (재초대는 기존 건 취소 후)
CREATE UNIQUE INDEX team_email_invites_pending_key
    ON team_email_invites (team_id, lower(email)) WHERE status = 'pending';

CREATE TABLE team_invite_links (
    id         text PRIMARY KEY,                     -- 'lnk_'
    team_id    text NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    token      text NOT NULL UNIQUE,
    created_by text REFERENCES users(id) ON DELETE SET NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,                          -- 회전/비활성화 시 (G: 이전 링크 즉시 무효)
    created_at timestamptz NOT NULL DEFAULT now()
);
-- api-spec §3.1: 팀당 활성 링크 1개 (회전 = 같은 트랜잭션에서 revoke + insert)
CREATE UNIQUE INDEX team_invite_links_active_key
    ON team_invite_links (team_id) WHERE revoked_at IS NULL;

-- ============================================================
-- §3.3 세션 (발표 1회)
-- ============================================================

CREATE TABLE sessions (
    id                  text PRIMARY KEY,            -- 'ses_'
    team_id             text NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    owner_id            text NOT NULL REFERENCES users(id) ON DELETE RESTRICT,  -- F: 발표자(권한·성장리포트 축)
    name                text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 50),
    status              session_status NOT NULL DEFAULT 'draft',
    mode                session_mode NOT NULL DEFAULT 'realtime',
    personas            questioner_persona[] NOT NULL CHECK (cardinality(personas) >= 1),  -- 중복선택(≥1)
    question_count      smallint NOT NULL CHECK (question_count BETWEEN 1 AND 20),  -- 1차 질문 수만(§4.1)
    time_limit_minutes  smallint NOT NULL CHECK (time_limit_minutes BETWEEN 1 AND 120),
    current_question_id text,                        -- FK는 §3.5에서 추가(순환 참조)
    qna_ended_reason    ended_reason,                -- A12: user_end > count_reached > timeout
    started_at          timestamptz,                 -- A9: 클라이언트 권위
    ended_at            timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_team_idx  ON sessions (team_id, created_at DESC);   -- 팀 페이지 목록
CREATE INDEX sessions_owner_idx ON sessions (owner_id, created_at DESC);  -- E: 성장 리포트(유저 스코프)

-- ============================================================
-- §3.4 세션 1:1 자식 — 자료 · 녹음 · 전사
-- (session_id를 그대로 PK로 사용, 파일 본문은 스토리지 — DB에는 storage_key만)
-- ============================================================

CREATE TABLE materials (
    session_id      text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status          async_status NOT NULL DEFAULT 'queued',
    progress        real NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    file_name       text NOT NULL,
    file_size_bytes integer NOT NULL CHECK (file_size_bytes <= 20 * 1024 * 1024),  -- §1.3: 20MB
    page_count      smallint CHECK (page_count <= 50),                             -- §1.3: 50p
    storage_key     text NOT NULL,
    slides          jsonb,                           -- ready 시: [{"page":1,"text":"..."}] (§6.1)
    error_code      text,                            -- 예: UNPROCESSABLE_PDF (스캔본)
    error_message   text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE recordings (
    session_id       text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status           async_status NOT NULL DEFAULT 'processing',  -- 업로드 완료 → ready
    file_name        text NOT NULL,
    file_size_bytes  integer NOT NULL CHECK (file_size_bytes <= 200 * 1024 * 1024),  -- §1.3: 200MB
    mime_type        text NOT NULL,                  -- audio/mpeg | audio/wav | audio/mp4
    duration_seconds integer NOT NULL CHECK (duration_seconds <= 3600),              -- §1.3: 60분
    storage_key      text NOT NULL,
    started_at       timestamptz,                    -- 클라이언트 보고값(A9)
    ended_at         timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE transcripts (
    session_id    text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status        async_status NOT NULL DEFAULT 'queued',
    segments      jsonb,                             -- [{"start":12.0,"end":15.2,"text":"..."}] (§6.2)
    error_code    text,
    error_message text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- §3.5 질문 · 답변
-- ============================================================

CREATE TABLE questions (
    id                text PRIMARY KEY,              -- 'q_'
    session_id        text NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    parent_id         text REFERENCES questions(id) ON DELETE CASCADE,  -- 꼬리질문의 부모
    follow_up_depth   smallint NOT NULL DEFAULT 0 CHECK (follow_up_depth IN (0, 1)),  -- A11: 깊이≤1
    order_index       smallint NOT NULL,             -- 1차 질문 순번(1..N), 꼬리는 부모와 동일
    persona           questioner_persona NOT NULL,
    strategy          question_strategy NOT NULL,    -- C: 리포트 type_scores 집계 축
    text              text NOT NULL,
    evidence          jsonb NOT NULL DEFAULT '{"slides": [], "transcript_refs": []}',  -- §6.3
    tts_status        async_status NOT NULL DEFAULT 'queued',   -- A6: VoxCPM2 큐
    tts_storage_key   text,
    tts_error_code    text,
    tts_error_message text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((parent_id IS NULL) = (follow_up_depth = 0))          -- 꼬리 ⟺ 부모 존재
);
-- 재생/표시 순서: ORDER BY order_index, follow_up_depth (꼬리는 부모 바로 뒤)
CREATE INDEX questions_session_idx ON questions (session_id, order_index, follow_up_depth);
-- 1차 질문 순번 유니크
CREATE UNIQUE INDEX questions_primary_order_key ON questions (session_id, order_index)
    WHERE parent_id IS NULL;
-- 질문당 꼬리질문 1개 (A11)
CREATE UNIQUE INDEX questions_one_follow_up_key ON questions (parent_id)
    WHERE parent_id IS NOT NULL;

-- sessions.current_question_id 순환 FK (질문 삭제 시 NULL)
ALTER TABLE sessions
    ADD CONSTRAINT sessions_current_question_fk
    FOREIGN KEY (current_question_id) REFERENCES questions(id)
    ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE answers (
    question_id       text PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,  -- 질문당 답변 1개
    kind              answer_kind NOT NULL,          -- answered | passed(스킵, 로그 표시용)
    status            answer_status NOT NULL DEFAULT 'processing',  -- row 생성 = 제출 시점(§5 매핑)
    audio_storage_key text,                          -- passed면 NULL
    duration_seconds  integer,
    text              text,                          -- raw STT 원문(v0.3 — 정제 없음)
    follow_up_status  follow_up_status NOT NULL DEFAULT 'pending',  -- A: 꼬리질문 판정 상태
    error_code        text,                          -- STT_FAILED 등 → 재제출로 재시도
    error_message     text,
    submitted_at      timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- 패스는 오디오 없음 + 꼬리질문 생략(§4.4)
    CHECK (kind <> 'passed' OR (audio_storage_key IS NULL AND follow_up_status = 'none'))
);

-- ============================================================
-- §3.6 리포트
-- ============================================================

CREATE TABLE reports (
    session_id       text PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status           async_status NOT NULL DEFAULT 'queued',   -- A7: qna/end 시 자동 생성
    words_per_minute real,                           -- v0.3: 원문 기준(필러 포함 — 2026-07-11 확정)
    filler_words     jsonb,                          -- [{"word":"음","count":9}] (§6.4)
    insight          text,
    error_code       text,
    error_message    text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()        -- report/generate 재생성 시 갱신
);
-- time_limit_seconds/actual_seconds/over_time은 저장하지 않음 — sessions·recordings에서 파생(§5)

-- D3: 전략별 점수는 정규화 — 성장 리포트가 SQL 한 방(§8.1)
CREATE TABLE report_type_scores (
    report_session_id text NOT NULL REFERENCES reports(session_id) ON DELETE CASCADE,
    strategy          question_strategy NOT NULL,
    score             real NOT NULL CHECK (score BETWEEN 0 AND 1),
    PRIMARY KEY (report_session_id, strategy)
);

-- ============================================================
-- §3.7 updated_at 자동 갱신 (공통 트리거)
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['users','teams','sessions','materials','transcripts','answers','reports']
    LOOP
        EXECUTE format('CREATE TRIGGER %I_updated_at BEFORE UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
    END LOOP;
END $$;

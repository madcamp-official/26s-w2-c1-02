/// api-spec.md v0.3 §6.1 Enums — 서버 계약과 1:1.
/// 값 이름은 wire 포맷(snake/lower)과 동일하게 유지한다.
library;

/// 질문자 페르소나 5종.
enum QuestionerPersona {
  egen('egen', '에겐'),
  teto('teto', '테토'),
  kkondae('kkondae', '꼰대'),
  mungcheong('mungcheong', '멍청'),
  jammin('jammin', '잼민');

  const QuestionerPersona(this.wire, this.label);
  final String wire;
  final String label;

  /// 질의응답 화면의 캐릭터 이름 (예: "꼰대교수").
  String get professorLabel => '$label교수';

  static QuestionerPersona fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => egen);
}

/// 질문 전략 4종 — 리포트 type_scores의 집계 축.
enum QuestionStrategy {
  detailProbe('detail_probe', '디테일 추궁형'),
  bigPicture('big_picture', '큰그림형'),
  basicConcept('basic_concept', '기초 개념형'),
  numericVerification('numeric_verification', '수치 검증형');

  const QuestionStrategy(this.wire, this.label);
  final String wire;
  final String label;

  static QuestionStrategy fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => bigPicture);
}

/// 세션 상태 머신 (spec §4).
enum SessionStatus {
  draft('draft'),
  recordingInProgress('recording_in_progress'),
  transcribing('transcribing'),
  generatingQuestions('generating_questions'),
  qna('qna'),
  completed('completed'),
  failed('failed');

  const SessionStatus(this.wire);
  final String wire;

  static SessionStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => draft);
}

/// 모든 비동기 리소스 공통 상태 (spec §1.2 — 종료 성공은 ready로 단일화).
enum AsyncStatus {
  queued('queued'),
  processing('processing'),
  ready('ready'),
  failed('failed');

  const AsyncStatus(this.wire);
  final String wire;

  bool get isDone => this == ready || this == failed;

  static AsyncStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => queued);
}

/// 답변 상태. `pending`은 답변 미제출(서버에선 row 부재)을 의미.
enum AnswerStatus {
  pending('pending'),
  processing('processing'),
  ready('ready'),
  failed('failed');

  const AnswerStatus(this.wire);
  final String wire;

  static AnswerStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => pending);
}

/// 꼬리질문 생성 판정 상태 (spec §4.4 A 수정).
enum FollowUpStatus {
  pending('pending'),
  generated('generated'),
  none('none');

  const FollowUpStatus(this.wire);
  final String wire;

  static FollowUpStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => none);
}

enum QnaStatus {
  inProgress('in_progress'),
  ended('ended'),
  failed('failed'); // 질문 생성 실패 — 재생성으로 복구

  const QnaStatus(this.wire);
  final String wire;

  static QnaStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => inProgress);
}

/// 발표 진행 방식.
enum SessionMode {
  realtime('realtime', '실시간 녹음'),
  upload('upload', '녹음 파일 업로드');

  const SessionMode(this.wire, this.label);
  final String wire;
  final String label;

  static SessionMode fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => realtime);
}

/// 질의응답 종료 사유 (우선순위: user_end > count_reached > timeout).
enum EndedReason {
  userEnd('user_end'),
  countReached('count_reached'),
  timeout('timeout');

  const EndedReason(this.wire);
  final String wire;

  static EndedReason? fromWire(String? w) {
    if (w == null) return null;
    for (final e in values) {
      if (e.wire == w) return e;
    }
    return null;
  }
}

/// X-Client-Platform 헤더 값 (spec §1 — 토큰 전달 분기).
enum ClientPlatform {
  web('web'),
  ios('ios'),
  android('android');

  const ClientPlatform(this.wire);
  final String wire;
}

/// 소셜 로그인 제공자. 구현 범위는 구글 1종(README 구현 명세서), 나머지는 자리만.
enum SocialProvider {
  google('google'),
  kakao('kakao'),
  naver('naver');

  const SocialProvider(this.wire);
  final String wire;
}

/// 초대 상태.
enum InviteStatus {
  pending('pending'),
  accepted('accepted'),
  declined('declined'),
  canceled('canceled');

  const InviteStatus(this.wire);
  final String wire;

  static InviteStatus fromWire(String w) =>
      values.firstWhere((e) => e.wire == w, orElse: () => pending);
}

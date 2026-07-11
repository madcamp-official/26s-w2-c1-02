import 'enums.dart';
import 'material_info.dart' show ApiErrorInfo;

/// Q&A 전체 상태 (GET /sessions/{id}/qna — 폴링 단일 소스, spec §4.4).
class QnaState {
  const QnaState({
    required this.status,
    this.currentQuestionId,
    this.endedReason,
    this.questions = const [],
  });

  final QnaStatus status;
  final String? currentQuestionId;
  final EndedReason? endedReason;
  final List<Question> questions;

  Question? get currentQuestion {
    for (final q in questions) {
      if (q.id == currentQuestionId) return q;
    }
    return null;
  }

  factory QnaState.fromJson(Map<String, dynamic> json) => QnaState(
        status: QnaStatus.fromWire(json['status'] as String),
        currentQuestionId: json['current_question_id'] as String?,
        endedReason: EndedReason.fromWire(json['ended_reason'] as String?),
        questions: (json['questions'] as List<dynamic>? ?? [])
            .map((e) => Question.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// 질문 하나 (1차 또는 꼬리질문).
class Question {
  const Question({
    required this.id,
    required this.order,
    required this.persona,
    required this.strategy,
    this.parentId,
    this.followUpDepth = 0,
    required this.text,
    required this.evidence,
    required this.tts,
    this.answer,
  });

  final String id;
  final int order;
  final QuestionerPersona persona;
  final QuestionStrategy strategy;

  /// 꼬리질문이면 부모 질문 id (깊이 최대 1).
  final String? parentId;
  final int followUpDepth;
  final String text;
  final Evidence evidence;
  final TtsInfo tts;

  /// 미답변이면 서버가 status=pending으로 내려줌.
  final AnswerInfo? answer;

  bool get isFollowUp => parentId != null;

  factory Question.fromJson(Map<String, dynamic> json) => Question(
        id: json['id'] as String,
        order: json['order'] as int,
        persona: QuestionerPersona.fromWire(json['persona'] as String),
        strategy: QuestionStrategy.fromWire(json['strategy'] as String),
        parentId: json['parent_id'] as String?,
        followUpDepth: json['follow_up_depth'] as int? ?? 0,
        text: json['text'] as String,
        evidence:
            Evidence.fromJson(json['evidence'] as Map<String, dynamic>? ?? {}),
        tts: TtsInfo.fromJson(json['tts'] as Map<String, dynamic>? ?? {}),
        answer: json['answer'] == null
            ? null
            : AnswerInfo.fromJson(json['answer'] as Map<String, dynamic>),
      );
}

/// 질문 근거 — 어느 슬라이드/어느 발화에서 나왔는지.
class Evidence {
  const Evidence({this.slides = const [], this.transcriptRefs = const []});

  final List<int> slides;

  /// "MM:SS" 타임스탬프 목록.
  final List<String> transcriptRefs;

  bool get isEmpty => slides.isEmpty && transcriptRefs.isEmpty;

  factory Evidence.fromJson(Map<String, dynamic> json) => Evidence(
        slides: (json['slides'] as List<dynamic>? ?? [])
            .map((e) => e as int)
            .toList(),
        transcriptRefs: (json['transcript_refs'] as List<dynamic>? ?? [])
            .map((e) => (e as Map<String, dynamic>)['ts'] as String)
            .toList(),
      );
}

/// 질문 TTS 상태 (VoxCPM2 큐 — spec A6).
class TtsInfo {
  const TtsInfo({this.status = AsyncStatus.queued, this.audioUrl});

  final AsyncStatus status;
  final String? audioUrl;

  factory TtsInfo.fromJson(Map<String, dynamic> json) => TtsInfo(
        status: AsyncStatus.fromWire(json['status'] as String? ?? 'queued'),
        audioUrl: json['audio_url'] as String?,
      );
}

/// 답변 상태 (spec §4.4 — 제출은 202, 결과는 폴링).
class AnswerInfo {
  const AnswerInfo({
    required this.status,
    this.text,
    this.audioUrl,
    this.followUpStatus = FollowUpStatus.none,
    this.error,
  });

  final AnswerStatus status;

  /// raw STT 원문 (v0.3 — 간투사 포함).
  final String? text;
  final String? audioUrl;
  final FollowUpStatus followUpStatus;
  final ApiErrorInfo? error;

  factory AnswerInfo.fromJson(Map<String, dynamic> json) => AnswerInfo(
        status: AnswerStatus.fromWire(json['status'] as String),
        text: json['text'] as String?,
        audioUrl: json['audio_url'] as String?,
        followUpStatus: FollowUpStatus.fromWire(
            json['follow_up_status'] as String? ?? 'none'),
        error: json['error'] == null
            ? null
            : ApiErrorInfo.fromJson(json['error'] as Map<String, dynamic>),
      );
}

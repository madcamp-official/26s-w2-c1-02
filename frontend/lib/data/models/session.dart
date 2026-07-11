import 'enums.dart';

/// 발표 세션 (spec §4.1). 발표 1회 = 세션 하나.
class Session {
  const Session({
    required this.id,
    required this.teamId,
    required this.ownerId,
    required this.name,
    required this.status,
    required this.personas,
    required this.questionCount,
    required this.timeLimitMinutes,
    required this.mode,
    this.material,
    this.recording,
    this.transcript,
    this.reportStatus,
    this.createdAt,
  });

  final String id;
  final String teamId;
  final String ownerId;
  final String name;
  final SessionStatus status;
  final List<QuestionerPersona> personas;

  /// 1차(primary) 질문 수 — 꼬리질문 미포함 (spec §4.1).
  final int questionCount;
  final int timeLimitMinutes;
  final SessionMode mode;

  /// 서브리소스 요약 (세션 상세 응답에 포함되는 것).
  final MaterialSummary? material;
  final RecordingSummary? recording;
  final TranscriptSummary? transcript;

  /// completed 이전에는 null (spec A7).
  final AsyncStatus? reportStatus;

  final DateTime? createdAt;

  factory Session.fromJson(Map<String, dynamic> json) => Session(
        id: json['id'] as String,
        teamId: json['team_id'] as String,
        ownerId: json['owner_id'] as String,
        name: json['name'] as String,
        status: SessionStatus.fromWire(json['status'] as String),
        personas: (json['personas'] as List<dynamic>)
            .map((e) => QuestionerPersona.fromWire(e as String))
            .toList(),
        questionCount: json['question_count'] as int,
        timeLimitMinutes: json['time_limit_minutes'] as int,
        mode: SessionMode.fromWire(json['mode'] as String),
        material: json['material'] == null
            ? null
            : MaterialSummary.fromJson(json['material'] as Map<String, dynamic>),
        recording: json['recording'] == null
            ? null
            : RecordingSummary.fromJson(
                json['recording'] as Map<String, dynamic>),
        transcript: json['transcript'] == null
            ? null
            : TranscriptSummary.fromJson(
                json['transcript'] as Map<String, dynamic>),
        reportStatus: json['report'] == null
            ? null
            : AsyncStatus.fromWire(
                (json['report'] as Map<String, dynamic>)['status'] as String),
        createdAt: json['created_at'] == null
            ? null
            : DateTime.parse(json['created_at'] as String),
      );
}

class MaterialSummary {
  const MaterialSummary({required this.status, this.slideCount});
  final AsyncStatus status;
  final int? slideCount;

  factory MaterialSummary.fromJson(Map<String, dynamic> json) =>
      MaterialSummary(
        status: AsyncStatus.fromWire(json['status'] as String),
        slideCount: json['slide_count'] as int?,
      );
}

class RecordingSummary {
  const RecordingSummary({
    required this.status,
    this.durationSeconds,
    this.audioUrl,
  });
  final AsyncStatus status;
  final int? durationSeconds;
  final String? audioUrl;

  factory RecordingSummary.fromJson(Map<String, dynamic> json) =>
      RecordingSummary(
        status: AsyncStatus.fromWire(json['status'] as String),
        durationSeconds: json['duration_seconds'] as int?,
        audioUrl: json['audio_url'] as String?,
      );
}

class TranscriptSummary {
  const TranscriptSummary({required this.status});
  final AsyncStatus status;

  factory TranscriptSummary.fromJson(Map<String, dynamic> json) =>
      TranscriptSummary(status: AsyncStatus.fromWire(json['status'] as String));
}

/// 세션 생성 요청 (spec §4.1).
class SessionCreateRequest {
  const SessionCreateRequest({
    required this.name,
    required this.personas,
    required this.questionCount,
    required this.timeLimitMinutes,
    required this.mode,
  });

  final String name;
  final List<QuestionerPersona> personas;
  final int questionCount;
  final int timeLimitMinutes;
  final SessionMode mode;

  Map<String, dynamic> toJson() => {
        'name': name,
        'personas': personas.map((p) => p.wire).toList(),
        'question_count': questionCount,
        'time_limit_minutes': timeLimitMinutes,
        'mode': mode.wire,
      };
}

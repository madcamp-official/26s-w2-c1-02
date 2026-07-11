import 'enums.dart';
import 'material_info.dart' show ApiErrorInfo;

/// 단일 세션 리포트 (GET /sessions/{id}/report, spec §5.2).
class Report {
  const Report({
    required this.status,
    this.typeScores = const {},
    this.strongTypes = const [],
    this.weakTypes = const [],
    this.speakingHabits,
    this.insight,
    this.error,
  });

  final AsyncStatus status;

  /// QuestionStrategy별 답변 점수 0.0~1.0 — 성장 리포트의 원천.
  final Map<QuestionStrategy, double> typeScores;
  final List<QuestionStrategy> strongTypes;
  final List<QuestionStrategy> weakTypes;
  final SpeakingHabits? speakingHabits;
  final String? insight;
  final ApiErrorInfo? error;

  factory Report.fromJson(Map<String, dynamic> json) {
    final scores = <QuestionStrategy, double>{};
    (json['type_scores'] as Map<String, dynamic>? ?? {}).forEach((k, v) {
      scores[QuestionStrategy.fromWire(k)] = (v as num).toDouble();
    });
    final quality = json['answer_quality'] as Map<String, dynamic>? ?? {};
    List<QuestionStrategy> parseTypes(String key) =>
        (quality[key] as List<dynamic>? ?? [])
            .map((e) => QuestionStrategy.fromWire(e as String))
            .toList();

    return Report(
      status: AsyncStatus.fromWire(json['status'] as String),
      typeScores: scores,
      strongTypes: parseTypes('strong_types'),
      weakTypes: parseTypes('weak_types'),
      speakingHabits: json['speaking_habits'] == null
          ? null
          : SpeakingHabits.fromJson(
              json['speaking_habits'] as Map<String, dynamic>),
      insight: json['insight'] as String?,
      error: json['error'] == null
          ? null
          : ApiErrorInfo.fromJson(json['error'] as Map<String, dynamic>),
    );
  }
}

/// 발표 습관 — WPM은 필러 포함(팀 협의 확정), over_time은 클라이언트 파생.
class SpeakingHabits {
  const SpeakingHabits({
    required this.wordsPerMinute,
    this.fillerWords = const [],
    required this.timeLimitSeconds,
    required this.actualSeconds,
  });

  final double wordsPerMinute;
  final List<FillerWord> fillerWords;
  final int timeLimitSeconds;
  final int actualSeconds;

  int get fillerWordCount =>
      fillerWords.fold(0, (sum, f) => sum + f.count);
  bool get overTime => actualSeconds > timeLimitSeconds;

  factory SpeakingHabits.fromJson(Map<String, dynamic> json) => SpeakingHabits(
        wordsPerMinute: (json['words_per_minute'] as num).toDouble(),
        fillerWords: (json['filler_words'] as List<dynamic>? ?? [])
            .map((e) => FillerWord.fromJson(e as Map<String, dynamic>))
            .toList(),
        timeLimitSeconds: json['time_limit_seconds'] as int,
        actualSeconds: json['actual_seconds'] as int,
      );
}

class FillerWord {
  const FillerWord({required this.word, required this.count});
  final String word;
  final int count;

  factory FillerWord.fromJson(Map<String, dynamic> json) =>
      FillerWord(word: json['word'] as String, count: json['count'] as int);
}

/// 성장 리포트 (GET /users/me/report/growth — 유저 스코프, spec E).
class GrowthReport {
  const GrowthReport({
    required this.range,
    this.teamId,
    this.series = const [],
    this.insight,
  });

  final String range;
  final String? teamId;
  final List<GrowthPoint> series;
  final String? insight;

  factory GrowthReport.fromJson(Map<String, dynamic> json) => GrowthReport(
        range: json['range'] as String,
        teamId: json['team_id'] as String?,
        series: (json['series'] as List<dynamic>? ?? [])
            .map((e) => GrowthPoint.fromJson(e as Map<String, dynamic>))
            .toList(),
        insight: json['insight'] as String?,
      );
}

class GrowthPoint {
  const GrowthPoint({
    required this.sessionId,
    required this.name,
    required this.date,
    this.typeScores = const {},
  });

  final String sessionId;
  final String name;
  final String date;
  final Map<QuestionStrategy, double> typeScores;

  factory GrowthPoint.fromJson(Map<String, dynamic> json) {
    final scores = <QuestionStrategy, double>{};
    (json['type_scores'] as Map<String, dynamic>? ?? {}).forEach((k, v) {
      scores[QuestionStrategy.fromWire(k)] = (v as num).toDouble();
    });
    return GrowthPoint(
      sessionId: json['session_id'] as String,
      name: json['name'] as String,
      date: json['date'] as String,
      typeScores: scores,
    );
  }
}

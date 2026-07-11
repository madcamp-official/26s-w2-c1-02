import 'enums.dart';
import 'material_info.dart' show ApiErrorInfo;

/// 발표 전사 (GET /sessions/{id}/transcript, spec §4.3).
/// v0.3: 원문(raw) ASR — 간투사·비문 포함 가능.
class Transcript {
  const Transcript({
    required this.status,
    this.segments = const [],
    this.error,
  });

  final AsyncStatus status;
  final List<TranscriptSegment> segments;
  final ApiErrorInfo? error;

  factory Transcript.fromJson(Map<String, dynamic> json) => Transcript(
        status: AsyncStatus.fromWire(json['status'] as String),
        segments: (json['segments'] as List<dynamic>? ?? [])
            .map((e) => TranscriptSegment.fromJson(e as Map<String, dynamic>))
            .toList(),
        error: json['error'] == null
            ? null
            : ApiErrorInfo.fromJson(json['error'] as Map<String, dynamic>),
      );
}

class TranscriptSegment {
  const TranscriptSegment({required this.ts, required this.text});

  /// "MM:SS" 형식 (서버가 초→포맷 변환해서 내려줌).
  final String ts;
  final String text;

  factory TranscriptSegment.fromJson(Map<String, dynamic> json) =>
      TranscriptSegment(
        ts: json['ts'] as String,
        text: json['text'] as String,
      );
}

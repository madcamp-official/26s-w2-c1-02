import 'enums.dart';

/// 발표 자료 상세 (GET /sessions/{id}/material, spec §4.2).
class MaterialInfo {
  const MaterialInfo({
    required this.status,
    required this.progress,
    this.fileName,
    this.pageCount,
    this.slides = const [],
    this.error,
  });

  final AsyncStatus status;

  /// 0.0 ~ 1.0
  final double progress;
  final String? fileName;
  final int? pageCount;
  final List<SlidePage> slides;
  final ApiErrorInfo? error;

  factory MaterialInfo.fromJson(Map<String, dynamic> json) => MaterialInfo(
        status: AsyncStatus.fromWire(json['status'] as String),
        progress: (json['progress'] as num?)?.toDouble() ?? 0,
        fileName: json['file_name'] as String?,
        pageCount: json['page_count'] as int?,
        slides: (json['slides'] as List<dynamic>? ?? [])
            .map((e) => SlidePage.fromJson(e as Map<String, dynamic>))
            .toList(),
        error: json['error'] == null
            ? null
            : ApiErrorInfo.fromJson(json['error'] as Map<String, dynamic>),
      );
}

class SlidePage {
  const SlidePage({required this.page, required this.text});
  final int page;
  final String text;

  factory SlidePage.fromJson(Map<String, dynamic> json) =>
      SlidePage(page: json['page'] as int, text: json['text'] as String);
}

/// 리소스에 내장되는 에러 (spec §1.2 — status=failed 시 채워짐).
class ApiErrorInfo {
  const ApiErrorInfo({required this.code, required this.message});
  final String code;
  final String message;

  factory ApiErrorInfo.fromJson(Map<String, dynamic> json) => ApiErrorInfo(
        code: json['code'] as String,
        message: json['message'] as String,
      );
}

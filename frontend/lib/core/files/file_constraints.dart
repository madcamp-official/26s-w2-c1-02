import 'dart:convert';

/// 파일 제약 클라이언트 검증 (api-spec §1.3 · workflow Step 2).
/// 서버가 최종 권위(413/415/422) — 클라이언트는 빠른 피드백용 1차 방어.
class FileConstraints {
  FileConstraints._();

  static const int pdfMaxBytes = 20 * 1024 * 1024; // 20 MB
  static const int pdfMaxPages = 50;
  static const int audioMaxBytes = 200 * 1024 * 1024; // 200 MB
  static const int audioMaxSeconds = 60 * 60; // 60분

  /// 업로드 허용 오디오 확장자 (webm은 v0.4-draft, 웹 녹음 폴백 산출물).
  static const List<String> audioExtensions = ['mp3', 'wav', 'm4a', 'webm'];

  static String _ext(String fileName) {
    final i = fileName.lastIndexOf('.');
    return i < 0 ? '' : fileName.substring(i + 1).toLowerCase();
  }

  static String _mb(int bytes) => (bytes / (1024 * 1024)).toStringAsFixed(1);

  /// PDF 검증. 통과하면 null, 실패하면 사용자 메시지 반환.
  static String? validatePdf({
    required String fileName,
    required int sizeBytes,
    List<int>? bytes,
  }) {
    if (_ext(fileName) != 'pdf') return 'PDF 파일만 업로드할 수 있어요';
    if (sizeBytes > pdfMaxBytes) {
      return 'PDF가 너무 커요 (${_mb(sizeBytes)}MB / 최대 ${_mb(pdfMaxBytes)}MB)';
    }
    if (bytes != null) {
      final pages = estimatePdfPageCount(bytes);
      if (pages != null && pages > pdfMaxPages) {
        return '페이지가 너무 많아요 ($pages페이지 / 최대 $pdfMaxPages페이지)';
      }
    }
    return null;
  }

  /// PDF 페이지 수 best-effort 추정 (`/Type /Page` 오브젝트 카운트).
  /// 압축 오브젝트 스트림 등으로 못 세면 null (서버가 재검증).
  static int? estimatePdfPageCount(List<int> bytes) {
    final text = latin1.decode(bytes, allowInvalid: true);
    final count = RegExp(r'/Type\s*/Page\b').allMatches(text).length;
    return count == 0 ? null : count;
  }

  /// 오디오 파일 업로드 검증 (d3 파일 모드). 통과하면 null.
  /// 재생 길이(60분)는 클라이언트에서 디코딩 없이 알 수 없어 서버가 검증.
  static String? validateAudio({
    required String fileName,
    required int sizeBytes,
  }) {
    if (!audioExtensions.contains(_ext(fileName))) {
      return '${audioExtensions.join(' · ')} 형식만 업로드할 수 있어요';
    }
    if (sizeBytes > audioMaxBytes) {
      return '파일이 너무 커요 (${_mb(sizeBytes)}MB / 최대 ${_mb(audioMaxBytes)}MB)';
    }
    return null;
  }
}

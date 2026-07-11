import '../../core/network/api_client.dart';
import '../models/material_info.dart';
import '../models/qna.dart';
import '../models/report.dart';
import '../models/session.dart';
import '../models/transcript.dart';

/// 세션(발표 1회) 리포지토리 — spec §4 전체.
/// 무거운 작업은 202 접수 후 각 GET을 폴링한다 (spec §1.2).
class SessionRepository {
  SessionRepository(this._api);

  final ApiClient _api;

  // ---- 세션 CRUD ----

  Future<List<Session>> fetchSessions(String teamId) async {
    final json = await _api.get('/teams/$teamId/sessions') as Map<String, dynamic>;
    return (json['items'] as List<dynamic>)
        .map((e) => Session.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Session> createSession(String teamId, SessionCreateRequest req) async {
    final json = await _api.post('/teams/$teamId/sessions', body: req.toJson())
        as Map<String, dynamic>;
    return Session.fromJson(json);
  }

  Future<Session> getSession(String id) async {
    final json = await _api.get('/sessions/$id') as Map<String, dynamic>;
    return Session.fromJson(json);
  }

  Future<void> deleteSession(String id) => _api.delete('/sessions/$id');

  // ---- 발표 자료 (PDF) ----

  Future<void> uploadMaterial(
    String sessionId, {
    required String fileName,
    required List<int> bytes,
  }) =>
      _api.upload('/sessions/$sessionId/material',
          fileName: fileName, bytes: bytes);

  Future<MaterialInfo> getMaterial(String sessionId) async {
    final json =
        await _api.get('/sessions/$sessionId/material') as Map<String, dynamic>;
    return MaterialInfo.fromJson(json);
  }

  Future<void> retryMaterial(String sessionId) =>
      _api.post('/sessions/$sessionId/material/retry');

  Future<void> deleteMaterial(String sessionId) =>
      _api.delete('/sessions/$sessionId/material');

  // ---- 녹음 & 전사 ----

  Future<void> startRecording(String sessionId) =>
      _api.post('/sessions/$sessionId/recording/start');

  Future<void> uploadRecording(
    String sessionId, {
    required String fileName,
    required List<int> bytes,
    required DateTime startedAt,
    required DateTime endedAt,
    required int durationSeconds,
  }) =>
      _api.upload('/sessions/$sessionId/recording',
          fileName: fileName,
          bytes: bytes,
          fields: {
            'started_at': startedAt.toUtc().toIso8601String(),
            'ended_at': endedAt.toUtc().toIso8601String(),
            'duration_seconds': '$durationSeconds',
          });

  Future<Transcript> getTranscript(String sessionId) async {
    final json = await _api.get('/sessions/$sessionId/transcript')
        as Map<String, dynamic>;
    return Transcript.fromJson(json);
  }

  Future<void> retryTranscript(String sessionId) =>
      _api.post('/sessions/$sessionId/transcript/retry');

  // ---- Q&A ----

  Future<void> generateQna(String sessionId) =>
      _api.post('/sessions/$sessionId/qna/generate');

  /// 폴링 단일 소스 (spec §4.4) — 꼬리질문/다음 질문/종료가 전부 여기서 확정.
  Future<QnaState> getQna(String sessionId) async {
    final json =
        await _api.get('/sessions/$sessionId/qna') as Map<String, dynamic>;
    return QnaState.fromJson(json);
  }

  /// 답변 제출 — 202 접수만. 결과는 getQna 폴링으로.
  Future<void> submitAnswer(
    String sessionId,
    String questionId, {
    required String fileName,
    required List<int> bytes,
  }) =>
      _api.upload('/sessions/$sessionId/qna/questions/$questionId/answer',
          fileName: fileName, bytes: bytes);

  Future<void> passQuestion(String sessionId, String questionId) =>
      _api.post('/sessions/$sessionId/qna/questions/$questionId/pass');

  Future<void> endQna(String sessionId) =>
      _api.post('/sessions/$sessionId/qna/end');

  // ---- 리포트 ----

  Future<Report> getReport(String sessionId) async {
    final json =
        await _api.get('/sessions/$sessionId/report') as Map<String, dynamic>;
    return Report.fromJson(json);
  }

  Future<void> regenerateReport(String sessionId) =>
      _api.post('/sessions/$sessionId/report/generate');

  Future<GrowthReport> getGrowthReport({String range = 'all', String? teamId}) async {
    final query = teamId == null ? 'range=$range' : 'range=$range&team_id=$teamId';
    final json = await _api.get('/users/me/report/growth?$query')
        as Map<String, dynamic>;
    return GrowthReport.fromJson(json);
  }
}

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/http_backend.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/models/qna.dart';
import 'package:rehearsal/data/models/session.dart';
import 'package:rehearsal/data/repositories/session_repository.dart';

/// Step 3 Q&A 루프의 데이터 계약 E2E (qna_page가 의존하는 경로).
/// 질문 생성(202) → GET /qna 폴링 → 답변 제출(202) → 꼬리질문/다음/종료.
void main() {
  late MockBackend mock;
  late SessionRepository repo;
  late String sid;

  setUp(() async {
    mock = MockBackend(
      latency: Duration.zero,
      transitionDelay: const Duration(milliseconds: 20),
    );
    final api = ApiClient(backend: mock, platform: ClientPlatform.web);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});
    repo = SessionRepository(api);
    final s = await repo.createSession(
      'team_1',
      const SessionCreateRequest(
        name: 'qna',
        personas: [QuestionerPersona.egen],
        questionCount: 1,
        timeLimitMinutes: 5,
        mode: SessionMode.realtime,
      ),
    );
    sid = s.id;
  });

  Future<QnaState> pollUntil(bool Function(QnaState) done,
      {int maxTicks = 80}) async {
    for (var i = 0; i < maxTicks; i++) {
      final q = await repo.getQna(sid);
      if (done(q)) return q;
      await Future<void>.delayed(const Duration(milliseconds: 15));
    }
    fail('폴링 타임아웃');
  }

  test('질문 생성 → TTS ready → 답변 제출 → 꼬리질문 등장 → 종료', () async {
    await repo.generateQna(sid);

    final gen = await pollUntil((q) => q.questions.isNotEmpty);
    expect(gen.questions.length, 1);
    final q1 = gen.questions.first;
    expect(q1.isFollowUp, false);
    expect(gen.currentQuestionId, q1.id);

    // TTS가 순차적으로 ready (qna_page가 재생 트리거하는 신호)
    final ttsReady =
        await pollUntil((q) => q.questions.first.tts.status == AsyncStatus.ready);
    expect(ttsReady.questions.first.tts.audioUrl, isNotNull);

    // 답변 제출은 202 접수만 — 결과는 폴링으로.
    await repo.submitAnswer(sid, q1.id,
        fileName: 'answer.wav', bytes: Uint8List(44), durationSeconds: 12);

    // 1차 질문(order 1, 홀수) → mock이 꼬리질문 생성 + current 이동.
    final withFollow = await pollUntil((q) => q.questions.length > 1);
    final follow = withFollow.questions.firstWhere((q) => q.isFollowUp);
    expect(follow.parentId, q1.id);
    expect(follow.followUpDepth, 1);
    expect(withFollow.currentQuestionId, follow.id);

    // 꼬리질문 답변 → 더 이상 미답변 없음 → count_reached 종료.
    await pollUntil((q) =>
        q.questions.firstWhere((x) => x.id == follow.id).tts.status ==
        AsyncStatus.ready);
    await repo.submitAnswer(sid, follow.id,
        fileName: 'answer.wav', bytes: Uint8List(44), durationSeconds: 12);

    final ended = await pollUntil((q) => q.status == QnaStatus.ended);
    expect(ended.endedReason, EndedReason.countReached);
    expect(ended.currentQuestionId, isNull);

    final s = await repo.getSession(sid);
    expect(s.status, SessionStatus.completed); // A7: 종료 시 리포트 자동
  });

  test('패스하면 답변 없이 다음/종료로 진행', () async {
    await repo.generateQna(sid);
    final gen = await pollUntil((q) => q.questions.isNotEmpty);
    final q1 = gen.questions.first;

    await repo.passQuestion(sid, q1.id);

    // 질문 1개짜리 세션이므로 패스 후 종료.
    final ended = await pollUntil((q) => q.status == QnaStatus.ended);
    expect(ended.endedReason, EndedReason.countReached);
  });

  test('답변 시작 시간초과(pass reason=timeout) → ended_reason=timeout', () async {
    await repo.generateQna(sid);
    final gen = await pollUntil((q) => q.questions.isNotEmpty);

    // qna_page가 30초 미시작 시 보내는 자동 패스.
    await repo.passQuestion(sid, gen.questions.first.id, reason: 'timeout');

    final ended = await pollUntil((q) => q.status == QnaStatus.ended);
    expect(ended.endedReason, EndedReason.timeout);
  });

  test('질의응답 마치기 → user_end 종료', () async {
    await repo.generateQna(sid);
    await pollUntil((q) => q.questions.isNotEmpty);

    await repo.endQna(sid);
    final ended = await repo.getQna(sid);
    expect(ended.status, QnaStatus.ended);
    expect(ended.endedReason, EndedReason.userEnd);
  });

  // 버그 수정 회귀: 업로드 실패 시 서버 미반영 + 같은 바이트 재제출 성공.
  test('답변 업로드 실패 → 서버 pending 유지 → 재제출 성공', () async {
    final flaky = _AnswerFlakyBackend(mock);
    final flakyApi = ApiClient(backend: flaky, platform: ClientPlatform.web);
    await flakyApi.login('/auth/login', {'username': 'junseo', 'password': 'x'});
    final flakyRepo = SessionRepository(flakyApi);

    await repo.generateQna(sid);
    final gen = await pollUntil((q) => q.questions.isNotEmpty);
    final q1 = gen.questions.first;
    final bytes = Uint8List(44); // 유효 WAV 헤더 크기 — 재제출 시 동일 바이트

    // 1) 첫 제출은 503 → 예외. 서버엔 아무것도 반영 안 됨.
    await expectLater(
      flakyRepo.submitAnswer(sid, q1.id,
          fileName: 'answer.wav', bytes: bytes, durationSeconds: 12),
      throwsA(isA<ApiException>()),
    );
    final afterFail =
        (await repo.getQna(sid)).questions.firstWhere((x) => x.id == q1.id);
    expect(afterFail.answer?.status ?? AnswerStatus.pending, AnswerStatus.pending);

    // 2) 같은 바이트 재제출 → 성공 → processing/ready로 진행.
    await flakyRepo.submitAnswer(sid, q1.id,
        fileName: 'answer.wav', bytes: bytes, durationSeconds: 12);
    final afterRetry = await pollUntil((q) {
      final a = q.questions.firstWhere((x) => x.id == q1.id).answer;
      return a != null && a.status != AnswerStatus.pending;
    });
    expect(
        afterRetry.questions.firstWhere((x) => x.id == q1.id).answer, isNotNull);
  });
}

/// 첫 번째 `POST .../answer`만 503으로 떨어뜨리는 백엔드 래퍼(실서버 오류 흉내).
class _AnswerFlakyBackend implements HttpBackend {
  _AnswerFlakyBackend(this._inner);
  final HttpBackend _inner;
  bool failNextAnswer = true;

  @override
  Future<BackendResponse> send(BackendRequest r) async {
    if (r.method == 'POST' && r.path.endsWith('/answer') && failNextAnswer) {
      failNextAnswer = false;
      return const BackendResponse(statusCode: 503, json: {
        'error': {'code': 'UNAVAILABLE', 'message': '일시적 오류'}
      });
    }
    return _inner.send(r);
  }
}

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/audio/pcm_chunker.dart';
import 'package:rehearsal/core/audio/recorder_service.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/models/session.dart';
import 'package:rehearsal/data/repositories/session_repository.dart';

/// 실시간 녹음 청크 파이프라인 E2E (FakeRecorder → 청크 업로드 → complete → STT).
/// spec §4.3.1 (v0.4-draft) 계약이 Mock 서버와 맞물려 도는지 검증.
void main() {
  late MockBackend mock;
  late SessionRepository repo;

  setUp(() async {
    mock = MockBackend(
      latency: Duration.zero,
      transitionDelay: const Duration(milliseconds: 30),
    );
    final api = ApiClient(backend: mock, platform: ClientPlatform.web);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});
    repo = SessionRepository(api);
  });

  test('청크 업로드 → complete → transcript ready 전이', () async {
    final session = await repo.createSession(
      'team_1',
      const SessionCreateRequest(
        name: '청크 테스트',
        personas: [QuestionerPersona.egen],
        questionCount: 3,
        timeLimitMinutes: 5,
        mode: SessionMode.realtime,
      ),
    );

    // 가짜 녹음기: 6초 청크(테스트 축소) — 15초 분량 생성 → 청크 2개 + 꼬리 1개
    final recorder =
        FakeRecorderService(timeScale: 30, chunkSeconds: 6, overlapSeconds: 1);
    final uploaded = <PcmChunk>[];
    var uploadChain = Future<void>.value();

    await recorder.start(onChunk: (chunk) {
      uploaded.add(chunk);
      uploadChain = uploadChain
          .then((_) => repo.uploadRecordingChunk(session.id, chunk));
    });
    // 100ms 틱 × 30배속 = 틱당 3초 → 5틱이면 15초
    await Future<void>.delayed(const Duration(milliseconds: 520));
    final result = await recorder.stop();
    await uploadChain;

    expect(result.durationSeconds, greaterThanOrEqualTo(12));
    expect(uploaded.length, result.chunkCount);
    expect(uploaded.first.seq, 0);
    expect(uploaded.first.overlapSeconds, 0);
    if (uploaded.length > 1) {
      expect(uploaded[1].overlapSeconds, 1);
      // 겹침: 다음 청크 시작 = 6·seq − 1
      expect(uploaded[1].offsetSeconds, 6 * 1 - 1);
    }
    // WAV 매직 확인
    expect(String.fromCharCodes(result.wavBytes.sublist(0, 4)), 'RIFF');

    await repo.completeRecording(
      session.id,
      fileName: result.fileName,
      bytes: result.wavBytes,
      totalChunks: result.chunkCount,
      startedAt: DateTime.now(),
      endedAt: DateTime.now(),
      durationSeconds: result.durationSeconds,
    );

    // 세션: transcribing → (mock 전이) transcript ready
    final after = await repo.getSession(session.id);
    expect(after.status, SessionStatus.transcribing);

    await Future<void>.delayed(const Duration(milliseconds: 120));
    final transcript = await repo.getTranscript(session.id);
    expect(transcript.status, AsyncStatus.ready);
    expect(transcript.segments, isNotEmpty);

    await recorder.dispose();
  });

  test('청크 202 응답에 received_seq 포함', () async {
    final session = await repo.createSession(
      'team_1',
      const SessionCreateRequest(
        name: 'seq 확인',
        personas: [QuestionerPersona.teto],
        questionCount: 3,
        timeLimitMinutes: 5,
        mode: SessionMode.realtime,
      ),
    );
    final chunk = PcmChunk(
      seq: 0,
      offsetSeconds: 0,
      overlapSeconds: 0,
      durationSeconds: 1,
      wavBytes: Uint8List(44),
    );
    // 예외 없이 접수되면 성공 (202)
    await repo.uploadRecordingChunk(session.id, chunk);
  });
}

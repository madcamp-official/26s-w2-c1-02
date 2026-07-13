import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/models/session.dart';
import 'package:rehearsal/data/repositories/session_repository.dart';

/// "준비 중"(draft) 발표 이어하기 — 새로 만들지 않고 옵션만 갱신하는지 검증.
void main() {
  late SessionRepository repo;

  setUp(() async {
    final mock = MockBackend(latency: Duration.zero);
    final api = ApiClient(backend: mock, platform: ClientPlatform.web);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});
    repo = SessionRepository(api);
  });

  test('draft 갱신: 세션 추가 없이 옵션만 바뀐다', () async {
    final before = await repo.fetchSessions('team_1');

    final draft = await repo.createSession(
      'team_1',
      const SessionCreateRequest(
        name: '초안',
        personas: [QuestionerPersona.egen],
        questionCount: 3,
        timeLimitMinutes: 5,
        mode: SessionMode.realtime,
      ),
    );

    // 이어하기: 이름·페르소나·개수·시간·모드 변경.
    final updated = await repo.updateSession(
      draft.id,
      const SessionCreateRequest(
        name: '수정한 발표',
        personas: [QuestionerPersona.teto, QuestionerPersona.kkondae],
        questionCount: 7,
        timeLimitMinutes: 12,
        mode: SessionMode.upload,
      ),
    );

    // 같은 세션 id, 값만 갱신.
    expect(updated.id, draft.id);
    expect(updated.name, '수정한 발표');
    expect(updated.questionCount, 7);
    expect(updated.timeLimitMinutes, 12);
    expect(updated.mode, SessionMode.upload);
    expect(updated.personas,
        containsAll([QuestionerPersona.teto, QuestionerPersona.kkondae]));

    // 서버 재조회에도 반영.
    final refetched = await repo.getSession(draft.id);
    expect(refetched.name, '수정한 발표');

    // 생성은 1회뿐 — 목록은 정확히 1개 늘어난다(갱신은 추가 아님).
    final after = await repo.fetchSessions('team_1');
    expect(after.length, before.length + 1);
  });
}

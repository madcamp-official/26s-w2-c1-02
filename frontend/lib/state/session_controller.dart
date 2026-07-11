import 'package:flutter/foundation.dart';

import '../data/models/session.dart';
import '../data/repositories/session_repository.dart';

/// 팀별 세션 목록 + 세션 상세 캐시.
/// material/transcript/qna/report 등 폴링 데이터는 화면에서
/// SessionRepository + PollingBuilder로 직접 다룬다 (컨트롤러는 얇게).
class SessionController extends ChangeNotifier {
  SessionController(this._repo);

  final SessionRepository _repo;

  final Map<String, List<Session>> _byTeam = {};
  final Map<String, Session> _byId = {};
  bool _loading = false;

  bool get loading => _loading;

  List<Session> sessionsOf(String teamId) => _byTeam[teamId] ?? const [];

  Session? byId(String id) => _byId[id];

  Future<void> load(String teamId) async {
    _loading = true;
    notifyListeners();
    try {
      final sessions = await _repo.fetchSessions(teamId);
      _byTeam[teamId] = sessions;
      for (final s in sessions) {
        _byId[s.id] = s;
      }
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<Session> create(String teamId, SessionCreateRequest req) async {
    final session = await _repo.createSession(teamId, req);
    await load(teamId);
    return session;
  }

  /// 세션 상세를 서버에서 새로 읽어 캐시 갱신 (상태 전이 확인용).
  Future<Session> refresh(String sessionId) async {
    final session = await _repo.getSession(sessionId);
    _byId[sessionId] = session;
    notifyListeners();
    return session;
  }

  Future<void> deleteSession(Session session) async {
    await _repo.deleteSession(session.id);
    await load(session.teamId);
  }
}

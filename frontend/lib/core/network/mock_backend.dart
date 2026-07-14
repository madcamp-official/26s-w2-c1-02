import 'dart:async';
import 'dart:math';

import 'http_backend.dart';

/// FE의 "가짜 서버" (workflow.md Step 1).
///
/// api-spec v0.3 응답 예시와 **동일한 JSON 형태**를 반환하고,
/// 무거운 작업의 비동기 상태 전이(202 → queued → processing → ready)를
/// 타이머로 시뮬레이션한다. 인터셉터 검증을 위해 access 토큰 만료(401
/// TOKEN_EXPIRED)도 흉내 낸다.
class MockBackend implements HttpBackend {
  MockBackend({
    Duration? latency,
    Duration? transitionDelay,
    this.accessTokenLifetime = const Duration(minutes: 15),
  })  : latency = latency ?? const Duration(milliseconds: 120),
        transitionDelay = transitionDelay ?? const Duration(milliseconds: 1800);

  /// 요청당 네트워크 지연 흉내.
  final Duration latency;

  /// 비동기 작업 한 단계 전이 시간 (queued→processing→ready).
  final Duration transitionDelay;

  /// access 토큰 수명. 테스트에서 짧게 줄여 만료 시나리오 검증.
  final Duration accessTokenLifetime;

  final _rng = Random();

  // ---- in-memory 상태 ----
  final Map<String, DateTime> _accessTokens = {}; // token -> 만료시각
  final Set<String> _refreshTokens = {};
  int _seq = 0;

  // ---- 이메일 인증 mock (email-verification-plan.md §8-5·§9) ----
  // 가입한 유저는 미인증으로 시작해 verify(코드 '000000') 후 로그인 가능.
  // 'unverified'는 로그인 403(EMAIL_NOT_VERIFIED) 분기 테스트용 고정 시드.
  static const verifyCode = '000000';
  final Map<String, String> _emailByUsername = {
    'unverified': 'unverified@rehearsal.io',
  };
  final Set<String> _unverifiedEmails = {'unverified@rehearsal.io'};
  final Map<String, int> _verifyAttempts = {}; // 이메일별 오입력 횟수 (5회 소진)

  static const _me = {
    'id': 'usr_1',
    'name': '준서',
    'username': 'junseo',
    'email': 'bjsbest0326@gmail.com',
  };

  final List<Map<String, dynamic>> _teams = [
    {
      'id': 'team_1',
      'name': 'teamname1',
      'leader_id': 'usr_1',
      'members': [
        {'id': 'usr_1', 'name': '준서'},
        {'id': 'usr_2', 'name': '서진'},
      ],
      'session_count': 2,
    },
    {
      'id': 'team_2',
      'name': 'teamname2',
      'leader_id': 'usr_2',
      'members': [
        {'id': 'usr_1', 'name': '준서'},
        {'id': 'usr_2', 'name': '서진'},
        {'id': 'usr_3', 'name': '서영'},
      ],
      'session_count': 0,
    },
  ];

  /// sessionId -> 세션 상세(JSON). material/transcript/qna/report는 별도 맵.
  final Map<String, Map<String, dynamic>> _sessions = {};
  final Map<String, Map<String, dynamic>> _materials = {};
  final Map<String, Map<String, dynamic>> _transcripts = {};
  final Map<String, Map<String, dynamic>> _qna = {};
  final Map<String, Map<String, dynamic>> _reports = {};

  MockBackend seeded() {
    _seedSession('ses_1', 'team_1', '1차 발표', completed: true);
    _seedSession('ses_2', 'team_1', '2차 발표', completed: false);
    return this;
  }

  String _newId(String prefix) =>
      '${prefix}_${(++_seq).toString().padLeft(3, '0')}${_rng.nextInt(999)}';

  // =====================================================================
  // 라우팅
  // =====================================================================

  @override
  Future<BackendResponse> send(BackendRequest r) async {
    await Future<void>.delayed(latency);
    final path = r.path;
    final m = r.method;

    // ---- 인증 불필요 엔드포인트 ----
    if (m == 'POST' && path == '/auth/login') return _login(r);
    if (m == 'POST' && path.startsWith('/auth/login/social/')) return _login(r);
    if (m == 'POST' && path == '/auth/signup') return _signup(r);
    if (m == 'POST' && path == '/auth/email/verify') return _verifyEmail(r);
    if (m == 'POST' && path == '/auth/email/verify-request') {
      // 재발송 = 새 코드 발급 → 오입력 카운터 리셋. 유저가 없어도·이미
      // 인증돼도 항상 204 (§9 — 계정 존재 여부 노출 방지)
      _verifyAttempts.remove(r.jsonBody?['email'] as String? ?? '');
      return const BackendResponse(statusCode: 204);
    }
    if (m == 'POST' && path == '/auth/refresh') return _refresh(r);
    if (m == 'GET' && _match(path, r'^/invites/([^/]+)$') != null) {
      final code = _match(path, r'^/invites/([^/]+)$')![0];
      // 매직 코드 — 초대코드 참여 에러 UI(§11-2) 검증용.
      if (code == 'BADBADBA') {
        return _err(404, 'INVITE_NOT_FOUND', '존재하지 않는 코드예요');
      }
      if (code == 'EXPIREDX') {
        return _err(410, 'INVITE_EXPIRED', '만료된 초대예요');
      }
      return _ok({
        'team_name': 'teamname1',
        'member_count': 2,
        'session_count': 2,
        'inviter_name': '준서',
      });
    }

    // ---- 여기부터 인증 필요: 토큰 검사 (인터셉터 검증 핵심) ----
    final auth = _checkAuth(r);
    if (auth != null) return auth;

    if (m == 'POST' && path == '/auth/logout') return _logout(r);
    if (m == 'GET' && path == '/auth/me') return _ok({'user': _me});

    // users
    if (path == '/users/me') {
      if (m == 'GET') return _ok(_me);
      if (m == 'PATCH') return _ok({..._me, ...?r.jsonBody});
      if (m == 'DELETE') return const BackendResponse(statusCode: 204);
    }
    if (m == 'PATCH' && path == '/users/me/password') return _ok({});
    if (m == 'GET' && path.startsWith('/users/me/report/growth')) {
      return _growthReport();
    }

    // teams
    if (path == '/teams') {
      if (m == 'GET') return _ok({'items': _teams, 'next_cursor': null});
      if (m == 'POST') return _createTeam(r);
    }
    var g = _match(path, r'^/teams/([^/]+)$');
    if (g != null) {
      final team = _team(g[0]);
      if (team == null) return _err(404, 'TEAM_NOT_FOUND', '팀을 찾을 수 없어요.');
      if (m == 'GET') return _ok(team);
      if (m == 'DELETE') {
        _teams.remove(team);
        return const BackendResponse(statusCode: 204);
      }
    }
    g = _match(path, r'^/teams/([^/]+)/leave$');
    if (g != null && m == 'POST') {
      _teams.removeWhere((t) => t['id'] == g![0]);
      return const BackendResponse(statusCode: 204);
    }
    g = _match(path, r'^/teams/([^/]+)/invites/link$');
    if (g != null) {
      if (m == 'POST' || m == 'GET') {
        // 초대코드 8자 (§11-1: 대문자+숫자, I·O·0·1 제외) — 실서버 형태와 동일하게.
        return _ok({
          'token': 'A2B3C4D5',
          'url': 'https://rehearsal.io/invites/A2B3C4D5',
          'expires_at':
              DateTime.now().add(const Duration(days: 7)).toIso8601String(),
        });
      }
      if (m == 'DELETE') return const BackendResponse(statusCode: 204);
    }
    g = _match(path, r'^/teams/([^/]+)/invites$');
    if (g != null && m == 'POST') {
      return BackendResponse(statusCode: 201, json: {
        'id': _newId('inv'),
        'email': r.jsonBody?['email'],
        'status': 'pending',
      });
    }
    g = _match(path, r'^/invites/([^/]+)/(accept|decline)$');
    if (g != null && m == 'POST') return _ok({'team_id': 'team_1'});

    // sessions
    g = _match(path, r'^/teams/([^/]+)/sessions$');
    if (g != null) {
      if (m == 'GET') {
        final items = _sessions.values
            .where((s) => s['team_id'] == g![0])
            .toList()
          ..sort((a, b) =>
              (b['created_at'] as String).compareTo(a['created_at'] as String));
        return _ok({'items': items, 'next_cursor': null});
      }
      if (m == 'POST') return _createSession(g[0], r);
    }
    g = _match(path, r'^/sessions/([^/]+)$');
    if (g != null) {
      final ses = _sessions[g[0]];
      if (ses == null) {
        return _err(404, 'SESSION_NOT_FOUND', '발표를 찾을 수 없어요.');
      }
      if (m == 'GET') return _ok(ses);
      if (m == 'PATCH') {
        // draft 발표 옵션 갱신 (이어하기).
        final b = r.jsonBody ?? {};
        for (final k in const [
          'name',
          'personas',
          'question_count',
          'time_limit_minutes',
          'mode',
        ]) {
          if (b[k] != null) ses[k] = b[k];
        }
        return _ok(ses);
      }
      if (m == 'DELETE') {
        _sessions.remove(g[0]);
        _materials.remove(g[0]);
        _transcripts.remove(g[0]);
        _qna.remove(g[0]);
        _reports.remove(g[0]);
        return const BackendResponse(statusCode: 204);
      }
    }

    // material
    g = _match(path, r'^/sessions/([^/]+)/material$');
    if (g != null) {
      final id = g[0];
      if (m == 'POST') return _uploadMaterial(id, r);
      if (m == 'GET') {
        return _ok(_materials[id] ?? {'status': 'queued', 'progress': 0.0});
      }
      if (m == 'DELETE') {
        _materials.remove(id);
        _sessions[id]?['material'] = null;
        return const BackendResponse(statusCode: 204);
      }
    }
    g = _match(path, r'^/sessions/([^/]+)/material/retry$');
    if (g != null && m == 'POST') return _uploadMaterial(g[0], r);

    // recording & transcript
    g = _match(path, r'^/sessions/([^/]+)/recording/start$');
    if (g != null && m == 'POST') {
      _sessions[g[0]]?['status'] = 'recording_in_progress';
      return const BackendResponse(statusCode: 202, json: {'status': 'recording_in_progress'});
    }
    g = _match(path, r'^/sessions/([^/]+)/recording/chunks$');
    if (g != null && m == 'POST') return _receiveChunk(g[0], r);
    g = _match(path, r'^/sessions/([^/]+)/recording/complete$');
    if (g != null && m == 'POST') return _completeRecording(g[0], r);
    g = _match(path, r'^/sessions/([^/]+)/recording$');
    if (g != null && m == 'POST') return _uploadRecording(g[0], r);
    g = _match(path, r'^/sessions/([^/]+)/transcript$');
    if (g != null && m == 'GET') {
      return _ok(_transcripts[g[0]] ?? {'status': 'queued', 'segments': []});
    }
    g = _match(path, r'^/sessions/([^/]+)/transcript/retry$');
    if (g != null && m == 'POST') return _uploadRecording(g[0], r);

    // qna
    g = _match(path, r'^/sessions/([^/]+)/qna/generate$');
    if (g != null && m == 'POST') return _generateQna(g[0]);
    g = _match(path, r'^/sessions/([^/]+)/qna$');
    if (g != null && m == 'GET') {
      return _ok(_qna[g[0]] ??
          {'status': 'in_progress', 'current_question_id': null, 'ended_reason': null, 'questions': []});
    }
    g = _match(path, r'^/sessions/([^/]+)/qna/questions/([^/]+)/answer$');
    if (g != null && m == 'POST') return _submitAnswer(g[0], g[1]);
    g = _match(path, r'^/sessions/([^/]+)/qna/questions/([^/]+)/pass$');
    if (g != null && m == 'POST') return _passQuestion(g[0], g[1], r);
    g = _match(path, r'^/sessions/([^/]+)/qna/end$');
    if (g != null && m == 'POST') return _endQna(g[0]);

    // report
    g = _match(path, r'^/sessions/([^/]+)/report$');
    if (g != null && m == 'GET') {
      final rep = _reports[g[0]];
      if (rep == null) return _err(404, 'SESSION_NOT_FOUND', '리포트가 아직 없어요.');
      return _ok(rep);
    }
    g = _match(path, r'^/sessions/([^/]+)/report/generate$');
    if (g != null && m == 'POST') {
      _startReport(g[0]);
      return const BackendResponse(statusCode: 202, json: {'status': 'queued'});
    }

    return _err(404, 'NOT_FOUND', '알 수 없는 경로: $m $path');
  }

  // =====================================================================
  // 인증
  // =====================================================================

  BackendResponse _issueTokens(BackendRequest r) {
    final access = 'acc_${_newId('t')}';
    final refresh = 'ref_${_newId('t')}';
    _accessTokens[access] = DateTime.now().add(accessTokenLifetime);
    _refreshTokens.add(refresh);

    final platform = r.headers['X-Client-Platform'] ?? 'web';
    return _ok({
      'access_token': access,
      // spec §2 B: Web은 refresh를 본문에 담지 않음(httpOnly 쿠키).
      // Mock에서는 쿠키를 흉내낼 수 없어 web도 본문 포함하되, ApiClient가
      // platform에 따라 저장 여부를 결정한다.
      'refresh_token': refresh,
      'token_type': 'Bearer',
      'expires_in': accessTokenLifetime.inSeconds,
      'user': _me,
      '_platform_echo': platform,
    });
  }

  BackendResponse _login(BackendRequest r) {
    // 미인증 유저는 로그인 차단 — FE가 403을 받으면 코드 입력 화면으로 보낸다 (§8-4).
    final username = r.jsonBody?['username'] as String?;
    final email = _emailByUsername[username];
    if (email != null && _unverifiedEmails.contains(email)) {
      return _err(403, 'EMAIL_NOT_VERIFIED', '이메일 인증이 필요해요.');
    }
    return _issueTokens(r);
  }

  BackendResponse _signup(BackendRequest r) {
    final username = r.jsonBody?['username'] as String?;
    final email = r.jsonBody?['email'] as String?;
    if (username != null && email != null) {
      _emailByUsername[username] = email; // 가입 즉시 미인증 — verify 후 로그인 가능 (§8-5)
      _unverifiedEmails.add(email);
    }
    return BackendResponse(
      statusCode: 201,
      json: {
        'user': {..._me, 'email_verified': false},
      },
    );
  }

  BackendResponse _verifyEmail(BackendRequest r) {
    final email = r.jsonBody?['email'] as String? ?? '';
    final code = r.jsonBody?['code'] as String?;
    if (code == '111111') {
      // 매직 코드 — 만료 시나리오 UI(재발송 강조) 검증용. 실서버는 10분 TTL로 발생.
      return _err(400, 'CODE_EXPIRED', '코드가 만료됐어요');
    }
    // 5회 오입력 소진 (§4-2) — attempt 검사가 대조보다 먼저(실서버와 동일 순서).
    if ((_verifyAttempts[email] ?? 0) >= 5) {
      return _err(400, 'CODE_EXPIRED', '코드가 만료됐어요 (5회 초과)');
    }
    if (code != verifyCode) {
      _verifyAttempts[email] = (_verifyAttempts[email] ?? 0) + 1;
      return _err(400, 'INVALID_CODE', '코드가 올바르지 않아요');
    }
    _verifyAttempts.remove(email);
    _unverifiedEmails.remove(email); // 멱등 — 이미 인증된 이메일도 200 (§9)
    return _ok({'email_verified': true});
  }

  BackendResponse _refresh(BackendRequest r) {
    final token = r.jsonBody?['refresh_token'] as String?;
    // Web은 쿠키 기반이라 본문이 비어있을 수 있음 → Mock에서는 항상 허용.
    if (token != null && !_refreshTokens.contains(token)) {
      return _err(401, 'UNAUTHORIZED', 'refresh 토큰이 유효하지 않아요.');
    }
    return _issueTokens(r);
  }

  BackendResponse _logout(BackendRequest r) {
    _accessTokens.clear();
    _refreshTokens.clear();
    return const BackendResponse(statusCode: 204);
  }

  /// Authorization 검사. 문제 없으면 null.
  BackendResponse? _checkAuth(BackendRequest r) {
    final header = r.headers['Authorization'];
    if (header == null || !header.startsWith('Bearer ')) {
      return _err(401, 'UNAUTHORIZED', '로그인이 필요해요.');
    }
    final token = header.substring(7);
    final expiry = _accessTokens[token];
    if (expiry == null) {
      return _err(401, 'UNAUTHORIZED', '유효하지 않은 토큰이에요.');
    }
    if (DateTime.now().isAfter(expiry)) {
      // 인터셉터가 이 코드를 보고 refresh를 시도해야 함.
      return _err(401, 'TOKEN_EXPIRED', '액세스 토큰이 만료됐어요.');
    }
    return null;
  }

  /// 테스트/데모용: 발급된 모든 access 토큰을 즉시 만료시킨다.
  void expireAccessTokens() {
    for (final k in _accessTokens.keys) {
      _accessTokens[k] = DateTime.now().subtract(const Duration(seconds: 1));
    }
  }

  // =====================================================================
  // 팀 · 세션
  // =====================================================================

  Map<String, dynamic>? _team(String id) {
    for (final t in _teams) {
      if (t['id'] == id) return t;
    }
    return null;
  }

  BackendResponse _createTeam(BackendRequest r) {
    final team = {
      'id': _newId('team'),
      'name': r.jsonBody?['name'] ?? '새 팀',
      'leader_id': 'usr_1',
      'members': [
        {'id': 'usr_1', 'name': '준서'},
      ],
      'session_count': 0,
    };
    _teams.add(team);
    return BackendResponse(statusCode: 201, json: team);
  }

  BackendResponse _createSession(String teamId, BackendRequest r) {
    final id = _newId('ses');
    final b = r.jsonBody ?? {};
    final ses = <String, dynamic>{
      'id': id,
      'team_id': teamId,
      'owner_id': 'usr_1',
      'name': b['name'] ?? '발표',
      'status': 'draft',
      'personas': b['personas'] ?? ['egen'],
      'question_count': b['question_count'] ?? 3,
      'time_limit_minutes': b['time_limit_minutes'] ?? 10,
      'mode': b['mode'] ?? 'realtime',
      'material': null,
      'recording': null,
      'transcript': null,
      'report': null,
      'created_at': DateTime.now().toIso8601String(),
    };
    _sessions[id] = ses;
    final team = _team(teamId);
    if (team != null) team['session_count'] = (team['session_count'] as int) + 1;
    return BackendResponse(statusCode: 201, json: ses);
  }

  void _seedSession(String id, String teamId, String name,
      {required bool completed}) {
    _sessions[id] = {
      'id': id,
      'team_id': teamId,
      'owner_id': 'usr_1',
      'name': name,
      'status': completed ? 'completed' : 'draft',
      'personas': ['egen', 'teto', 'kkondae'],
      'question_count': 5,
      'time_limit_minutes': 10,
      'mode': 'realtime',
      'material': completed ? {'status': 'ready', 'slide_count': 10} : null,
      'recording': completed
          ? {'status': 'ready', 'duration_seconds': 663, 'audio_url': 'mock://rec/$id'}
          : null,
      'transcript': completed ? {'status': 'ready'} : null,
      'report': completed ? {'status': 'ready'} : null,
      'created_at': DateTime.now()
          .subtract(Duration(days: completed ? 2 : 1))
          .toIso8601String(),
    };
    if (completed) {
      _transcripts[id] = {
        'status': 'ready',
        'segments': [
          {'ts': '00:12', 'text': '안녕하세요, 어… 오늘 발표를 맡은 준서입니다.'},
          {'ts': '01:40', 'text': '핵심 기능은 세 가지입니다. 첫째, AI가 발표 자료를 분석해 예상 질문을 만들고…'},
          {'ts': '04:12', 'text': '성능은 기존 대비 2배 개선되었습니다. 측정에는 사내 서버를 사용했고…'},
        ],
        'error': null,
      };
      _reports[id] = _readyReport();
      _qna[id] = _seededQnaLog(id);
    }
  }

  /// 완료 세션의 Q&A 로그 시드 (이전 발표 상세의 Q&A 탭 데모용).
  /// 1차 질문 + 꼬리질문(둘 다 답변) + 패스한 질문을 포함.
  Map<String, dynamic> _seededQnaLog(String id) => {
        'status': 'ended',
        'current_question_id': null,
        'ended_reason': 'count_reached',
        'questions': [
          {
            'id': 'q_${id}_1',
            'order': 1,
            'persona': 'kkondae',
            'strategy': 'detail_probe',
            'parent_id': null,
            'follow_up_depth': 0,
            'text': '측정 환경이 정확히 뭐였는지 설명해 주시겠어요?',
            'evidence': {
              'slides': [3],
              'transcript_refs': [{'ts': '04:12'}],
            },
            'tts': {'status': 'ready', 'audio_url': 'mock://tts/q_${id}_1'},
            'answer': {
              'status': 'ready',
              'text': '사내 A100 서버 1대에서 3회 평균으로 측정했습니다.',
              'audio_url': 'mock://answer/q_${id}_1',
              'follow_up_status': 'generated',
            },
          },
          {
            'id': 'q_${id}_1_f1',
            'order': 1,
            'persona': 'kkondae',
            'strategy': 'detail_probe',
            'parent_id': 'q_${id}_1',
            'follow_up_depth': 1,
            'text': '3회 평균이면 편차는 어느 정도였나요?',
            'evidence': {'slides': [], 'transcript_refs': []},
            'tts': {'status': 'ready', 'audio_url': 'mock://tts/q_${id}_1_f1'},
            'answer': {
              'status': 'ready',
              'text': '측정값 편차는 5% 이내였습니다.',
              'audio_url': 'mock://answer/q_${id}_1_f1',
              'follow_up_status': 'none',
            },
          },
          {
            'id': 'q_${id}_2',
            'order': 2,
            'persona': 'egen',
            'strategy': 'big_picture',
            'parent_id': null,
            'follow_up_depth': 0,
            'text': '경쟁 서비스 대비 핵심 차별점은 뭔가요?',
            'evidence': {'slides': [], 'transcript_refs': []},
            'tts': {'status': 'ready', 'audio_url': 'mock://tts/q_${id}_2'},
            'answer': {
              'status': 'ready',
              'text': null, // 패스한 질문
              'audio_url': null,
              'follow_up_status': 'none',
              'passed': true,
            },
          },
        ],
      };

  // =====================================================================
  // 비동기 시뮬레이션: material / recording+STT / qna / report
  // =====================================================================

  BackendResponse _uploadMaterial(String sessionId, BackendRequest r) {
    final fileName = r.multipart?.fileName ?? 'deck.pdf';
    _materials[sessionId] = {
      'status': 'queued',
      'progress': 0.0,
      'file_name': fileName,
      'page_count': null,
      'slides': [],
      'error': null,
    };
    _sessions[sessionId]?['material'] = {'status': 'queued', 'slide_count': null};

    Timer(transitionDelay, () {
      final mat = _materials[sessionId];
      if (mat == null) return;
      mat['status'] = 'processing';
      mat['progress'] = 0.4;
      _sessions[sessionId]?['material'] = {'status': 'processing', 'slide_count': null};
      Timer(transitionDelay, () {
        final mat2 = _materials[sessionId];
        if (mat2 == null) return;
        mat2['status'] = 'ready';
        mat2['progress'] = 1.0;
        mat2['page_count'] = 10;
        mat2['slides'] = List.generate(
            10, (i) => {'page': i + 1, 'text': '슬라이드 ${i + 1} 텍스트 (mock)'});
        _sessions[sessionId]?['material'] = {'status': 'ready', 'slide_count': 10};
      });
    });

    return const BackendResponse(statusCode: 202, json: {'status': 'queued'});
  }

  /// sessionId → 수신한 청크 seq 목록 (spec §4.3.1 v0.4-draft).
  final Map<String, List<int>> _receivedChunks = {};

  /// 청크 수신: 세션은 recording_in_progress 유지, transcript는 processing.
  BackendResponse _receiveChunk(String sessionId, BackendRequest r) {
    final ses = _sessions[sessionId];
    if (ses == null) return _err(404, 'SESSION_NOT_FOUND', '발표를 찾을 수 없어요.');

    final seq = int.tryParse(r.multipart?.fields['seq'] ?? '') ?? -1;
    if (seq < 0) return _err(400, 'VALIDATION', 'seq 필드가 필요해요.');

    (_receivedChunks[sessionId] ??= []).add(seq);
    _transcripts[sessionId] ??= {'status': 'processing', 'segments': [], 'error': null};
    ses['transcript'] = {'status': 'processing'};

    return BackendResponse(statusCode: 202, json: {'received_seq': seq});
  }

  /// 실시간 녹음 종료: 누락 청크 검증 + 전체 파일 저장 + 병합 → transcribing.
  BackendResponse _completeRecording(String sessionId, BackendRequest r) {
    final ses = _sessions[sessionId];
    if (ses == null) return _err(404, 'SESSION_NOT_FOUND', '발표를 찾을 수 없어요.');

    final total =
        int.tryParse(r.multipart?.fields['total_chunks'] ?? '') ?? 0;
    final received = (_receivedChunks[sessionId] ?? []).toSet();
    final missing = [for (var i = 0; i < total; i++) if (!received.contains(i)) i];
    if (missing.isNotEmpty) {
      // 폴백 안전망: 전체 파일이 있으므로 경고만 남기고 진행 (spec §4.3.1)
      // (실서버는 누락 구간만 전체 파일에서 재전사)
    }

    return _uploadRecording(sessionId, r); // 이후 흐름은 단발 업로드와 동일
  }

  BackendResponse _uploadRecording(String sessionId, BackendRequest r) {
    final ses = _sessions[sessionId];
    if (ses == null) return _err(404, 'SESSION_NOT_FOUND', '발표를 찾을 수 없어요.');

    ses['status'] = 'transcribing';
    ses['recording'] = {
      'status': 'ready',
      'duration_seconds':
          (double.tryParse(r.multipart?.fields['duration_seconds'] ?? '') ??
                  300)
              .round(),
      'audio_url': 'mock://rec/$sessionId',
    };
    _transcripts[sessionId] = {'status': 'processing', 'segments': [], 'error': null};
    ses['transcript'] = {'status': 'processing'};

    Timer(transitionDelay * 2, () {
      final t = _transcripts[sessionId];
      if (t == null) return;
      t['status'] = 'ready';
      t['segments'] = [
        {'ts': '00:12', 'text': '안녕하세요, 어… 오늘 발표를 맡은 준서입니다.'},
        {'ts': '04:12', 'text': '성능은 기존 대비 2배 개선되었습니다.'},
      ];
      _sessions[sessionId]?['transcript'] = {'status': 'ready'};
    });

    return const BackendResponse(statusCode: 202, json: {'status': 'processing'});
  }

  BackendResponse _generateQna(String sessionId) {
    final ses = _sessions[sessionId];
    if (ses == null) return _err(404, 'SESSION_NOT_FOUND', '발표를 찾을 수 없어요.');

    ses['status'] = 'generating_questions';
    final personas =
        (ses['personas'] as List<dynamic>).map((e) => e as String).toList();
    final count = ses['question_count'] as int;

    Timer(transitionDelay * 2, () {
      final questions = <Map<String, dynamic>>[];
      const strategies = [
        'detail_probe', 'big_picture', 'basic_concept', 'numeric_verification',
      ];
      for (var i = 0; i < count; i++) {
        final qid = 'q_${sessionId}_${i + 1}';
        questions.add({
          'id': qid,
          'order': i + 1,
          'persona': personas[i % personas.length],
          'strategy': strategies[i % strategies.length],
          'parent_id': null,
          'follow_up_depth': 0,
          'text': '(mock Q${i + 1}) 발표에서 언급한 내용에 대해 더 설명해 주시겠어요?',
          'evidence': i.isEven
              ? {'slides': [i + 1], 'transcript_refs': [{'ts': '0$i:12'}]}
              : {'slides': [], 'transcript_refs': []},
          'tts': {'status': 'queued', 'audio_url': null},
          'answer': {'status': 'pending'},
        });
      }
      _qna[sessionId] = {
        'status': 'in_progress',
        'current_question_id': questions.first['id'],
        'ended_reason': null,
        'questions': questions,
      };
      _sessions[sessionId]?['status'] = 'qna';

      // TTS는 질문별로 순차 ready (VoxCPM2 큐 흉내)
      for (var i = 0; i < questions.length; i++) {
        Timer(transitionDelay * (i + 1), () {
          final q = _findQuestion(sessionId, questions[i]['id'] as String);
          q?['tts'] = {'status': 'ready', 'audio_url': 'mock://tts/${questions[i]['id']}'};
        });
      }
    });

    return const BackendResponse(statusCode: 202, json: {'status': 'generating_questions'});
  }

  Map<String, dynamic>? _findQuestion(String sessionId, String qid) {
    final qna = _qna[sessionId];
    if (qna == null) return null;
    for (final q in qna['questions'] as List<dynamic>) {
      if ((q as Map<String, dynamic>)['id'] == qid) return q;
    }
    return null;
  }

  /// spec §4.4 A 수정 준수: 202 + processing만 반환.
  /// 꼬리질문/다음 질문은 GET /qna 폴링으로 확정된다.
  BackendResponse _submitAnswer(String sessionId, String qid) {
    final q = _findQuestion(sessionId, qid);
    if (q == null) return _err(404, 'SESSION_NOT_FOUND', '질문을 찾을 수 없어요.');

    q['answer'] = {
      'status': 'processing',
      'text': null,
      'audio_url': 'mock://answer/$qid',
      'follow_up_status': 'pending',
    };

    Timer(transitionDelay * 2, () {
      final q2 = _findQuestion(sessionId, qid);
      if (q2 == null) return;
      q2['answer'] = {
        'status': 'ready',
        'text': '(mock) 사내 서버 A100 1대에서 3회 평균으로 측정했습니다.',
        'audio_url': 'mock://answer/$qid',
        'follow_up_status': 'pending',
      };

      // 꼬리질문 판정: 1차 질문 && 홀수 order → 생성 (데모용 결정 규칙)
      Timer(transitionDelay, () {
        final qna = _qna[sessionId];
        final q3 = _findQuestion(sessionId, qid);
        if (qna == null || q3 == null) return;
        final isPrimary = q3['parent_id'] == null;
        final makeFollowUp = isPrimary && (q3['order'] as int).isOdd;

        if (makeFollowUp) {
          final fid = '${qid}_f1';
          final follow = {
            'id': fid,
            'order': q3['order'],
            'persona': q3['persona'],
            'strategy': q3['strategy'],
            'parent_id': qid,
            'follow_up_depth': 1,
            'text': '(mock 꼬리질문) 방금 답변에서 근거를 조금 더 구체적으로 말씀해 주시겠어요?',
            'evidence': {'slides': [], 'transcript_refs': []},
            'tts': {'status': 'queued', 'audio_url': null},
            'answer': {'status': 'pending'},
          };
          final list = qna['questions'] as List<dynamic>;
          list.insert(list.indexOf(q3) + 1, follow);
          (q3['answer'] as Map<String, dynamic>)['follow_up_status'] = 'generated';
          qna['current_question_id'] = fid;
          Timer(transitionDelay, () {
            _findQuestion(sessionId, fid)?['tts'] =
                {'status': 'ready', 'audio_url': 'mock://tts/$fid'};
          });
        } else {
          (q3['answer'] as Map<String, dynamic>)['follow_up_status'] = 'none';
          _advanceOrEnd(sessionId, qid);
        }
      });
    });

    return const BackendResponse(statusCode: 202, json: {
      'answer': {
        'status': 'processing',
        'text': null,
        'audio_url': 'mock://answer/pending',
        'follow_up_status': 'pending',
      }
    });
  }

  BackendResponse _passQuestion(String sessionId, String qid, BackendRequest r) {
    final q = _findQuestion(sessionId, qid);
    if (q == null) return _err(404, 'SESSION_NOT_FOUND', '질문을 찾을 수 없어요.');
    q['answer'] = {
      'status': 'ready',
      'text': null,
      'audio_url': null,
      'follow_up_status': 'none',
      'passed': true,
    };
    // reason=timeout(답변 시작 시간초과) → 마지막 질문이면 ended_reason=timeout.
    final reason = r.jsonBody?['reason'] as String?;
    _advanceOrEnd(sessionId, qid,
        endReason: reason == 'timeout' ? 'timeout' : 'count_reached');
    return _ok(_qna[sessionId]!);
  }

  /// 다음 미답변 질문으로 이동, 없으면 [endReason]으로 종료.
  void _advanceOrEnd(String sessionId, String fromQid,
      {String endReason = 'count_reached'}) {
    final qna = _qna[sessionId];
    if (qna == null) return;
    final list = (qna['questions'] as List<dynamic>).cast<Map<String, dynamic>>();
    final next = list.where((q) {
      final a = q['answer'] as Map<String, dynamic>?;
      return a == null || a['status'] == 'pending';
    }).firstOrNull;

    if (next != null) {
      qna['current_question_id'] = next['id'];
    } else {
      qna['status'] = 'ended';
      qna['ended_reason'] = endReason;
      qna['current_question_id'] = null;
      _completeSession(sessionId);
    }
  }

  BackendResponse _endQna(String sessionId) {
    final qna = _qna[sessionId];
    if (qna != null) {
      qna['status'] = 'ended';
      qna['ended_reason'] = 'user_end';
      qna['current_question_id'] = null;
    }
    _completeSession(sessionId);
    return const BackendResponse(statusCode: 202, json: {'status': 'completed'});
  }

  void _completeSession(String sessionId) {
    _sessions[sessionId]?['status'] = 'completed';
    _startReport(sessionId); // A7: 종료 시 리포트 자동 생성
  }

  void _startReport(String sessionId) {
    _reports[sessionId] = {'status': 'processing'};
    _sessions[sessionId]?['report'] = {'status': 'processing'};
    Timer(transitionDelay * 2, () {
      if (_reports[sessionId] == null) return;
      _reports[sessionId] = _readyReport();
      _sessions[sessionId]?['report'] = {'status': 'ready'};
    });
  }

  Map<String, dynamic> _readyReport() => {
        'status': 'ready',
        'type_scores': {
          'detail_probe': 0.40,
          'big_picture': 0.85,
          'basic_concept': 0.80,
          'numeric_verification': 0.35,
        },
        'answer_quality': {
          'strong_types': ['big_picture', 'basic_concept'],
          'weak_types': ['detail_probe', 'numeric_verification'],
        },
        'speaking_habits': {
          'words_per_minute': 182,
          'filler_words': [
            {'word': '음', 'count': 9},
            {'word': '어', 'count': 5},
          ],
          'time_limit_seconds': 600,
          'actual_seconds': 663,
        },
        'insight': '필러 워드가 도입부에 몰려 있어요. 첫 1분 대본을 미리 정해두면 좋아요.',
      };

  BackendResponse _growthReport() => _ok({
        'range': 'all',
        'user_id': 'usr_1',
        'team_id': null,
        'series': [
          {
            'session_id': 'ses_1',
            'name': '1차 발표',
            'date': '2026-07-08',
            'type_scores': {'detail_probe': 0.40, 'numeric_verification': 0.30},
          },
          {
            'session_id': 'ses_2',
            'name': '2차 발표',
            'date': '2026-07-09',
            'type_scores': {'detail_probe': 0.62, 'numeric_verification': 0.45},
          },
        ],
        'insight': '디테일 추궁형 점수가 2회차 연속 올랐어요. 수치 검증형은 아직 준비가 필요해요.',
      });

  // =====================================================================
  // 헬퍼
  // =====================================================================

  BackendResponse _ok(Map<String, dynamic> json) =>
      BackendResponse(statusCode: 200, json: json);

  BackendResponse _err(int status, String code, String message) =>
      BackendResponse(statusCode: status, json: {
        'error': {'code': code, 'message': message, 'details': {}},
      });

  /// 정규식 매칭 → 캡처 그룹 리스트 (미매칭 시 null).
  List<String>? _match(String path, String pattern) {
    final m = RegExp(pattern).firstMatch(path);
    if (m == null) return null;
    return [for (var i = 1; i <= m.groupCount; i++) m.group(i)!];
  }
}

extension<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

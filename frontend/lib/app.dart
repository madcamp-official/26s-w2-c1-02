import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/audio/audio_player_service.dart';
import 'core/audio/recorder_service.dart';
import 'core/config/env.dart';
import 'core/network/api_client.dart';
import 'core/network/http_backend.dart';
import 'core/network/mock_backend.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';
import 'data/repositories/auth_repository.dart';
import 'data/repositories/session_repository.dart';
import 'data/repositories/team_repository.dart';
import 'state/auth_controller.dart';
import 'state/session_controller.dart';
import 'state/team_controller.dart';

/// 앱 루트: 백엔드/ApiClient/repository/controller 조립.
///
/// Mock ↔ 실서버 전환은 [HttpBackend] 주입 하나로 결정된다
/// (`--dart-define=USE_MOCK=false`). 인터셉터·repository·화면 코드는
/// 두 모드에서 완전히 동일한 경로를 탄다 (workflow 공통 가이드 2).
class RehearsalApp extends StatefulWidget {
  const RehearsalApp({super.key});

  @override
  State<RehearsalApp> createState() => _RehearsalAppState();
}

class _RehearsalAppState extends State<RehearsalApp> {
  late final ApiClient _api;
  late final AuthController _auth;
  late final TeamController _teams;
  late final SessionController _sessions;
  late final AppRouter _router;

  @override
  void initState() {
    super.initState();
    final HttpBackend backend = Env.useMockData
        ? (MockBackend()..seeded())
        : RealHttpBackend(baseUrl: '${Env.apiBaseUrl}/api/v1');
    _api = ApiClient(backend: backend);

    _auth = AuthController(AuthRepository(_api));
    _teams = TeamController(TeamRepository(_api));
    _sessions = SessionController(SessionRepository(_api));
    _api.onAuthExpired = _auth.handleAuthExpired;
    _router = AppRouter(_auth);

    // 새로고침으로 메모리의 access 토큰이 사라져도, 저장된 세션(Web=httpOnly 쿠키)으로
    // 로그인 상태를 되살린다. 완료되면 notifyListeners → 라우터가 다시 판단한다.
    _auth.restoreSession();
  }

  @override
  void dispose() {
    _auth.dispose();
    _teams.dispose();
    _sessions.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider.value(value: _api),
        Provider(create: (_) => SessionRepository(_api)),
        Provider(create: (_) => TeamRepository(_api)),
        Provider<RecorderService>(
          create: (_) => MicRecorderService(),
          dispose: (_, r) => r.dispose(),
        ),
        Provider<AudioPlayerService>(
          create: (_) => JustAudioPlayerService(),
          dispose: (_, p) => p.dispose(),
        ),
        ChangeNotifierProvider.value(value: _auth),
        ChangeNotifierProvider.value(value: _teams),
        ChangeNotifierProvider.value(value: _sessions),
      ],
      child: MaterialApp.router(
        title: '말꼬리',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        routerConfig: _router.router,
      ),
    );
  }
}

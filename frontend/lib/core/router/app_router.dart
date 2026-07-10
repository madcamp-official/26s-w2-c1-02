import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/login_page.dart';
import '../../features/home/home_page.dart';
import '../../features/profile/my_page.dart';
import '../../features/speech/create_speech_page.dart';
import '../../features/speech/presenting_page.dart';
import '../../features/speech/qna_page.dart';
import '../../features/team/create_team_page.dart';
import '../../features/team/team_detail_page.dart';
import '../../state/auth_controller.dart';

/// 앱 라우팅. go_router 사용 → 웹에서 URL 딥링크/뒤로가기까지 지원.
class AppRouter {
  AppRouter(this.auth);

  final AuthController auth;

  late final GoRouter router = GoRouter(
    initialLocation: '/',
    refreshListenable: auth,
    redirect: (context, state) {
      final loggingIn = state.matchedLocation == '/login';
      if (!auth.isLoggedIn) return loggingIn ? null : '/login';
      if (loggingIn) return '/';
      return null;
    },
    routes: [
      GoRoute(
        path: '/login',
        name: 'login',
        builder: (context, state) => const LoginPage(),
      ),
      GoRoute(
        path: '/',
        name: 'home',
        builder: (context, state) => const HomePage(),
      ),
      GoRoute(
        path: '/me',
        name: 'myPage',
        builder: (context, state) => const MyPage(),
      ),
      GoRoute(
        path: '/teams/new',
        name: 'createTeam',
        builder: (context, state) => const CreateTeamPage(),
      ),
      GoRoute(
        path: '/teams/:teamId',
        name: 'teamDetail',
        builder: (context, state) =>
            TeamDetailPage(teamId: state.pathParameters['teamId']!),
      ),
      GoRoute(
        path: '/teams/:teamId/speeches/new',
        name: 'createSpeech',
        builder: (context, state) =>
            CreateSpeechPage(teamId: state.pathParameters['teamId']!),
      ),
      GoRoute(
        path: '/speeches/:speechId/present',
        name: 'present',
        builder: (context, state) =>
            PresentingPage(speechId: state.pathParameters['speechId']!),
      ),
      GoRoute(
        path: '/speeches/:speechId/qna',
        name: 'qna',
        builder: (context, state) =>
            QnaPage(speechId: state.pathParameters['speechId']!),
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('페이지를 찾을 수 없어요: ${state.uri}')),
    ),
  );
}

/// 앱 실행 환경 설정.
///
/// 백엔드 붙이기 전까지는 [useMockData] = true 로 두면
/// 로컬 목 데이터로 전체 플로우가 동작한다.
///
/// 실제 API로 전환할 때:
///   flutter run --dart-define=USE_MOCK=false --dart-define=API_BASE_URL=http://localhost:8000
class Env {
  Env._();

  static const bool useMockData =
      bool.fromEnvironment('USE_MOCK', defaultValue: true);

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );
}

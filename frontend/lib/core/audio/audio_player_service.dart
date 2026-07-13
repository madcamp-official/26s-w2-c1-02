import 'dart:async';

import 'package:just_audio/just_audio.dart';

/// 질문 TTS 재생 추상화 (api-spec §4.4 — 질문 음성 재생 / 다시 듣기).
///
/// - 실서버: `question.tts.audio_url`(http) → [JustAudioPlayerService]가 실제 재생.
/// - Mock 모드: URL이 `mock://…`이라 재생할 실체가 없으므로 **재생 시간을 흉내**만 낸다.
///   FE는 Mock에서도 "재생 완료 → 자동 답변 녹음" 플로우를 그대로 검증할 수 있다.
///
/// [play]는 **재생이 끝나면**(또는 [stop] 호출 시) resolve 되는 Future를 돌려준다.
/// 호출부는 `await player.play(url)` 후 자동으로 답변 녹음을 시작한다.
abstract class AudioPlayerService {
  /// [url]을 끝까지 재생. 완료/중단 시 resolve. 다시 듣기 = 같은 url로 재호출.
  Future<void> play(String url);

  /// 재생 중지 (진행 중인 [play] Future를 즉시 완료시킨다).
  Future<void> stop();

  Future<void> dispose();
}

/// just_audio 기반 실구현. `mock://` 스킴은 지연만 흉내 낸다.
class JustAudioPlayerService implements AudioPlayerService {
  JustAudioPlayerService({Duration? mockDuration})
      : _mockDuration = mockDuration ?? const Duration(milliseconds: 2200);

  /// Mock URL 재생을 흉내 낼 시간 (TTS 한 문장 길이 근사).
  final Duration _mockDuration;

  final AudioPlayer _player = AudioPlayer();

  /// mock:// 재생 중단용.
  Completer<void>? _mockCompleter;
  Timer? _mockTimer;

  @override
  Future<void> play(String url) async {
    await stop(); // 이전 재생 정리 (다시 듣기)

    if (url.startsWith('mock://')) {
      final completer = Completer<void>();
      _mockCompleter = completer;
      _mockTimer = Timer(_mockDuration, () {
        if (!completer.isCompleted) completer.complete();
      });
      return completer.future;
    }

    await _player.setUrl(url);
    // just_audio의 play()는 재생이 끝나거나 정지되면 완료된다.
    await _player.play();
  }

  @override
  Future<void> stop() async {
    _mockTimer?.cancel();
    _mockTimer = null;
    final c = _mockCompleter;
    _mockCompleter = null;
    if (c != null && !c.isCompleted) c.complete();

    if (_player.playing) await _player.stop();
  }

  @override
  Future<void> dispose() async {
    _mockTimer?.cancel();
    await _player.dispose();
  }
}

/// 테스트/마이크 없는 데모용 — 실제 재생 없이 [playDuration] 뒤 완료.
class FakeAudioPlayerService implements AudioPlayerService {
  FakeAudioPlayerService({this.playDuration = Duration.zero});

  final Duration playDuration;

  /// 재생 요청된 URL 이력 (테스트 검증용).
  final List<String> playedUrls = [];
  Completer<void>? _completer;
  Timer? _timer;

  @override
  Future<void> play(String url) async {
    await stop();
    playedUrls.add(url);
    final completer = Completer<void>();
    _completer = completer;
    if (playDuration == Duration.zero) {
      completer.complete();
    } else {
      _timer = Timer(playDuration, () {
        if (!completer.isCompleted) completer.complete();
      });
    }
    return completer.future;
  }

  @override
  Future<void> stop() async {
    _timer?.cancel();
    _timer = null;
    final c = _completer;
    _completer = null;
    if (c != null && !c.isCompleted) c.complete();
  }

  @override
  Future<void> dispose() async {
    _timer?.cancel();
  }
}

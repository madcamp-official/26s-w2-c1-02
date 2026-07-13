import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/audio/audio_player_service.dart';

/// Step 3 오디오 재생 추상화 — 재생 완료 시 resolve 되는 계약 검증.
/// (qna_page는 `await player.play(url)` 후 자동으로 답변 녹음을 시작한다.)
void main() {
  test('FakeAudioPlayer: play가 URL을 기록하고 즉시 완료', () async {
    final player = FakeAudioPlayerService();
    await player.play('mock://tts/q1');
    expect(player.playedUrls, ['mock://tts/q1']);

    // 같은 URL로 재호출 가능(멱등)
    await player.play('mock://tts/q1');
    expect(player.playedUrls.length, 2);
    await player.dispose();
  });

  test('FakeAudioPlayer: stop이 진행 중 재생을 즉시 완료시킨다', () async {
    final player =
        FakeAudioPlayerService(playDuration: const Duration(seconds: 5));
    final playing = player.play('mock://tts/long');
    await player.stop();
    await playing; // stop 없으면 5초 hang — stop으로 즉시 완료돼야 통과
    expect(player.playedUrls, ['mock://tts/long']);
    await player.dispose();
  });
}

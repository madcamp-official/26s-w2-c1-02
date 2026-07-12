import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/audio/pcm_chunker.dart';
import 'package:rehearsal/core/audio/wav_codec.dart';

/// 청크 파이프라인 검증 (spec §4.3.1: 60초 + 4초 겹침).
/// 테스트는 빠르게: 6초 청크 + 1초 겹침으로 축소 (로직 동일).
void main() {
  const sr = 16000;
  const bps = sr * 2; // 16-bit mono bytes/sec

  Uint8List pcmSeconds(double seconds, {int fill = 0}) =>
      Uint8List((seconds * bps).round())..fillRange(0, (seconds * bps).round(), fill);

  PcmChunker chunker() =>
      PcmChunker(sampleRate: sr, chunkSeconds: 6, overlapSeconds: 1);

  test('경계마다 청크 방출: 오프셋·겹침·길이가 계약대로', () {
    final c = chunker();
    final out = <PcmChunk>[];

    // 14초 주입 (3.5초씩 4번) → 6s·12s 경계에서 2개 방출
    for (var i = 0; i < 4; i++) {
      out.addAll(c.add(pcmSeconds(3.5)));
    }
    expect(out.length, 2);

    // 청크0: [0, 6), 겹침 0
    expect(out[0].seq, 0);
    expect(out[0].offsetSeconds, 0);
    expect(out[0].overlapSeconds, 0);
    expect(out[0].durationSeconds, 6);

    // 청크1: [5, 12) — 앞 1초 겹침
    expect(out[1].seq, 1);
    expect(out[1].offsetSeconds, 5);
    expect(out[1].overlapSeconds, 1);
    expect(out[1].durationSeconds, 7);

    // flush → 꼬리 [11, 14) = 3초
    final tail = c.flush();
    expect(tail, isNotNull);
    expect(tail!.seq, 2);
    expect(tail.offsetSeconds, 11);
    expect(tail.durationSeconds, 3);
    expect(c.emittedCount, 3);
  });

  test('청크 길이 미만 녹음 → flush에서 단일 청크', () {
    final c = chunker();
    expect(c.add(pcmSeconds(2)), isEmpty);
    final tail = c.flush();
    expect(tail!.seq, 0);
    expect(tail.offsetSeconds, 0);
    expect(tail.overlapSeconds, 0);
    expect(tail.durationSeconds, 2);
    expect(c.flush(), isNull); // 두 번째 flush는 없음
  });

  test('겹침 구간 데이터가 실제로 이전 청크 끝과 동일', () {
    final c = chunker();
    final out = <PcmChunk>[];
    // 값이 초 단위로 구분되게: i번째 1초는 값 i로 채움
    for (var i = 0; i < 12; i++) {
      out.addAll(c.add(pcmSeconds(1, fill: i)));
    }
    // 12초 = 정확히 두 경계 → add에서 2개 방출, flush는 null
    expect(out.length, 2);
    expect(c.flush(), isNull);
    // 청크1은 [5, 12) — wav 헤더(44B) 뒤 첫 바이트 = 5초 지점 값(5)
    expect(out[1].wavBytes[44], 5);
    // 청크0의 마지막 바이트(6초 직전) = 값 5 — 겹침 구간 일치 확인
    expect(out[0].wavBytes.last, 5);
  });

  test('전체 WAV: 헤더 + 총 길이 보존', () {
    final c = chunker();
    c.add(pcmSeconds(7.5));
    c.flush();
    final wav = c.buildFullWav();
    expect(wav.length, 44 + (7.5 * bps).round());
    // RIFF/WAVE 매직
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
    expect(c.totalSeconds, 7.5);
  });

  test('wav_codec: 16kHz 모노 16bit 헤더 필드', () {
    final wav = encodeWav(Uint8List(3200)); // 0.1초
    final bd = ByteData.sublistView(wav);
    expect(bd.getUint32(24, Endian.little), 16000); // sampleRate
    expect(bd.getUint16(22, Endian.little), 1); // channels
    expect(bd.getUint16(34, Endian.little), 16); // bits
    expect(bd.getUint32(40, Endian.little), 3200); // data size
  });
}

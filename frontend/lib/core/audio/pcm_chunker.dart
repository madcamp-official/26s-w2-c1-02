import 'dart:typed_data';

import 'wav_codec.dart';

/// 실시간 녹음 청크 (api-spec §4.3.1).
class PcmChunk {
  const PcmChunk({
    required this.seq,
    required this.offsetSeconds,
    required this.overlapSeconds,
    required this.durationSeconds,
    required this.wavBytes,
  });

  /// 0-base 순번.
  final int seq;

  /// 녹음 시작 기준 시작 오프셋 (겹침 포함): max(0, 60·seq − 4).
  final double offsetSeconds;

  /// 앞 청크와의 겹침 (첫 청크 0, 이후 4).
  final double overlapSeconds;
  final double durationSeconds;
  final Uint8List wavBytes;
}

/// PCM16 스트림을 60초 + 4초 겹침 청크로 분할 (README 아키텍처 · STT 실측 확정값).
///
/// - 경계 단어 잘림 방지: 청크 i는 [max(0, 60i−4), 60(i+1)) 구간을 커버.
/// - 전체 재생용 원본도 함께 축적 → [buildFullWav]로 종료 시 확보.
/// - 불변 조건(청크 STT 처리시간 < 청크 길이)은 서버 측 실측으로 보장됨(RTF≈0.03).
class PcmChunker {
  PcmChunker({
    this.sampleRate = 16000,
    this.chunkSeconds = 60,
    this.overlapSeconds = 4,
  });

  final int sampleRate;
  final int chunkSeconds;
  final int overlapSeconds;

  int get _bps => sampleRate * 2; // 16-bit mono: bytes per second

  final BytesBuilder _full = BytesBuilder(copy: false);

  /// 현재 미방출 구간을 담는 롤링 윈도우 (겹침 tail 포함).
  final List<Uint8List> _window = [];

  /// _window 첫 바이트의 절대 오프셋.
  int _windowStart = 0;
  int _totalBytes = 0;
  int _emitted = 0;

  int get emittedCount => _emitted;
  double get totalSeconds => _totalBytes / _bps;

  /// PCM 데이터 추가. 60초 경계를 넘을 때마다 완성된 청크를 반환.
  List<PcmChunk> add(Uint8List pcm) {
    _full.add(pcm);
    _window.add(pcm);
    _totalBytes += pcm.length;

    final chunks = <PcmChunk>[];
    // 청크 i의 끝 = (i+1)·60s. 끝까지 데이터가 차면 방출.
    while (_totalBytes >= (_emitted + 1) * chunkSeconds * _bps) {
      chunks.add(_emit(endByte: (_emitted + 1) * chunkSeconds * _bps));
    }
    return chunks;
  }

  /// 녹음 종료: 남은 꼬리 구간(60초 미만)을 마지막 청크로 방출.
  PcmChunk? flush() {
    final lastEnd = _emitted * chunkSeconds * _bps;
    if (_totalBytes <= lastEnd) return null; // 새 데이터 없음
    return _emit(endByte: _totalBytes);
  }

  PcmChunk _emit({required int endByte}) {
    final seq = _emitted;
    final overlapBytes = seq == 0 ? 0 : overlapSeconds * _bps;
    final startByte = seq * chunkSeconds * _bps - overlapBytes;

    final pcm = _slice(startByte, endByte);
    _emitted++;

    // 다음 청크 시작(겹침 포함) 이전 데이터는 윈도우에서 폐기.
    _trimWindowBefore(_emitted * chunkSeconds * _bps - overlapSeconds * _bps);

    return PcmChunk(
      seq: seq,
      offsetSeconds: startByte / _bps,
      overlapSeconds: seq == 0 ? 0 : overlapSeconds.toDouble(),
      durationSeconds: (endByte - startByte) / _bps,
      wavBytes: encodeWav(pcm, sampleRate: sampleRate),
    );
  }

  /// 절대 오프셋 [start, end) 구간을 윈도우에서 추출.
  Uint8List _slice(int start, int end) {
    final out = Uint8List(end - start);
    var written = 0;
    var pieceStart = _windowStart;
    for (final piece in _window) {
      final pieceEnd = pieceStart + piece.length;
      final from = start > pieceStart ? start : pieceStart;
      final to = end < pieceEnd ? end : pieceEnd;
      if (to > from) {
        out.setRange(written, written + (to - from),
            piece.sublist(from - pieceStart, to - pieceStart));
        written += to - from;
      }
      pieceStart = pieceEnd;
      if (pieceStart >= end) break;
    }
    return out;
  }

  void _trimWindowBefore(int keepFrom) {
    while (_window.isNotEmpty &&
        _windowStart + _window.first.length <= keepFrom) {
      _windowStart += _window.first.length;
      _window.removeAt(0);
    }
  }

  /// 재생용 전체 WAV (README: "재생용 전체 파일도 종료 시 확보").
  Uint8List buildFullWav() =>
      encodeWav(_full.toBytes(), sampleRate: sampleRate);
}

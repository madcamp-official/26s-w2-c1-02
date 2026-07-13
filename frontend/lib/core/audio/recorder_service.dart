import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

import 'package:record/record.dart';

import 'pcm_chunker.dart';

/// 녹음 결과 (전체 재생용 파일).
class RecordingResult {
  const RecordingResult({
    required this.wavBytes,
    required this.durationSeconds,
    required this.chunkCount,
  });

  final Uint8List wavBytes;
  final double durationSeconds;

  /// 방출된 청크 수 (complete의 total_chunks).
  final int chunkCount;

  String get fileName => 'recording.wav';
}

/// 마이크 녹음 서비스.
///
/// PCM 16kHz 모노 스트림을 받아 [PcmChunker]로 60+4초 청크를 만들고,
/// 청크가 완성될 때마다 [onChunk]를 호출한다 (api-spec §4.3.1).
/// 웹/모바일 공통 — 산출물은 항상 wav (spec §1.3).
abstract class RecorderService {
  /// 마이크 권한 확인/요청.
  Future<bool> hasPermission();

  /// 녹음 시작. [onChunk]는 60초 경계마다 호출됨 (마지막 꼬리는 stop에서).
  Future<void> start({required void Function(PcmChunk chunk) onChunk});

  /// 녹음 종료 → 꼬리 청크 방출 + 전체 파일 반환.
  Future<RecordingResult> stop();

  /// 진행 중 여부.
  bool get isRecording;

  Future<void> dispose();
}

/// record 패키지 기반 실구현 (web/iOS/Android).
class MicRecorderService implements RecorderService {
  MicRecorderService({int chunkSeconds = 60, int overlapSeconds = 4})
      : _chunkSeconds = chunkSeconds,
        _overlapSeconds = overlapSeconds;

  final int _chunkSeconds;
  final int _overlapSeconds;

  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _sub;
  PcmChunker? _chunker;
  void Function(PcmChunk)? _onChunk;

  @override
  bool get isRecording => _chunker != null;

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<void> start({required void Function(PcmChunk chunk) onChunk}) async {
    if (isRecording) throw StateError('이미 녹음 중입니다');
    _onChunk = onChunk;
    _chunker = PcmChunker(
        chunkSeconds: _chunkSeconds, overlapSeconds: _overlapSeconds);

    // PCM 스트림 (STT 표준: 16kHz 모노 16bit). 미지원 브라우저는 여기서 throw
    // → UI가 파일 업로드 모드 안내 (spec §4.3.1 폴백).
    final stream = await _recorder.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
    ));

    _sub = stream.listen((data) {
      final chunker = _chunker;
      if (chunker == null) return;
      for (final chunk in chunker.add(data)) {
        _onChunk?.call(chunk);
      }
    });
  }

  @override
  Future<RecordingResult> stop() async {
    final chunker = _chunker;
    if (chunker == null) throw StateError('녹음 중이 아닙니다');

    await _sub?.cancel();
    _sub = null;
    await _recorder.stop();

    final tail = chunker.flush();
    if (tail != null) _onChunk?.call(tail);

    final result = RecordingResult(
      wavBytes: chunker.buildFullWav(),
      durationSeconds: chunker.totalSeconds,
      chunkCount: chunker.emittedCount,
    );
    _chunker = null;
    _onChunk = null;
    return result;
  }

  @override
  Future<void> dispose() async {
    await _sub?.cancel();
    await _recorder.dispose();
  }
}

/// 마이크 없이 동작하는 가짜 녹음기 — 위젯 테스트·권한 거부 시 데모용.
/// 실시간으로 저음 사인파 PCM을 생성한다 (무음이면 STT 디버깅이 애매해서).
class FakeRecorderService implements RecorderService {
  FakeRecorderService({
    this.timeScale = 1,
    int chunkSeconds = 60,
    int overlapSeconds = 4,
  })  : _chunkSeconds = chunkSeconds,
        _overlapSeconds = overlapSeconds;

  /// 테스트 가속용: 1틱(100ms)당 생성할 오디오 배수.
  final int timeScale;
  final int _chunkSeconds;
  final int _overlapSeconds;

  Timer? _timer;
  PcmChunker? _chunker;
  void Function(PcmChunk)? _onChunk;
  int _sampleIndex = 0;

  @override
  bool get isRecording => _chunker != null;

  @override
  Future<bool> hasPermission() async => true;

  @override
  Future<void> start({required void Function(PcmChunk chunk) onChunk}) async {
    _onChunk = onChunk;
    _chunker = PcmChunker(
        chunkSeconds: _chunkSeconds, overlapSeconds: _overlapSeconds);
    _sampleIndex = 0;
    _timer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _feed(milliseconds: 100 * timeScale);
    });
  }

  void _feed({required int milliseconds}) {
    final chunker = _chunker;
    if (chunker == null) return;
    final samples = 16000 * milliseconds ~/ 1000;
    final data = ByteData(samples * 2);
    for (var i = 0; i < samples; i++) {
      final v = (sin(2 * pi * 220 * (_sampleIndex + i) / 16000) * 3000).round();
      data.setInt16(i * 2, v, Endian.little);
    }
    _sampleIndex += samples;
    for (final chunk in chunker.add(data.buffer.asUint8List())) {
      _onChunk?.call(chunk);
    }
  }

  @override
  Future<RecordingResult> stop() async {
    _timer?.cancel();
    _timer = null;
    final chunker = _chunker!;
    final tail = chunker.flush();
    if (tail != null) _onChunk?.call(tail);
    final result = RecordingResult(
      wavBytes: chunker.buildFullWav(),
      durationSeconds: chunker.totalSeconds,
      chunkCount: chunker.emittedCount,
    );
    _chunker = null;
    _onChunk = null;
    return result;
  }

  @override
  Future<void> dispose() async {
    _timer?.cancel();
  }
}

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/audio/pcm_chunker.dart';
import '../../core/audio/recorder_service.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/session.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 발표중 (와이어프레임 e1) — 실제 마이크 녹음 + 청크 파이프라인.
///
/// - 타이머는 클라이언트 권위 (spec A9)
/// - 녹음 중 60초+4초 겹침 WAV 청크를 순차 업로드 (spec §4.3.1)
/// - 발표 마치기 → 꼬리 청크 + 재생용 전체 파일 complete 업로드 → STT 폴링
class PresentingPage extends StatefulWidget {
  const PresentingPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<PresentingPage> createState() => _PresentingPageState();
}

enum _MicState { checking, denied, unsupported, recording }

class _PresentingPageState extends State<PresentingPage> {
  Session? _session;
  Timer? _timer;
  int _elapsedSeconds = 0;
  int _slide = 1;
  DateTime? _startedAt;
  bool _finishing = false;

  _MicState _mic = _MicState.checking;
  RecorderService? _recorder; // 실사용 중인 녹음기 (실물 또는 Fake)

  // 청크 업로드 직렬화 큐 (순서 보장 — infra 제약 2)
  Future<void> _uploadQueue = Future.value();
  int _chunksSent = 0;
  int _chunksFailed = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  Future<void> _bootstrap() async {
    final ctrl = context.read<SessionController>();
    final session =
        ctrl.byId(widget.sessionId) ?? await ctrl.refresh(widget.sessionId);
    if (!mounted) return;
    setState(() => _session = session);
    await _startRecording(context.read<RecorderService>());
  }

  Future<void> _startRecording(RecorderService recorder) async {
    try {
      if (!await recorder.hasPermission()) {
        if (mounted) setState(() => _mic = _MicState.denied);
        return;
      }
      await recorder.start(onChunk: _enqueueChunk);
    } catch (_) {
      // PCM 스트리밍 미지원 (구형 브라우저 등) → 파일 모드 안내 (spec §4.3.1 폴백)
      if (mounted) setState(() => _mic = _MicState.unsupported);
      return;
    }

    if (!mounted) {
      await recorder.stop();
      return;
    }
    _recorder = recorder;
    _startedAt = DateTime.now();
    unawaited(
        context.read<SessionRepository>().startRecording(widget.sessionId));
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _elapsedSeconds++);
    });
    setState(() => _mic = _MicState.recording);
  }

  /// 청크 업로드 — 실패해도 발표는 계속 (complete의 전체 파일이 안전망).
  void _enqueueChunk(PcmChunk chunk) {
    final repo = context.read<SessionRepository>();
    _uploadQueue = _uploadQueue.then((_) async {
      try {
        await repo.uploadRecordingChunk(widget.sessionId, chunk);
        if (mounted) setState(() => _chunksSent++);
      } catch (_) {
        if (mounted) setState(() => _chunksFailed++);
      }
    });
  }

  Future<void> _finish() async {
    final recorder = _recorder;
    if (recorder == null || _finishing) return;
    setState(() => _finishing = true);
    _timer?.cancel();

    try {
      final result = await recorder.stop();
      _recorder = null;
      await _uploadQueue; // 남은 청크 전송 완료 대기 (마지막 꼬리 포함)

      if (!mounted) return;
      await context.read<SessionRepository>().completeRecording(
            widget.sessionId,
            fileName: result.fileName,
            bytes: result.wavBytes,
            totalChunks: result.chunkCount,
            startedAt: _startedAt ?? DateTime.now(),
            endedAt: DateTime.now(),
            durationSeconds: result.durationSeconds,
          );
      if (mounted) {
        context.pushReplacement('/sessions/${widget.sessionId}/processing');
      }
    } catch (e) {
      if (mounted) {
        setState(() => _finishing = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('업로드 실패: $e — 다시 시도해주세요')));
      }
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    // 화면 이탈 시 마이크 해제 (녹음 데이터는 폐기 — 이어하기는 세션 상태 재조회로)
    final recorder = _recorder;
    if (recorder != null && recorder.isRecording) {
      unawaited(recorder.stop().then<void>((_) {}, onError: (_) {}));
    }
    super.dispose();
  }

  int get _limitSeconds => (_session?.timeLimitMinutes ?? 10) * 60;
  bool get _overtime => _elapsedSeconds > _limitSeconds;

  String _fmt(int s) =>
      '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: AppBackButton(
            fallbackLocation:
                _session != null ? '/teams/${_session!.teamId}' : '/'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: switch (_mic) {
            _MicState.checking =>
              const Center(child: CircularProgressIndicator()),
            _MicState.denied => _MicProblemView(
                icon: Icons.mic_off,
                title: '마이크 권한이 필요해요',
                message: '마이크 권한을 허용하지 않으면 실시간 녹음을 사용할 수 없어요.\n'
                    '권한을 허용하거나, 녹음 파일 업로드로 진행해주세요.',
                onRetry: () => _startRecording(context.read<RecorderService>()),
                actionLabel: '녹음 파일 업로드로 전환',
                onAction: () => context.pushReplacement(
                    '/sessions/${widget.sessionId}/upload-recording'),
                onFake: kDebugMode ? () => _startRecording(FakeRecorderService()) : null,
              ),
            _MicState.unsupported => _MicProblemView(
                icon: Icons.browser_not_supported,
                title: '이 브라우저는 실시간 녹음을 지원하지 않아요',
                message: '녹음 파일 업로드 모드를 이용해주세요.',
                actionLabel: '녹음 파일 업로드로 전환',
                onAction: () => context.pushReplacement(
                    '/sessions/${widget.sessionId}/upload-recording'),
                onFake: kDebugMode ? () => _startRecording(FakeRecorderService()) : null,
              ),
            _MicState.recording => _recordingView(),
          },
        ),
      ),
    );
  }

  Widget _recordingView() {
    final title = _session?.name ?? '발표';
    return Column(
      children: [
        const Spacer(),
        Text(title,
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 20),
        AspectRatio(
          aspectRatio: 16 / 10,
          child: Container(
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(8),
            ),
            alignment: Alignment.center,
            child: Text('PDF 슬라이드 ($_slide)',
                style: const TextStyle(color: AppColors.textSecondary)),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: TextButton(
                style: TextButton.styleFrom(
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.textPrimary),
                onPressed: _slide > 1 ? () => setState(() => _slide--) : null,
                child: const Text('이전 슬라이드'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextButton(
                style: TextButton.styleFrom(
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.textPrimary),
                onPressed: () => setState(() => _slide++),
                child: const Text('다음 슬라이드'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 28),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircleAvatar(radius: 5, backgroundColor: AppColors.danger),
            const SizedBox(width: 8),
            const Text('발표 녹음 중',
                style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
            if (_chunksSent > 0) ...[
              const SizedBox(width: 10),
              Text('· 전송된 청크 $_chunksSent개',
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.textSecondary)),
            ],
            if (_chunksFailed > 0)
              Text(' (실패 $_chunksFailed — 종료 시 전체 파일로 복구)',
                  style:
                      const TextStyle(fontSize: 11, color: AppColors.danger)),
          ],
        ),
        const SizedBox(height: 8),
        Text('${_fmt(_elapsedSeconds)} / ${_fmt(_limitSeconds)}',
            style: TextStyle(
                fontSize: 30,
                fontWeight: FontWeight.w800,
                color: _overtime ? AppColors.danger : AppColors.accent)),
        if (_overtime)
          Text('제한시간 초과 +${_fmt(_elapsedSeconds - _limitSeconds)}',
              style: const TextStyle(fontSize: 12, color: AppColors.danger)),
        const Spacer(flex: 2),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.accent,
              shape:
                  RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: _finishing ? null : _finish,
            child: Text(_finishing ? '마무리 업로드 중…' : '발표 마치기',
                style:
                    const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

/// 권한 거부/미지원 안내 (와이어프레임 j1 요소의 인라인 버전 — 전체 화면은 Step 3).
class _MicProblemView extends StatelessWidget {
  const _MicProblemView({
    required this.icon,
    required this.title,
    required this.message,
    this.onRetry,
    this.actionLabel,
    this.onAction,
    this.onFake,
  });

  final IconData icon;
  final String title;
  final String message;
  final VoidCallback? onRetry;
  final String? actionLabel;
  final VoidCallback? onAction;
  final VoidCallback? onFake;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 56, color: AppColors.danger),
          const SizedBox(height: 16),
          Text(title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary)),
          const SizedBox(height: 24),
          if (onRetry != null)
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: AppColors.accent),
              onPressed: onRetry,
              child: const Text('다시 시도'),
            ),
          if (onAction != null) ...[
            if (onRetry != null) const SizedBox(height: 10),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
              onPressed: onAction,
              child: Text(actionLabel ?? '계속'),
            ),
          ],
          if (onFake != null) ...[
            const SizedBox(height: 8),
            TextButton(
              onPressed: onFake,
              child: const Text('(개발용) 가짜 녹음으로 진행',
                  style: TextStyle(fontSize: 12, color: AppColors.hint)),
            ),
          ],
        ],
      ),
    );
  }
}

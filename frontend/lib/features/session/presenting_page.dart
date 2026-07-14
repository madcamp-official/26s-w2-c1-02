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

/// 발표중 (와이어프레임 e1) — 실제 마이크 녹음 → 일괄 업로드.
///
/// - 타이머는 클라이언트 권위 (spec A9)
/// - 녹음 중 [PcmChunker]로 전체 WAV만 축적 (청크 전송은 하지 않음)
/// - 발표 마치기 → 전체 WAV를 `POST /recording` 단발 업로드 → STT 폴링
///
/// §0.8 합의: 데모까지는 일괄 업로드(A8) 하나로 수렴한다. 실시간 청크 파이프라인
/// (`/recording/chunks`·`/recording/complete`)은 후순위 순수 최적화로 §4.3.1에
/// draft 보존 — 리포지토리·Mock 계약은 유지하되 이 화면에서는 호출하지 않는다.
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
    // §0.8: 실시간 `recording/start` 표시는 청크 파이프라인용이었으므로 호출하지 않는다.
    // 일괄 업로드는 `POST /recording`이 draft → transcribing 전이를 직접 수행.
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _elapsedSeconds++);
    });
    setState(() => _mic = _MicState.recording);
  }

  /// §0.8: 일괄 업로드로 수렴 — 청크는 전송하지 않는다(no-op). [PcmChunker]는
  /// 전체 WAV 축적용으로만 돌고, onChunk 콜백은 청크 계약 revival용으로 남겨둔다.
  /// (§4.3.1을 살릴 때 여기서 uploadRecordingChunk 직렬 큐를 복구)
  void _enqueueChunk(PcmChunk chunk) {}

  Future<void> _finish() async {
    final recorder = _recorder;
    if (recorder == null || _finishing) return;
    setState(() => _finishing = true);
    _timer?.cancel();

    try {
      final result = await recorder.stop();
      _recorder = null;

      if (!mounted) return;
      // §0.8: 실시간 모드도 일괄 업로드로 수렴 — 전체 WAV 1회 전송.
      await context.read<SessionRepository>().uploadRecording(
            widget.sessionId,
            fileName: result.fileName,
            bytes: result.wavBytes,
            startedAt: _startedAt ?? DateTime.now(),
            endedAt: DateTime.now(),
            durationSeconds: result.durationSeconds.round(),
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

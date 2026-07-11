import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/session.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 발표중 (와이어프레임 e1).
/// 타이머는 클라이언트 권위(spec A9). 실제 마이크 녹음은 Step 2 —
/// 지금은 종료 시 mock 오디오 바이트를 업로드해 STT 파이프라인을 태운다.
class PresentingPage extends StatefulWidget {
  const PresentingPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<PresentingPage> createState() => _PresentingPageState();
}

class _PresentingPageState extends State<PresentingPage> {
  Session? _session;
  Timer? _timer;
  int _elapsedSeconds = 0;
  int _slide = 1;
  DateTime? _startedAt;
  bool _finishing = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final ctrl = context.read<SessionController>();
      final session =
          ctrl.byId(widget.sessionId) ?? await ctrl.refresh(widget.sessionId);
      if (!mounted) return;
      setState(() => _session = session);
      // 발표 시작 = 녹음 시작 (recording/start는 이어하기용 마커)
      unawaited(
          context.read<SessionRepository>().startRecording(widget.sessionId));
      _startedAt = DateTime.now();
      _timer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() => _elapsedSeconds++);
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  int get _limitSeconds => (_session?.timeLimitMinutes ?? 10) * 60;
  bool get _overtime => _elapsedSeconds > _limitSeconds;

  String _fmt(int s) =>
      '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';

  Future<void> _finish() async {
    _timer?.cancel();
    setState(() => _finishing = true);
    // Step 2에서 실제 녹음 파일로 교체. 지금은 mock 바이트 → STT 시작(202).
    await context.read<SessionRepository>().uploadRecording(
          widget.sessionId,
          fileName: 'recording.m4a',
          bytes: utf8.encode('mock-audio'),
          startedAt: _startedAt ?? DateTime.now(),
          endedAt: DateTime.now(),
          durationSeconds: _elapsedSeconds,
        );
    if (mounted) {
      context.pushReplacement('/sessions/${widget.sessionId}/processing');
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = _session?.name ?? '발표';
    return Scaffold(
      appBar: AppBar(
        leading: AppBackButton(
            fallbackLocation:
                _session != null ? '/teams/${_session!.teamId}' : '/'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: Column(
            children: [
              const Spacer(),
              Text(title,
                  style: const TextStyle(
                      fontSize: 22, fontWeight: FontWeight.w800)),
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
                      onPressed:
                          _slide > 1 ? () => setState(() => _slide--) : null,
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
                      style: TextStyle(
                          fontSize: 13, color: AppColors.textSecondary)),
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
                    style: const TextStyle(
                        fontSize: 12, color: AppColors.danger)),
              const Spacer(flex: 2),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: _finishing ? null : _finish,
                  child: Text(_finishing ? '업로드 중…' : '발표 마치기',
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w800)),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}

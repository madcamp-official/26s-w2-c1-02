import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/speech.dart';
import '../../state/speech_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 발표중 화면 (Figma: 발표중 화면 / 제한시간 초과 / 질의응답 여부 확인).
///
/// 기능 명세 5): 페이지 진입(=발표 시작) 시각부터 타이머(녹음) 시작,
/// "발표 마치기"를 누르면 발표 종료 후 질의응답 여부를 확인한다.
class PresentingPage extends StatefulWidget {
  const PresentingPage({super.key, required this.speechId});
  final String speechId;

  @override
  State<PresentingPage> createState() => _PresentingPageState();
}

enum _Phase { presenting, confirmQna }

class _PresentingPageState extends State<PresentingPage> {
  Speech? _speech;
  Timer? _timer;
  int _elapsedSeconds = 0;
  int _slide = 1;
  _Phase _phase = _Phase.presenting;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final s =
          await context.read<SpeechController>().ensureLoaded(widget.speechId);
      if (!mounted) return;
      setState(() => _speech = s);
      _startTimer(); // 발표 시작 = 녹음 시작(목).
    });
  }

  void _startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _elapsedSeconds++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  int get _limitSeconds => (_speech?.durationMinutes ?? 5) * 60;
  bool get _overtime => _elapsedSeconds > _limitSeconds;

  String get _elapsedLabel {
    final m = (_elapsedSeconds ~/ 60).toString().padLeft(2, '0');
    final s = (_elapsedSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  void _finish() {
    _timer?.cancel();
    setState(() => _phase = _Phase.confirmQna);
  }

  @override
  Widget build(BuildContext context) {
    final title = _speech?.name ?? 'speech';
    final teamFallback = _speech != null ? '/teams/${_speech!.teamId}' : '/';
    return Scaffold(
      appBar: AppBar(leading: AppBackButton(fallbackLocation: teamFallback)),
      body: SafeArea(
        child: ResponsivePage(
          child: _phase == _Phase.presenting
              ? _buildPresenting(title)
              : _buildConfirm(title),
        ),
      ),
    );
  }

  Widget _buildPresenting(String title) {
    return Column(
      children: [
        const Spacer(flex: 2),
        Text(title,
            style:
                const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 20),
        // PDF 슬라이드 자리
        AspectRatio(
          aspectRatio: 16 / 11,
          child: Container(
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(6),
            ),
            alignment: Alignment.center,
            child: Text('pdf 슬라이드 화면 ($_slide)',
                style: const TextStyle(color: AppColors.textSecondary)),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _SlideButton(
                label: '이전 슬라이드',
                onTap: _slide > 1 ? () => setState(() => _slide--) : null,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _SlideButton(
                label: '다음 슬라이드',
                onTap: () => setState(() => _slide++),
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        Text(
          _overtime ? _elapsedLabel : '발표중…  $_elapsedLabel',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w800,
            color: _overtime ? AppColors.danger : AppColors.accent,
          ),
        ),
        if (_overtime)
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Text('발표 제한시간을 넘겼어요',
                style: TextStyle(color: AppColors.danger, fontSize: 12)),
          ),
        const Spacer(flex: 3),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.accent,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
            onPressed: _finish,
            child: const Text('발표 마치기',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _buildConfirm(String title) {
    return Column(
      children: [
        const Spacer(flex: 2),
        Text(title,
            style:
                const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 16),
        Text(_elapsedLabel,
            style: TextStyle(
                fontSize: 26,
                fontWeight: FontWeight.w800,
                color: _overtime ? AppColors.danger : AppColors.accent)),
        const SizedBox(height: 20),
        const Text('발표를 마쳤어요.',
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w800,
                color: AppColors.accent)),
        const Text('질의응답으로 넘어갈까요?',
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w800,
                color: AppColors.accent)),
        const Spacer(flex: 3),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.accent,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
            onPressed: () =>
                context.pushReplacement('/speeches/${widget.speechId}/qna'),
            child: const Text('질의응답으로 넘어가기',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.textPrimary,
              side: const BorderSide(color: AppColors.border),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
            onPressed: () {
              // 질의응답 생략 → 이전 화면(팀)으로.
              if (context.canPop()) {
                context.pop();
              } else {
                context.go('/');
              }
            },
            child: const Text('안 할게요',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _SlideButton extends StatelessWidget {
  const _SlideButton({required this.label, this.onTap});
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: AppColors.surfaceAlt,
          foregroundColor: AppColors.textPrimary,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
        onPressed: onTap,
        child: Text(label),
      ),
    );
  }
}

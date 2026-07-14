import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/audio/audio_player_service.dart';
import '../../core/audio/recorder_service.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/qna.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/mic_permission_view.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// 질의응답 (와이어프레임 06 f1~f3) — 프로젝트의 심장.
///
/// GET /qna 폴링이 단일 소스(spec §4.4). 질문별로:
///   TTS 재생 → (완료 시) 답변 시작 대기(30초 카운트다운) → "답변 시작하기"로
///   녹음 → "답변 완료" → 202 제출 → 폴링으로 answer ready·꼬리질문 등장/다음
///   질문 이동/종료 확정.
/// 30초 안에 답변을 시작하지 않으면 클라이언트가 자동 pass 처리한다
/// (spec §4.4 A12 — 답변 시간초과 → 자동 다음).
class QnaPage extends StatefulWidget {
  const QnaPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<QnaPage> createState() => _QnaPageState();
}

class _QnaPageState extends State<QnaPage> {
  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<QnaState>(
            fetch: () => repo.getQna(widget.sessionId),
            // 종료(ended) 또는 생성 실패(failed)면 폴링을 멈춘다. 그 외(생성 중·진행
            // 중)는 계속 폴링한다.
            isDone: (q) =>
                q.status == QnaStatus.ended || q.status == QnaStatus.failed,
            onDone: (q) {
              // 종료만 결과 화면으로. 실패는 builder가 재생성 안내를 띄운다.
              if (q.status != QnaStatus.ended) return;
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (context.mounted) {
                  context.pushReplacement(
                      '/sessions/${widget.sessionId}/qna/complete');
                }
              });
            },
            builder: (context, snap, retry) {
              final qna = snap.data;
              if (snap.error != null) {
                return _ErrorRetry(error: snap.error!, onRetry: retry);
              }
              // 질문 생성 실패 — 같은 폴링 재시도가 아니라 생성을 다시 접수해야 한다
              // (세션 failed → generating_questions 재시도 경로). 이후 폴링 재개.
              if (qna != null && qna.status == QnaStatus.failed) {
                return _GenerationFailed(
                  onRetry: () async {
                    await repo.generateQna(widget.sessionId);
                    retry();
                  },
                );
              }
              if (qna == null || qna.questions.isEmpty) {
                return const _GeneratingView();
              }
              final current = qna.currentQuestion ?? qna.questions.first;
              // question.id로 keying → 다음/꼬리질문으로 넘어가면 재생·녹음
              // 생명주기가 새로 시작(자동 TTS 재생)된다.
              return _QuestionView(
                key: ValueKey(current.id),
                sessionId: widget.sessionId,
                qna: qna,
                question: current,
              );
            },
          ),
        ),
      ),
    );
  }
}

class _GeneratingView extends StatelessWidget {
  const _GeneratingView();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        CircularProgressIndicator(color: AppColors.accent),
        SizedBox(height: 24),
        Text('AI 청중이 질문을 만들고 있어요…',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        SizedBox(height: 8),
        Text('슬라이드와 발표 내용을 분석 중이에요.',
            style: TextStyle(color: AppColors.textSecondary)),
      ],
    );
  }
}

/// 답변 상호작용 단계.
enum _Phase {
  waitingTts, // 질문 음성 합성 대기
  playing, // 질문 음성 재생 중
  awaitingStart, // 재생 완료 → 답변 시작 대기(30초 카운트다운)
  recording, // 답변 녹음 중
  submitting, // 답변 업로드 중
  submitFailed, // 업로드 실패 — 보관한 녹음으로 재제출 가능
  done, // 제출 완료(이후는 폴링이 상태 표시) 또는 재방문
  micDenied, // 마이크 권한 거부/미지원
}

class _QuestionView extends StatefulWidget {
  const _QuestionView({
    super.key,
    required this.sessionId,
    required this.qna,
    required this.question,
  });

  final String sessionId;
  final QnaState qna;
  final Question question;

  @override
  State<_QuestionView> createState() => _QuestionViewState();
}

class _QuestionViewState extends State<_QuestionView> {
  /// 질문 후 "답변 시작까지"의 제한시간. 초과 시 클라이언트가 자동 pass
  /// 처리한다(spec §4.4 A12 — 답변 시간초과 → 자동 다음).
  static const int _answerStartLimitSeconds = 30;

  late final AudioPlayerService _player = context.read<AudioPlayerService>();
  late final SessionRepository _repo = context.read<SessionRepository>();

  RecorderService? _recorder;
  _Phase _phase = _Phase.waitingTts;

  /// 제출 대기 중인 녹음 바이트 — 업로드 실패 시 재녹음 없이 재제출용.
  List<int>? _answerBytes;

  /// 제출 대기 중인 녹음 길이(초) — 답변 업로드의 duration_seconds 폼 필드.
  int _answerDuration = 0;

  /// 답변 시작 대기 카운트다운.
  Timer? _waitTimer;
  int _waitElapsed = 0;

  Question get _q => widget.question;

  @override
  void initState() {
    super.initState();
    final answer = _q.answer;
    if (answer != null && answer.status != AnswerStatus.pending) {
      // 이미 제출된 질문으로 재진입 — 폴링 상태만 보여준다.
      _phase = _Phase.done;
    } else {
      _maybeAutoPlay();
    }
  }

  @override
  void didUpdateWidget(_QuestionView old) {
    super.didUpdateWidget(old);
    // 질문 생성 직후엔 TTS가 아직 queued일 수 있다. 폴링으로 ready가 되면 재생.
    if (_phase == _Phase.waitingTts && _q.tts.status == AsyncStatus.ready) {
      _playTts();
    }
  }

  void _maybeAutoPlay() {
    if (_q.tts.status == AsyncStatus.ready) {
      _playTts();
    } else {
      _phase = _Phase.waitingTts;
    }
  }

  Future<void> _playTts() async {
    final url = _q.tts.audioUrl;
    if (url == null) {
      // 음성 URL이 없으면 재생 없이 바로 답변 시작 대기로.
      _awaitAnswerStart();
      return;
    }
    setState(() => _phase = _Phase.playing);
    try {
      await _player.play(url);
    } catch (e) {
      // 재생 실패(예: iOS -1002 unsupported URL, 네트워크 오류)에도 답변 흐름은
      // 막히면 안 된다. 음성 없이 질문 텍스트로 답변을 이어가게 한다.
      if (kDebugMode) debugPrint('TTS 재생 실패: $e');
      if (mounted && _phase == _Phase.playing) {
        _snack('질문 음성을 재생하지 못했어요. 질문을 읽고 답변해주세요.');
      }
    }
    if (!mounted || _phase != _Phase.playing) return; // 중단/다시듣기/화면 이탈
    _awaitAnswerStart(); // 재생 완료(또는 실패) → 답변 시작 대기(30초)
  }

  /// 질문 재생 후 30초 카운트다운. 사용자가 답변을 시작하면 멈추고,
  /// 시간 내에 시작하지 않으면 자동 pass (spec §4.4 A12).
  void _awaitAnswerStart() {
    _waitTimer?.cancel();
    _waitElapsed = 0;
    setState(() => _phase = _Phase.awaitingStart);
    _waitTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      setState(() => _waitElapsed++);
      if (_waitElapsed >= _answerStartLimitSeconds) {
        _waitTimer?.cancel();
        _autoPassOnTimeout();
      }
    });
  }

  Future<void> _autoPassOnTimeout() async {
    if (_phase != _Phase.awaitingStart) return;
    _snack('답변 시작 시간(30초)이 지나 자동으로 넘어갔어요');
    await _pass(reason: 'timeout');
  }

  Future<void> _startRecording([RecorderService? override]) async {
    _waitTimer?.cancel(); // 답변 시작 → 대기 카운트다운 종료
    final recorder = override ?? context.read<RecorderService>();
    try {
      if (!await recorder.hasPermission()) {
        if (mounted) setState(() => _phase = _Phase.micDenied);
        return;
      }
      await recorder.start(onChunk: (_) {}); // 답변은 단발 — 청크는 버린다
    } catch (_) {
      if (mounted) setState(() => _phase = _Phase.micDenied);
      return;
    }
    if (!mounted) {
      await recorder.stop();
      return;
    }
    _recorder = recorder;
    setState(() => _phase = _Phase.recording);
  }

  /// 녹음 종료 → 바이트 보관 → 업로드. 녹음은 업로드 성공 전까지 버리지 않는다.
  Future<void> _submitAnswer() async {
    final recorder = _recorder;
    if (_phase != _Phase.recording || recorder == null) return;
    setState(() => _phase = _Phase.submitting);
    try {
      final result = await recorder.stop();
      _recorder = null;
      _answerBytes = result.wavBytes; // 유실 방지: 업로드 성공 전까지 보관
      _answerDuration = result.durationSeconds.round();
    } catch (e) {
      _recorder = null;
      _answerBytes = null;
      if (mounted) {
        setState(() => _phase = _Phase.submitFailed);
        _snack('녹음 종료 실패: $e');
      }
      return;
    }
    await _uploadAnswer();
  }

  /// 보관한 녹음 바이트로 202 제출. 실패 시 submitFailed로 남아 재제출 가능.
  Future<void> _uploadAnswer() async {
    final bytes = _answerBytes;
    if (bytes == null) return;
    setState(() => _phase = _Phase.submitting);
    try {
      await _repo.submitAnswer(
        widget.sessionId,
        _q.id,
        fileName: 'answer.wav',
        bytes: bytes,
        durationSeconds: _answerDuration,
      );
      _answerBytes = null;
      if (mounted) setState(() => _phase = _Phase.done);
    } catch (e) {
      if (mounted) {
        setState(() => _phase = _Phase.submitFailed);
        _snack('답변 제출 실패: $e — 다시 제출해주세요');
      }
    }
  }

  /// 실패한 녹음을 버리고 처음부터 다시 녹음.
  Future<void> _reRecord() async {
    _answerBytes = null;
    await _startRecording();
  }

  Future<void> _pass({String reason = 'user'}) async {
    _waitTimer?.cancel();
    await _stopEverything();
    await _repo.passQuestion(widget.sessionId, _q.id, reason: reason);
  }

  Future<void> _end() async {
    _waitTimer?.cancel();
    await _stopEverything();
    await _repo.endQna(widget.sessionId);
  }

  Future<void> _stopEverything() async {
    await _player.stop();
    final recorder = _recorder;
    _recorder = null;
    if (recorder != null && recorder.isRecording) {
      await recorder.stop();
    }
  }

  void _snack(String msg) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(msg)));

  @override
  void dispose() {
    _waitTimer?.cancel();
    unawaited(_player.stop());
    final recorder = _recorder;
    if (recorder != null && recorder.isRecording) {
      unawaited(recorder.stop().then<void>((_) {}, onError: (_) {}));
    }
    super.dispose();
  }

  String _fmt(int s) =>
      '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final primaries = widget.qna.questions.where((q) => !q.isFollowUp).length;

    return Column(
      children: [
        Row(
          children: [
            const Spacer(),
            Text('Q${_q.order}${_q.isFollowUp ? '-꼬리' : ''} / $primaries',
                style: const TextStyle(
                    fontWeight: FontWeight.w700, color: AppColors.accent)),
          ],
        ),
        const Spacer(),
        if (_q.isFollowUp) const _FollowUpBadge(),
        const SizedBox(height: 12),
        CircleAvatar(
          radius: 40,
          backgroundColor: AppColors.accent.withValues(alpha: 0.15),
          child: Text(_q.persona.label.characters.first,
              style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: AppColors.accent)),
        ),
        const SizedBox(height: 8),
        Text(_q.persona.professorLabel,
            style: const TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 16),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Text('"${_q.text}"',
              style: const TextStyle(fontSize: 15, height: 1.5)),
        ),
        const SizedBox(height: 8),
        if (!_q.evidence.isEmpty) _EvidenceBadge(evidence: _q.evidence),
        const Spacer(flex: 2),
        _interaction(),
        const SizedBox(height: 12),
        if (_phase != _Phase.micDenied) _bottomActions(),
        const SizedBox(height: 16),
      ],
    );
  }

  /// 단계별 중앙 상호작용 영역.
  Widget _interaction() {
    switch (_phase) {
      case _Phase.micDenied:
        return MicPermissionView(
          title: '마이크 권한이 필요해요',
          message: '답변 녹음을 위해 마이크 접근을 허용해주세요.',
          onRetry: () => _startRecording(),
          onFake: kDebugMode
              ? () => _startRecording(FakeRecorderService())
              : null,
        );
      case _Phase.waitingTts:
        if (_q.tts.status == AsyncStatus.failed) {
          return _center(
            danger: true,
            label: '질문 음성 생성에 실패했어요',
            child: OutlinedButton(
              onPressed: () => _startRecording(),
              child: const Text('음성 없이 답변하기'),
            ),
          );
        }
        return _center(
            label: '질문 음성을 준비하고 있어요…', spinner: true);
      case _Phase.playing:
        return _center(label: '질문을 듣고 있어요', icon: Icons.volume_up);
      case _Phase.awaitingStart:
        final remaining = _answerStartLimitSeconds - _waitElapsed;
        final low = remaining <= 10;
        return Column(
          children: [
            const Text('준비되면 답변을 시작하세요',
                style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
            const SizedBox(height: 6),
            Text('답변 시작까지 ${_fmt(remaining < 0 ? 0 : remaining)}',
                style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w800,
                    color: low ? AppColors.danger : AppColors.accent)),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: () => _startRecording(),
                icon: const Icon(Icons.mic),
                label: const Text('답변 시작하기',
                    style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ),
          ],
        );
      case _Phase.recording:
        return Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const CircleAvatar(radius: 5, backgroundColor: AppColors.danger),
                const SizedBox(width: 8),
                const Text('답변 녹음 중',
                    style: TextStyle(
                        fontSize: 13, color: AppColors.textSecondary)),
              ],
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                onPressed: _submitAnswer,
                child: const Text('답변 완료',
                    style: TextStyle(fontWeight: FontWeight.w800)),
              ),
            ),
          ],
        );
      case _Phase.submitting:
        return _center(label: '답변을 제출하고 있어요…', spinner: true);
      case _Phase.submitFailed:
        final hasBytes = _answerBytes != null;
        return Column(
          children: [
            const Icon(Icons.cloud_off, color: AppColors.danger),
            const SizedBox(height: 8),
            const Text('답변 제출에 실패했어요',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800)),
            const SizedBox(height: 4),
            Text(
                hasBytes
                    ? '녹음은 저장돼 있어요. 네트워크 확인 후 다시 제출해주세요.'
                    : '다시 녹음해주세요.',
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            const SizedBox(height: 12),
            if (hasBytes)
              SizedBox(
                width: double.infinity,
                height: 54,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: _uploadAnswer,
                  child: const Text('다시 제출',
                      style: TextStyle(fontWeight: FontWeight.w800)),
                ),
              ),
            const SizedBox(height: 6),
            TextButton.icon(
              onPressed: _reRecord,
              icon: const Icon(Icons.mic, size: 16),
              label: const Text('다시 녹음'),
            ),
          ],
        );
      case _Phase.done:
        return _AnswerStatus(answer: _q.answer);
    }
  }

  Widget _bottomActions() {
    final busy = _phase == _Phase.submitting;
    return Row(
      children: [
        Expanded(
          child: TextButton(
            style: TextButton.styleFrom(
                backgroundColor: AppColors.surface,
                foregroundColor: AppColors.textPrimary),
            onPressed: (busy || _phase == _Phase.done) ? null : _pass,
            child: const Text('모르겠어요 · 패스'),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TextButton(
            style: TextButton.styleFrom(
                backgroundColor: AppColors.surface,
                foregroundColor: AppColors.danger),
            onPressed: busy ? null : _end,
            child: const Text('질의응답 마치기'),
          ),
        ),
      ],
    );
  }

  Widget _center({
    required String label,
    bool spinner = false,
    bool danger = false,
    IconData? icon,
    Widget? child,
  }) {
    return Column(
      children: [
        if (spinner)
          const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: AppColors.accent)),
        if (icon != null) Icon(icon, color: AppColors.accent),
        const SizedBox(height: 8),
        Text(label,
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 13,
                color: danger ? AppColors.danger : AppColors.textSecondary)),
        if (child != null) ...[const SizedBox(height: 4), child],
      ],
    );
  }
}

class _FollowUpBadge extends StatelessWidget {
  const _FollowUpBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
      ),
      child: const Text('꼬리질문',
          style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.accent)),
    );
  }
}

class _EvidenceBadge extends StatelessWidget {
  const _EvidenceBadge({required this.evidence});
  final Evidence evidence;

  @override
  Widget build(BuildContext context) {
    final slides = evidence.slides.map((s) => '슬라이드 $s').join(', ');
    final refs = evidence.transcriptRefs.map((t) => '발표 $t').join(', ');
    final sep = evidence.slides.isNotEmpty && evidence.transcriptRefs.isNotEmpty
        ? ' · '
        : '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text('근거: $slides$sep$refs',
          style: const TextStyle(fontSize: 11.5, color: AppColors.accent)),
    );
  }
}

/// 제출 후 폴링이 확정하는 답변 상태 표시.
class _AnswerStatus extends StatelessWidget {
  const _AnswerStatus({required this.answer});
  final AnswerInfo? answer;

  @override
  Widget build(BuildContext context) {
    final a = answer;
    final label = switch (a?.status) {
      AnswerStatus.processing =>
        '답변을 텍스트로 변환하고 있어요…'
            '${a?.followUpStatus == FollowUpStatus.pending ? ' (꼬리질문 판정 대기)' : ''}',
      AnswerStatus.ready => a?.followUpStatus == FollowUpStatus.pending
          ? '꼬리질문 여부를 판단하고 있어요…'
          : '답변 완료${a?.text != null ? ': ${a!.text}' : ''}',
      AnswerStatus.failed => '답변 변환 실패 — 다시 제출해주세요',
      _ => '답변을 제출했어요',
    };
    final danger = a?.status == AnswerStatus.failed;
    return Column(
      children: [
        if (a?.status != AnswerStatus.failed)
          const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: AppColors.accent)),
        const SizedBox(height: 8),
        Text(label,
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 12.5,
                color: danger ? AppColors.danger : AppColors.textSecondary)),
      ],
    );
  }
}

/// 질문 생성 실패 안내 — 폴링 재시도가 아니라 생성을 다시 접수한다.
class _GenerationFailed extends StatefulWidget {
  const _GenerationFailed({required this.onRetry});

  /// generateQna 재접수 후 폴링을 재개한다. 완료까지 await.
  final Future<void> Function() onRetry;

  @override
  State<_GenerationFailed> createState() => _GenerationFailedState();
}

class _GenerationFailedState extends State<_GenerationFailed> {
  bool _busy = false;

  Future<void> _retry() async {
    if (_busy) return; // 중복 접수 방지 (재접수 시 409 QNA_ALREADY_STARTED)
    setState(() => _busy = true);
    try {
      await widget.onRetry();
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('다시 생성하지 못했어요: $e')));
      }
    }
    // 성공하면 폴링이 재개되며 이 위젯은 곧 생성 중 화면으로 교체된다.
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.error_outline, size: 48, color: AppColors.danger),
        const SizedBox(height: 12),
        const Text('질문 생성에 실패했어요',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        const Text('AI 청중 응답이 지연되거나 실패했어요. 다시 시도해주세요.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textSecondary)),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _retry,
          child: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Colors.white))
              : const Text('다시 생성'),
        ),
      ],
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.error_outline, size: 48, color: AppColors.danger),
        const SizedBox(height: 12),
        Text('$error', textAlign: TextAlign.center),
        const SizedBox(height: 12),
        FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
      ],
    );
  }
}

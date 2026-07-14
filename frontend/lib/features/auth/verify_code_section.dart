import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';

/// 6자리 인증코드 입력 섹션 — 가입 페이지 2단계와 인증 페이지(로그인 403 경로) 공용.
///
/// 서버 정책(email-verification-plan §4-2)을 그대로 안내·처리한다:
/// - 코드는 발송 후 **10분 만료**, **5회 오입력 시 소진** → 둘 다 CODE_EXPIRED로 옴
/// - 재발송은 **60초 쿨다운** — 429의 retry_after_seconds를 받으면 그 값으로 표시
/// - 6자리 채우면 자동 제출, INVALID_CODE는 입력 초기화 + 흔들림 피드백
class VerifyCodeSection extends StatefulWidget {
  const VerifyCodeSection({
    super.key,
    required this.email,
    required this.onVerified,
    this.sendOnInit = false,
  });

  final String email;

  /// verify 200 직후 호출 — 화면 이동(로그인 등)은 호출자 몫.
  final VoidCallback onVerified;

  /// true면 진입 즉시 코드 재발송 (로그인 403 경로 — 이전 코드는 10분 만료라 새로 필요).
  final bool sendOnInit;

  @override
  State<VerifyCodeSection> createState() => _VerifyCodeSectionState();
}

class _VerifyCodeSectionState extends State<VerifyCodeSection>
    with SingleTickerProviderStateMixin {
  static const _resendCooldown = 60; // §4-2: 재발송 60초 쿨다운

  final _code = TextEditingController();
  bool _submitting = false;
  bool _highlightResend = false; // CODE_EXPIRED(만료·5회 소진) 시 재발송 강조

  Timer? _cooldownTimer;
  int _cooldownLeft = 0;

  // INVALID_CODE 흔들림 피드백 (§8-3)
  late final AnimationController _shake = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 400));

  @override
  void initState() {
    super.initState();
    if (widget.sendOnInit) {
      _resend();
    } else {
      // 방금 발송된 코드(가입 부수효과)가 살아 있으므로 재발송만 잠근다.
      _startCooldown(_resendCooldown);
    }
  }

  @override
  void dispose() {
    _code.dispose();
    _cooldownTimer?.cancel();
    _shake.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting || _code.text.length != 6) return;
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().verifyEmail(widget.email, _code.text);
      if (!mounted) return;
      widget.onVerified();
    } on ApiException catch (e) {
      if (!mounted) return;
      switch (e.code) {
        case 'INVALID_CODE':
          _snack('코드가 올바르지 않아요');
          _code.clear();
          _shake.forward(from: 0);
        case 'CODE_EXPIRED': // 10분 경과 또는 5회 오입력 소진 (§4-2)
          _snack('코드가 만료됐어요 (10분 경과 또는 5회 초과). 재발송해주세요');
          _code.clear();
          setState(() => _highlightResend = true);
        default:
          _snack(e.message ?? '인증에 실패했어요. 잠시 후 다시 시도해주세요');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _resend() async {
    try {
      await context
          .read<AuthController>()
          .requestEmailVerification(widget.email);
      if (!mounted) return;
      _snack('인증코드를 다시 보냈어요. 메일함(스팸함 포함)을 확인해주세요');
      setState(() => _highlightResend = false);
      _startCooldown(_resendCooldown);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 429) {
        // 서버가 남은 쿨다운을 알려주면 그 값으로 표시 (§5-1 retry_after_seconds)
        final retryAfter =
            (e.details?['retry_after_seconds'] as num?)?.toInt() ??
                _resendCooldown;
        _snack('잠시 후 다시 시도해주세요');
        _startCooldown(retryAfter);
      } else {
        _snack(e.message ?? '재발송에 실패했어요');
      }
    }
  }

  void _startCooldown(int seconds) {
    _cooldownTimer?.cancel();
    setState(() => _cooldownLeft = seconds);
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _cooldownLeft -= 1);
      if (_cooldownLeft <= 0) t.cancel();
    });
  }

  void _snack(String msg) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(msg)));

  @override
  Widget build(BuildContext context) {
    final cooling = _cooldownLeft > 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('${widget.email}로\n인증코드를 보냈어요',
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 18, fontWeight: FontWeight.w700, height: 1.4)),
        const SizedBox(height: 8),
        const Text('10분 안에 입력해주세요 · 5회 틀리면 재발송이 필요해요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
        const SizedBox(height: 32),
        AnimatedBuilder(
          animation: _shake,
          builder: (context, child) => Transform.translate(
            // 감쇠 사인파 — 좌우로 4회 흔들리며 잦아든다
            offset:
                Offset(sin(_shake.value * pi * 4) * 8 * (1 - _shake.value), 0),
            child: child,
          ),
          child: TextField(
            controller: _code,
            enabled: !_submitting,
            autofocus: true,
            keyboardType: TextInputType.number,
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(6),
            ],
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 32, fontWeight: FontWeight.w700, letterSpacing: 12),
            decoration: const InputDecoration(
              hintText: '······',
              counterText: '',
            ),
            onChanged: (v) {
              if (v.length == 6) _submit(); // 6자리 채우면 자동 제출
              setState(() {}); // 인증하기 버튼 활성화 갱신
            },
          ),
        ),
        const SizedBox(height: 24),
        SizedBox(
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primary,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: _submitting || _code.text.length != 6 ? null : _submit,
            child: Text(_submitting ? '확인 중…' : '인증하기'),
          ),
        ),
        const SizedBox(height: 12),
        TextButton(
          style: TextButton.styleFrom(
            foregroundColor:
                _highlightResend ? AppColors.primary : AppColors.textSecondary,
          ),
          onPressed: cooling ? null : _resend,
          child: Text(
              cooling ? '재발송 ($_cooldownLeft초 후 가능)' : '코드가 안 왔나요? 재발송'),
        ),
      ],
    );
  }
}

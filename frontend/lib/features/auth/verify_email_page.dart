import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 이메일 인증코드 입력 (email-verification-plan §8-2·§8-3).
///
/// 진입 경로 2개 — 둘 다 [email]을 받는다:
/// ① 가입 201 직후 자동 진입 (가입이 코드를 발송하므로 [sendOnEntry]=false)
/// ② 로그인 403(EMAIL_NOT_VERIFIED) 리다이렉트 — 가입 때 코드는 10분 만료라
///    [sendOnEntry]=true로 진입 즉시 새 코드를 발송한다 (§8-4)
class VerifyEmailPage extends StatefulWidget {
  const VerifyEmailPage({
    super.key,
    required this.email,
    this.sendOnEntry = false,
  });

  final String email;
  final bool sendOnEntry;

  @override
  State<VerifyEmailPage> createState() => _VerifyEmailPageState();
}

class _VerifyEmailPageState extends State<VerifyEmailPage>
    with SingleTickerProviderStateMixin {
  static const _resendCooldown = 60; // §8-2: 재발송 60초 쿨다운

  final _code = TextEditingController();
  bool _submitting = false;
  bool _highlightResend = false; // CODE_EXPIRED 시 재발송 버튼 강조 (§8-3)

  Timer? _cooldownTimer;
  int _cooldownLeft = 0;

  // INVALID_CODE 흔들림 피드백 (§8-3)
  late final AnimationController _shake =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 400));

  @override
  void initState() {
    super.initState();
    if (widget.sendOnEntry) _resend(); // 로그인 403 경로 — 새 코드 자동 발송
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
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('인증 완료! 로그인해주세요')));
      context.go('/login');
    } on ApiException catch (e) {
      if (!mounted) return;
      switch (e.code) {
        case 'INVALID_CODE':
          _snack('코드가 올바르지 않아요');
          _code.clear();
          _shake.forward(from: 0);
        case 'CODE_EXPIRED':
          _snack('코드가 만료됐어요. 재발송해주세요');
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
        // Retry-After 헤더는 ApiClient가 노출하지 않아 기본 쿨다운으로 대체 (§8-3)
        _snack('잠시 후 다시 시도해주세요');
        _startCooldown(_resendCooldown);
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
    return Scaffold(
      appBar: AppBar(
        leading: const AppBackButton(fallbackLocation: '/login'),
        title: const Text('이메일 인증'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.symmetric(vertical: 24),
            children: [
              Text('${widget.email}로\n인증코드를 보냈어요',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 18, fontWeight: FontWeight.w700, height: 1.4)),
              const SizedBox(height: 8),
              const Text('6자리 코드를 입력하면 자동으로 확인해요',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
              const SizedBox(height: 32),
              AnimatedBuilder(
                animation: _shake,
                builder: (context, child) => Transform.translate(
                  // 감쇠 사인파 — 좌우로 4회 흔들리며 잦아든다
                  offset: Offset(
                      sin(_shake.value * pi * 4) * 8 * (1 - _shake.value), 0),
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
                      fontSize: 32,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 12),
                  decoration: const InputDecoration(
                    hintText: '······',
                    counterText: '',
                  ),
                  onChanged: (v) {
                    if (v.length == 6) _submit(); // §8-2: 6자리 채우면 자동 제출
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
                  onPressed:
                      _submitting || _code.text.length != 6 ? null : _submit,
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
                child: Text(cooling
                    ? '재발송 ($_cooldownLeft초 후 가능)'
                    : '코드가 안 왔나요? 재발송'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

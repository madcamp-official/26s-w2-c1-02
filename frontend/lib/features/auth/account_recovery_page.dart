import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 아이디 찾기 · 비밀번호 재설정 (와이어프레임 a3, api-spec §2).
///
/// 비밀번호는 해시로만 저장돼 "찾아줄" 수 없다 → 재설정으로 처리한다. 두 흐름 모두
/// 서버는 계정 존재 여부를 응답으로 구분해주지 않으므로(열거 방지), 화면도 "가입돼
/// 있다면" 화법으로 안내한다.
class AccountRecoveryPage extends StatelessWidget {
  const AccountRecoveryPage({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          leading: const AppBackButton(fallbackLocation: '/login'),
          title: const Text('아이디·비밀번호 찾기'),
          bottom: const TabBar(
            tabs: [
              Tab(text: '아이디 찾기'),
              Tab(text: '비밀번호 재설정'),
            ],
          ),
        ),
        body: SafeArea(
          child: ResponsivePage(
            child: const TabBarView(
              children: [
                _FindUsernameTab(),
                _ResetPasswordTab(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ============================================================
// 아이디 찾기 — 이메일 입력 → 아이디는 메일로 발송
// ============================================================

class _FindUsernameTab extends StatefulWidget {
  const _FindUsernameTab();

  @override
  State<_FindUsernameTab> createState() => _FindUsernameTabState();
}

class _FindUsernameTabState extends State<_FindUsernameTab> {
  final _email = TextEditingController();
  bool _submitting = false;
  bool _sent = false; // 발송 완료 안내 표시

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    if (_submitting) return;
    if (email.isEmpty || !email.contains('@')) {
      _snack(context, '이메일 주소를 확인해주세요');
      return;
    }
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().findUsername(email);
      if (!mounted) return;
      setState(() => _sent = true); // 성공/미가입 구분 없이 동일 안내 (열거 방지)
    } on ApiException catch (e) {
      if (!mounted) return;
      _snack(context, e.message ?? '요청에 실패했어요. 잠시 후 다시 시도해주세요');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_sent) {
      return _SentPanel(
        title: '아이디를 메일로 보냈어요',
        message: '입력하신 주소로 가입된 계정이 있다면\n아이디를 담은 메일을 보내드렸어요.\n'
            '메일함(스팸함 포함)을 확인해주세요.',
        onBackToLogin: () => context.go('/login'),
        onRetry: () => setState(() => _sent = false),
      );
    }
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      children: [
        const Text('가입할 때 쓴 이메일을 입력하면\n아이디를 메일로 알려드려요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.4)),
        const SizedBox(height: 32),
        TextField(
          controller: _email,
          enabled: !_submitting,
          autofocus: true,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          decoration: const InputDecoration(hintText: '이메일'),
          onSubmitted: (_) => _submit(),
        ),
        const SizedBox(height: 24),
        _PrimaryButton(
          label: _submitting ? '보내는 중…' : '아이디 찾기',
          onPressed: _submitting ? null : _submit,
        ),
      ],
    );
  }
}

// ============================================================
// 비밀번호 재설정 — 이메일로 코드 발송 → 코드 + 새 비밀번호
// ============================================================

class _ResetPasswordTab extends StatefulWidget {
  const _ResetPasswordTab();

  @override
  State<_ResetPasswordTab> createState() => _ResetPasswordTabState();
}

class _ResetPasswordTabState extends State<_ResetPasswordTab> {
  static const _resendCooldown = 60; // §2: 재발송 60초 쿨다운

  final _email = TextEditingController();
  final _code = TextEditingController();
  final _pw = TextEditingController();
  final _pwConfirm = TextEditingController();

  String? _sentEmail; // null이면 아직 이메일 입력 단계
  bool _submitting = false;

  Timer? _cooldownTimer;
  int _cooldownLeft = 0;

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _pw.dispose();
    _pwConfirm.dispose();
    _cooldownTimer?.cancel();
    super.dispose();
  }

  Future<void> _requestCode() async {
    final email = _email.text.trim();
    if (_submitting) return;
    if (email.isEmpty || !email.contains('@')) {
      _snack(context, '이메일 주소를 확인해주세요');
      return;
    }
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().requestPasswordReset(email);
      if (!mounted) return;
      setState(() => _sentEmail = email); // 미가입이어도 204 → 코드 입력 단계로 (열거 방지)
      _startCooldown(_resendCooldown);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 429) {
        final retryAfter =
            (e.details?['retry_after_seconds'] as num?)?.toInt() ?? _resendCooldown;
        // 쿨다운 중이어도 이미 코드가 발송돼 있으므로 코드 입력 단계로 넘어간다.
        setState(() => _sentEmail = email);
        _startCooldown(retryAfter);
      } else {
        _snack(context, e.message ?? '코드 발송에 실패했어요. 잠시 후 다시 시도해주세요');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _resend() async {
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().requestPasswordReset(_sentEmail!);
      if (!mounted) return;
      _snack(context, '재설정 코드를 다시 보냈어요');
      _startCooldown(_resendCooldown);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 429) {
        final retryAfter =
            (e.details?['retry_after_seconds'] as num?)?.toInt() ?? _resendCooldown;
        _startCooldown(retryAfter);
      } else {
        _snack(context, e.message ?? '재발송에 실패했어요');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _submitReset() async {
    if (_submitting) return;
    if (_code.text.length != 6) {
      _snack(context, '6자리 코드를 입력해주세요');
      return;
    }
    if (_pw.text.length < 8) {
      _snack(context, '비밀번호는 8자 이상이어야 해요');
      return;
    }
    if (_pw.text != _pwConfirm.text) {
      _snack(context, '비밀번호가 서로 달라요');
      return;
    }
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().resetPassword(
            email: _sentEmail!,
            code: _code.text,
            newPassword: _pw.text,
          );
      if (!mounted) return;
      _snack(context, '비밀번호를 변경했어요. 새 비밀번호로 로그인해주세요');
      context.go('/login');
    } on ApiException catch (e) {
      if (!mounted) return;
      switch (e.code) {
        case 'INVALID_CODE':
          _snack(context, '코드가 올바르지 않아요');
          _code.clear();
        case 'CODE_EXPIRED': // 10분 경과 또는 5회 오입력 소진 (§2)
          _snack(context, '코드가 만료됐어요 (10분 경과 또는 5회 초과). 재발송해주세요');
          _code.clear();
        case 'PASSWORD_TOO_LONG':
          _snack(context, e.message ?? '비밀번호가 너무 길어요');
        default:
          _snack(context, e.message ?? '재설정에 실패했어요. 잠시 후 다시 시도해주세요');
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
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

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      children: _sentEmail == null ? _emailStep() : _codeStep(),
    );
  }

  List<Widget> _emailStep() => [
        const Text('가입할 때 쓴 이메일로\n재설정 코드를 보내드려요',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.4)),
        const SizedBox(height: 32),
        TextField(
          controller: _email,
          enabled: !_submitting,
          autofocus: true,
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.done,
          decoration: const InputDecoration(hintText: '이메일'),
          onSubmitted: (_) => _requestCode(),
        ),
        const SizedBox(height: 24),
        _PrimaryButton(
          label: _submitting ? '보내는 중…' : '재설정 코드 받기',
          onPressed: _submitting ? null : _requestCode,
        ),
      ];

  List<Widget> _codeStep() {
    final cooling = _cooldownLeft > 0;
    return [
      Text('$_sentEmail로\n재설정 코드를 보냈어요',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.4)),
      const SizedBox(height: 8),
      const Text('10분 안에 입력해주세요 · 5회 틀리면 재발송이 필요해요',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
      const SizedBox(height: 24),
      TextField(
        controller: _code,
        enabled: !_submitting,
        autofocus: true,
        keyboardType: TextInputType.number,
        inputFormatters: [
          FilteringTextInputFormatter.digitsOnly,
          LengthLimitingTextInputFormatter(6),
        ],
        textAlign: TextAlign.center,
        style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: 10),
        decoration: const InputDecoration(hintText: '······', counterText: ''),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _pw,
        enabled: !_submitting,
        obscureText: true,
        decoration: const InputDecoration(hintText: '새 비밀번호 (8자 이상)'),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _pwConfirm,
        enabled: !_submitting,
        obscureText: true,
        textInputAction: TextInputAction.done,
        decoration: const InputDecoration(hintText: '새 비밀번호 확인'),
        onSubmitted: (_) => _submitReset(),
      ),
      const SizedBox(height: 24),
      _PrimaryButton(
        label: _submitting ? '변경 중…' : '비밀번호 변경',
        onPressed: _submitting ? null : _submitReset,
      ),
      const SizedBox(height: 12),
      TextButton(
        style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
        onPressed: cooling || _submitting ? null : _resend,
        child: Text(cooling ? '재발송 ($_cooldownLeft초 후 가능)' : '코드가 안 왔나요? 재발송'),
      ),
    ];
  }
}

// ============================================================
// 공용 위젯
// ============================================================

void _snack(BuildContext context, String msg) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

class _PrimaryButton extends StatelessWidget {
  const _PrimaryButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
        onPressed: onPressed,
        child: Text(label),
      ),
    );
  }
}

/// 아이디 찾기 발송 완료 안내 패널.
class _SentPanel extends StatelessWidget {
  const _SentPanel({
    required this.title,
    required this.message,
    required this.onBackToLogin,
    required this.onRetry,
  });

  final String title;
  final String message;
  final VoidCallback onBackToLogin;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      children: [
        const SizedBox(height: 24),
        Center(
          child: CircleAvatar(
            radius: 28,
            backgroundColor: AppColors.primary.withValues(alpha: 0.1),
            child: const Icon(Icons.mark_email_read_outlined,
                color: AppColors.primary, size: 28),
          ),
        ),
        const SizedBox(height: 24),
        Text(title,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
        const SizedBox(height: 12),
        Text(message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textSecondary, height: 1.5)),
        const SizedBox(height: 32),
        _PrimaryButton(label: '로그인으로 돌아가기', onPressed: onBackToLogin),
        const SizedBox(height: 8),
        TextButton(
          style: TextButton.styleFrom(foregroundColor: AppColors.textSecondary),
          onPressed: onRetry,
          child: const Text('다른 이메일로 다시 시도'),
        ),
      ],
    );
  }
}

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_colors.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';
import 'verify_code_section.dart';

/// 이메일 인증 페이지 — 주 진입은 로그인 403(EMAIL_NOT_VERIFIED) 리다이렉트 (§8-4).
///
/// 가입 직후 인증은 signup_page 안의 2단계(VerifyCodeSection)가 처리하므로,
/// 이 페이지는 "가입은 했지만 인증을 못 마친 채 나중에 로그인한 유저"용이다.
/// 로그인은 username 기반이고 403 응답에 email이 없어서, [email]이 비어 있으면
/// 이메일 입력 단계를 먼저 보여준다. 확정 시 새 코드를 발송한다(이전 코드는 10분 만료).
class VerifyEmailPage extends StatefulWidget {
  const VerifyEmailPage({
    super.key,
    this.email = '',
    this.sendOnEntry = false,
  });

  final String email;
  final bool sendOnEntry;

  @override
  State<VerifyEmailPage> createState() => _VerifyEmailPageState();
}

class _VerifyEmailPageState extends State<VerifyEmailPage> {
  final _emailInput = TextEditingController();
  String? _email; // null이면 아직 이메일 입력 단계

  @override
  void initState() {
    super.initState();
    if (widget.email.isNotEmpty) _email = widget.email;
  }

  @override
  void dispose() {
    _emailInput.dispose();
    super.dispose();
  }

  void _confirmEmail() {
    final email = _emailInput.text.trim();
    if (email.isEmpty || !email.contains('@')) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('이메일 주소를 확인해주세요')));
      return;
    }
    setState(() => _email = email);
  }

  @override
  Widget build(BuildContext context) {
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
              if (_email == null)
                ..._emailEntry()
              else
                VerifyCodeSection(
                  // 이메일 입력 단계를 거쳤거나 sendOnEntry면 새 코드 발송이 필요.
                  key: ValueKey(_email),
                  email: _email!,
                  sendOnInit: widget.sendOnEntry || widget.email.isEmpty,
                  onVerified: () {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                        content: Text('인증 완료! 로그인해주세요')));
                    context.go('/login');
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }

  /// 로그인 403 경로 1단계 — 가입한 이메일을 받아 새 코드를 발송한다.
  List<Widget> _emailEntry() {
    return [
      const Text('이메일 인증이 필요해요',
          textAlign: TextAlign.center,
          style: TextStyle(
              fontSize: 18, fontWeight: FontWeight.w700, height: 1.4)),
      const SizedBox(height: 8),
      const Text('가입할 때 쓴 이메일로 인증코드를 보내드려요',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: AppColors.textSecondary)),
      const SizedBox(height: 32),
      TextField(
        controller: _emailInput,
        autofocus: true,
        keyboardType: TextInputType.emailAddress,
        decoration: const InputDecoration(hintText: '이메일'),
        onSubmitted: (_) => _confirmEmail(),
      ),
      const SizedBox(height: 24),
      SizedBox(
        height: 56,
        child: FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.primary,
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
          onPressed: _confirmEmail,
          child: const Text('인증코드 받기'),
        ),
      ),
    ];
  }
}

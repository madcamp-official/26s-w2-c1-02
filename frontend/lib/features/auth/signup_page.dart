import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 회원가입 (와이어프레임 a2). Step 1: 폼 골격 + mock 가입.
/// 이메일 인증코드 실발송은 백엔드(Step 4, 우선순위 '선택') 이후.
class SignupPage extends StatefulWidget {
  const SignupPage({super.key});

  @override
  State<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends State<SignupPage> {
  final _name = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _passwordConfirm = TextEditingController();
  final _email = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    for (final c in [_name, _username, _password, _passwordConfirm, _email]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (_password.text != _passwordConfirm.text) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('비밀번호가 일치하지 않아요')));
      return;
    }
    setState(() => _submitting = true);
    try {
      await context.read<AuthController>().signup(
            name: _name.text.trim(),
            username: _username.text.trim(),
            password: _password.text,
            email: _email.text.trim(),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('가입 완료! 로그인해주세요 (이메일 인증은 추후)')));
      context.go('/login');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(leading: const AppBackButton(fallbackLocation: '/login'), title: const Text('회원가입')),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.symmetric(vertical: 16),
            children: [
              _field(_name, '이름'),
              _field(_username, '아이디'),
              _field(_password, '비밀번호', obscure: true),
              _field(_passwordConfirm, '비밀번호 확인', obscure: true),
              Row(
                children: [
                  Expanded(child: _field(_email, '이메일', bottom: 0)),
                  const SizedBox(width: 8),
                  TextButton(
                    style: TextButton.styleFrom(
                      backgroundColor: AppColors.surface,
                      foregroundColor: AppColors.textPrimary,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 18),
                    ),
                    onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('이메일 발송은 추후 연동 (mock)'))),
                    child: const Text('인증요청'),
                  ),
                ],
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
                  onPressed: _submitting ? null : _submit,
                  child: Text(_submitting ? '가입 중…' : '가입하기'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String hint,
      {bool obscure = false, double bottom = 12}) {
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: TextField(
        controller: c,
        obscureText: obscure,
        decoration: InputDecoration(hintText: hint),
      ),
    );
  }
}

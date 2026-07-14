import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';
import 'verify_code_section.dart';

/// 회원가입 (와이어프레임 a2) — 2단계.
/// ① 가입 폼 → signup 201 (백엔드가 인증코드 발송)
/// ② 같은 화면에서 6자리 코드 입력(10분 만료·5회 소진·재발송 60초 쿨다운)
///    → verify 200 → 로그인 화면으로.
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

  /// 가입 성공한 이메일 — null이 아니면 코드 입력 단계(②)를 표시한다.
  String? _pendingEmail;

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
      final email = _email.text.trim();
      await context.read<AuthController>().signup(
            name: _name.text.trim(),
            username: _username.text.trim(),
            password: _password.text,
            email: email,
          );
      if (!mounted) return;
      // 가입(201) = 인증코드 발송됨 — 같은 화면에서 코드 입력 단계로 전환.
      setState(() => _pendingEmail = email);
    } on ApiException catch (e) {
      if (!mounted) return;
      final msg = switch (e.code) {
        'USERNAME_TAKEN' => '이미 사용 중인 아이디예요',
        'EMAIL_TAKEN' => '이미 가입된 이메일이에요',
        _ => e.message ?? '가입에 실패했어요. 잠시 후 다시 시도해주세요',
      };
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(msg)));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          leading: const AppBackButton(fallbackLocation: '/login'),
          title: Text(_pendingEmail == null ? '회원가입' : '이메일 인증')),
      body: SafeArea(
        child: ResponsivePage(
          child: _pendingEmail == null ? _signupForm() : _verifyStep(),
        ),
      ),
    );
  }

  /// ① 가입 폼.
  Widget _signupForm() {
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 16),
      children: [
        _field(_name, '이름'),
        _field(_username, '아이디'),
        _field(_password, '비밀번호', obscure: true, helper: '8자 이상 입력해주세요'),
        _field(_passwordConfirm, '비밀번호 확인', obscure: true),
        // "인증요청" 버튼 없음 — 가입 자체가 인증코드를 발송한다 (§8-1).
        _field(_email, '이메일', bottom: 0, helper: '가입하면 이 주소로 인증코드가 발송돼요'),
        const SizedBox(height: 24),
        SizedBox(
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primary,
              shape:
                  RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: _submitting ? null : _submit,
            child: Text(_submitting ? '가입 중…' : '가입하기'),
          ),
        ),
      ],
    );
  }

  /// ② 인증코드 입력 — 가입이 발송한 코드를 이 화면에서 바로 입력한다.
  Widget _verifyStep() {
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      children: [
        VerifyCodeSection(
          email: _pendingEmail!,
          sendOnInit: false, // 가입(201)이 방금 발송 — 재발송 쿨다운만 시작됨
          onVerified: () {
            ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('인증 완료! 로그인해주세요')));
            context.go('/login');
          },
        ),
      ],
    );
  }

  Widget _field(TextEditingController c, String hint,
      {bool obscure = false, double bottom = 12, String? helper}) {
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: TextField(
        controller: c,
        obscureText: obscure,
        // helperText는 입력 전부터 항상 표시 — 비밀번호 8~128자 제약(auth 스키마) 안내용.
        decoration: InputDecoration(hintText: hint, helperText: helper),
      ),
    );
  }
}

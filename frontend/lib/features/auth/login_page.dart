import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../state/auth_controller.dart';
import '../common/responsive_page.dart';

/// 로그인 (와이어프레임 a1).
/// 소셜은 구글 1종만 동작(우선순위 '선택'), 카카오/네이버는 자리만 (README 구현 명세서).
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _usernameController = TextEditingController();
  final _pwController = TextEditingController();

  @override
  void dispose() {
    _usernameController.dispose();
    _pwController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    final auth = context.read<AuthController>();
    try {
      await auth.login(
        username: _usernameController.text.trim(),
        password: _pwController.text,
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      // §8-4: 403 = 비밀번호는 맞는데 이메일 미인증 — 코드 입력 화면으로.
      // 로그인은 username 기반이라 이메일은 인증 화면 1단계에서 입력받는다.
      if (e.statusCode == 403 && e.code == 'EMAIL_NOT_VERIFIED') {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('이메일 인증이 필요해요')));
        context.go('/verify-email');
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.statusCode == 401
              ? '아이디 또는 비밀번호가 올바르지 않아요'
              : (e.message ?? '로그인에 실패했어요. 잠시 후 다시 시도해주세요'))));
      return;
    }
    if (mounted && auth.isLoggedIn) context.go('/');
  }

  Future<void> _loginGoogle() async {
    final auth = context.read<AuthController>();
    await auth.loginWithSocial(SocialProvider.google);
    if (mounted && auth.isLoggedIn) context.go('/');
  }

  void _notSupported(String name) {
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$name 로그인은 이번 범위에서 자리만 있어요 (구글만 지원 예정)')));
  }

  @override
  Widget build(BuildContext context) {
    final loading = context.watch<AuthController>().loading;

    return Scaffold(
      body: SafeArea(
        child: ResponsivePage(
          child: SingleChildScrollView(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const SizedBox(height: 48),
                Image.asset(
                  'assets/icons/malggori-character.png',
                  width: 140,
                  height: 140,
                  fit: BoxFit.contain,
                ),
                const SizedBox(height: 28),
                const Text('당신의 발표를 더 완벽하게',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
                const Text('말꼬리',
                    style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w800,
                        color: AppColors.accent)),
                const SizedBox(height: 32),
                TextField(
                  controller: _usernameController,
                  decoration: const InputDecoration(hintText: '아이디'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pwController,
                  obscureText: true,
                  decoration: const InputDecoration(hintText: '비밀번호'),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.primary,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: loading ? null : _login,
                    child: Text(loading ? '로그인 중…' : '로그인',
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _link('아이디·비밀번호 찾기', () => context.push('/account-recovery')),
                    const Text('  |  ',
                        style: TextStyle(color: AppColors.textSecondary)),
                    _link('회원가입', () => context.push('/signup')),
                  ],
                ),
                const SizedBox(height: 24),
                _SocialButton(
                    label: '구글로 로그인',
                    onTap: loading ? null : _loginGoogle),
                const SizedBox(height: 10),
                _SocialButton(
                    label: '카카오로 로그인 (자리만)',
                    onTap: () => _notSupported('카카오')),
                const SizedBox(height: 10),
                _SocialButton(
                    label: '네이버로 로그인 (자리만)',
                    onTap: () => _notSupported('네이버')),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _link(String text, VoidCallback onTap) => GestureDetector(
        onTap: onTap,
        child: Text(text,
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSecondary,
              decoration: TextDecoration.underline,
            )),
      );
}

class _SocialButton extends StatelessWidget {
  const _SocialButton({required this.label, this.onTap});
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 50,
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.textPrimary,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        onPressed: onTap,
        child: Text(label, style: const TextStyle(fontSize: 14)),
      ),
    );
  }
}

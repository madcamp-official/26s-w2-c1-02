import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/responsive_page.dart';

/// 로그인 / 회원가입 화면 (Figma: 로그인 화면).
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _idController = TextEditingController();
  final _pwController = TextEditingController();

  @override
  void dispose() {
    _idController.dispose();
    _pwController.dispose();
    super.dispose();
  }

  Future<void> _login({String? provider}) async {
    final auth = context.read<AuthController>();
    if (provider != null) {
      await auth.loginWithProvider(provider);
    } else {
      await auth.login(id: _idController.text, password: _pwController.text);
    }
    if (mounted && auth.isLoggedIn) context.go('/');
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
                // 로고 자리 (Figma "아이콘")
                Container(
                  width: 140,
                  height: 140,
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  alignment: Alignment.center,
                  child: const Text('아이콘',
                      style: TextStyle(fontSize: 28, color: AppColors.textSecondary)),
                ),
                const SizedBox(height: 28),
                const Text('당신의 발표를 더 완벽하게',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                const Text('Rehearsal.io',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700)),
                const SizedBox(height: 32),
                TextField(
                  controller: _idController,
                  decoration: const InputDecoration(hintText: 'ID'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pwController,
                  obscureText: true,
                  decoration: const InputDecoration(hintText: 'PW'),
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Text('아직 회원이 아니신가요? ',
                        style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
                    GestureDetector(
                      onTap: () {
                        // TODO: 회원가입 플로우 (실제 인증 붙일 때 구현)
                      },
                      child: const Text('회원가입하기',
                          style: TextStyle(
                            fontSize: 13,
                            decoration: TextDecoration.underline,
                          )),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                _PrimaryLoginButton(
                  label: loading ? '로그인 중…' : '로그인',
                  onTap: loading ? null : () => _login(),
                ),
                const SizedBox(height: 20),
                _SocialButton(
                  label: '카카오로 로그인',
                  onTap: loading ? null : () => _login(provider: 'kakao'),
                ),
                const SizedBox(height: 12),
                _SocialButton(
                  label: '네이버로 로그인',
                  onTap: loading ? null : () => _login(provider: 'naver'),
                ),
                const SizedBox(height: 12),
                _SocialButton(
                  label: '구글로 로그인',
                  onTap: loading ? null : () => _login(provider: 'google'),
                ),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _PrimaryLoginButton extends StatelessWidget {
  const _PrimaryLoginButton({required this.label, this.onTap});
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        onPressed: onTap,
        child: Text(label),
      ),
    );
  }
}

class _SocialButton extends StatelessWidget {
  const _SocialButton({required this.label, this.onTap});
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.textPrimary,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
        ),
        onPressed: onTap,
        child: Text(label),
      ),
    );
  }
}

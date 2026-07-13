import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 비밀번호 변경 (와이어프레임 09 i2) — PATCH /users/me/password.
class ChangePasswordPage extends StatefulWidget {
  const ChangePasswordPage({super.key});

  @override
  State<ChangePasswordPage> createState() => _ChangePasswordPageState();
}

class _ChangePasswordPageState extends State<ChangePasswordPage> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _confirm = TextEditingController();
  bool _submitting = false;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final cur = _current.text;
    final next = _next.text;
    if (cur.isEmpty || next.isEmpty) return _snack('현재·새 비밀번호를 입력해주세요');
    if (next.length < 8) return _snack('새 비밀번호는 8자 이상이어야 해요');
    if (next != _confirm.text) return _snack('새 비밀번호 확인이 일치하지 않아요');

    setState(() => _submitting = true);
    try {
      await context
          .read<AuthController>()
          .changePassword(currentPassword: cur, newPassword: next);
      if (!mounted) return;
      _snack('비밀번호가 변경됐어요');
      context.pop();
    } on ApiException catch (e) {
      if (mounted) _snack(e.message ?? '변경에 실패했어요');
    } catch (_) {
      if (mounted) _snack('변경에 실패했어요');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  void _snack(String m) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: const AppBackButton(fallbackLocation: '/me'),
        title: const Text('비밀번호 변경'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.symmetric(vertical: 24),
            children: [
              _field('현재 비밀번호', _current),
              const SizedBox(height: 16),
              _field('새 비밀번호 (8자 이상)', _next),
              const SizedBox(height: 16),
              _field('새 비밀번호 확인', _confirm),
              const SizedBox(height: 32),
              SizedBox(
                height: 54,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: _submitting ? null : _submit,
                  child: Text(_submitting ? '변경 중…' : '변경하기',
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w700)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _field(String label, TextEditingController c) {
    return TextField(
      controller: c,
      obscureText: true,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
      ),
    );
  }
}

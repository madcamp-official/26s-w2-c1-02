import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/repositories/team_repository.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/fade_slide_in.dart';
import '../common/responsive_page.dart';

/// 팀 만들기 (와이어프레임 c1) — spec §3: 팀 이름 + 초대(이메일/링크).
/// v0.3에서 '프레젠테이션 유형'은 팀이 아니라 세션 설정(페르소나)으로 이동했다.
class CreateTeamPage extends StatefulWidget {
  const CreateTeamPage({super.key});

  @override
  State<CreateTeamPage> createState() => _CreateTeamPageState();
}

class _CreateTeamPageState extends State<CreateTeamPage> {
  static const _maxNameLength = 20;

  final _nameController = TextEditingController();
  final _emailController = TextEditingController();

  String? _nameError;
  bool _nameConfirmed = false;
  final List<String> _invitedEmails = [];
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    super.dispose();
  }

  void _confirmName() {
    final value = _nameController.text.trim();
    setState(() {
      if (value.isEmpty) {
        _nameError = '팀 이름을 작성해주세요';
        _nameConfirmed = false;
      } else if (value.length > _maxNameLength) {
        _nameError = '팀 이름은 $_maxNameLength자 이내로 작성해주세요';
        _nameConfirmed = false;
      } else {
        _nameError = null;
        _nameConfirmed = true;
      }
    });
  }

  void _addEmail() {
    final email = _emailController.text.trim();
    if (email.isEmpty || !email.contains('@')) return;
    setState(() {
      _invitedEmails.add(email);
      _emailController.clear();
    });
  }

  Future<void> _submit() async {
    if (!_nameConfirmed) return;
    setState(() => _submitting = true);
    try {
      final teamCtrl = context.read<TeamController>();
      final repo = context.read<TeamRepository>();
      final team = await teamCtrl.create(_nameController.text.trim());
      for (final email in _invitedEmails) {
        await repo.inviteByEmail(team.id, email);
      }
      if (!mounted) return;
      context.go('/');
      context.push('/teams/${team.id}');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.only(top: 8, bottom: 32),
            children: [
              const Text('새로운 프레젠테이션',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const Text('팀을 만들게요',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const SizedBox(height: 20),
              const Text('팀 이름', style: TextStyle(color: AppColors.textSecondary)),
              const SizedBox(height: 8),
              TextField(
                controller: _nameController,
                maxLength: _maxNameLength + 5,
                decoration: InputDecoration(
                  counterText: '',
                  hintText: '팀 이름 입력',
                  errorText: _nameError,
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                      '${_nameController.text.length} / $_maxNameLength',
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.hint)),
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  style: TextButton.styleFrom(
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.textPrimary,
                  ),
                  onPressed: _confirmName,
                  child: const Text('확인'),
                ),
              ),

              // 팀원 초대 — 이름 확정 후 fade-in
              if (_nameConfirmed)
                FadeSlideIn(
                  key: const ValueKey('step-invite'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: 16),
                      const Text('팀원 초대',
                          style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _emailController,
                              decoration:
                                  const InputDecoration(hintText: '이메일 주소'),
                            ),
                          ),
                          const SizedBox(width: 8),
                          TextButton(
                            style: TextButton.styleFrom(
                              backgroundColor: AppColors.accent
                                  .withValues(alpha: 0.15),
                              foregroundColor: AppColors.accent,
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 16, vertical: 18),
                            ),
                            onPressed: _addEmail,
                            child: const Text('초대 보내기'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: _invitedEmails
                            .map((e) => Chip(
                                  label: Text(e),
                                  onDeleted: () => setState(
                                      () => _invitedEmails.remove(e)),
                                ))
                            .toList(),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        height: 48,
                        child: TextButton.icon(
                          style: TextButton.styleFrom(
                            backgroundColor: AppColors.surface,
                            foregroundColor: AppColors.textPrimary,
                          ),
                          icon: const Icon(Icons.link, size: 18),
                          label: const Text('초대 링크 복사'),
                          onPressed: () async {
                            // 팀 생성 전이므로 안내만 — 생성 후 팀 화면에서 실제 링크 발급.
                            await Clipboard.setData(const ClipboardData(
                                text: 'https://rehearsal.io/invites/(팀 생성 후 발급)'));
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text('팀을 만들면 실제 초대 링크가 발급돼요')));
                            }
                          },
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '초대를 수락하면 자동으로 팀에 합류돼요.\n팀을 만든 후에도 초대할 수 있어요.',
                        style: TextStyle(
                            fontSize: 12, color: AppColors.textSecondary),
                      ),
                      const SizedBox(height: 40),
                      SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: AppColors.accent,
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(28)),
                          ),
                          onPressed: _submitting ? null : _submit,
                          child: Text(_submitting ? '만드는 중…' : '팀 만들기',
                              style: const TextStyle(
                                  fontSize: 17, fontWeight: FontWeight.w700)),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

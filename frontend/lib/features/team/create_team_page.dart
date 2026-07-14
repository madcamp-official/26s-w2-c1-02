import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/repositories/team_repository.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/fade_slide_in.dart';
import '../common/responsive_page.dart';
import 'invite_code_dialog.dart';

/// 팀 만들기 (와이어프레임 c1) — 팀 이름 → 만들기 → 초대코드 표시.
/// 팀 초대는 초대코드로 통일(§11-2) — 생성 완료 시 코드를 바로 보여주고,
/// 이후에도 팀 상세의 "+ 초대"에서 같은 코드를 다시 볼 수 있다.
class CreateTeamPage extends StatefulWidget {
  const CreateTeamPage({super.key});

  @override
  State<CreateTeamPage> createState() => _CreateTeamPageState();
}

class _CreateTeamPageState extends State<CreateTeamPage> {
  static const _maxNameLength = 20;

  final _nameController = TextEditingController();

  String? _nameError;
  bool _nameConfirmed = false;
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
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

  Future<void> _submit() async {
    if (!_nameConfirmed) return;
    setState(() => _submitting = true);
    try {
      final teamCtrl = context.read<TeamController>();
      final repo = context.read<TeamRepository>();
      final team = await teamCtrl.create(_nameController.text.trim());
      // 생성 완료 화면 = 초대코드 다이얼로그 (§11-2) — 닫으면 팀 상세로.
      final link = await repo.createInviteLink(team.id);
      if (!mounted) return;
      await showInviteCodeDialog(context, link.token);
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

              // 1) 팀 이름
              const Text('팀 이름',
                  style: TextStyle(color: AppColors.textSecondary)),
              const SizedBox(height: 8),
              TextField(
                controller: _nameController,
                maxLength: _maxNameLength + 5,
                onChanged: (_) => setState(() {}), // 글자수 표시 갱신
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
                  child: Text('${_nameController.text.length} / $_maxNameLength',
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

              // 2) 팀 만들기 — 이름 확정 후 fade-in. 초대는 생성 후 초대코드로(§11-2).
              if (_nameConfirmed)
                FadeSlideIn(
                  key: const ValueKey('step-create'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: 16),
                      const Text(
                        '팀을 만들면 초대코드가 발급돼요.\n'
                        '코드를 공유하면 팀원이 홈의 "초대코드로 참여"로 합류할 수 있어요.',
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

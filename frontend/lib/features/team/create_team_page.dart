import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/presentation_type.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/fade_slide_in.dart';
import '../common/responsive_page.dart';

/// 새 프레젠테이션 만들기 (Figma: 새 프레젠테이션 만들기 1~3).
///
/// 한 스크롤 화면에서 단계적으로 노출:
///   1) 팀 이름 (빈 값/20자 초과 검증) → 확인
///   2) 프레젠테이션 유형 단일 선택 → 확인
///   3) 팀원 초대(선택) → "프레젠테이션 팀 만들기"
class CreateTeamPage extends StatefulWidget {
  const CreateTeamPage({super.key});

  @override
  State<CreateTeamPage> createState() => _CreateTeamPageState();
}

class _CreateTeamPageState extends State<CreateTeamPage> {
  static const int _maxNameLength = 20;

  final _nameController = TextEditingController();

  String? _nameError;
  bool _nameConfirmed = false;
  PresentationType? _type;
  bool _typeConfirmed = false;
  final List<String> _invitedMembers = [];
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
    if (!_nameConfirmed || _type == null) return;
    setState(() => _submitting = true);
    final team = await context.read<TeamController>().create(
          name: _nameController.text.trim(),
          type: _type!,
          memberNames: _invitedMembers,
        );
    if (!mounted) return;
    // 팀 생성 후 해당 팀 화면으로 이동(메인은 스택에 남김).
    context.go('/');
    context.push('/teams/${team.id}');
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = _nameConfirmed && _typeConfirmed && _type != null;

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.only(top: 8, bottom: 32),
            children: [
              const Text('새로운 프레젠테이션을 만들게요',
                  style:
                      TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const SizedBox(height: 12),

              // 1) 팀 이름
              const Text('프레젠테이션의 이름을 작성해주세요',
                  style: TextStyle(fontSize: 15)),
              const SizedBox(height: 12),
              TextField(
                controller: _nameController,
                maxLength: _maxNameLength + 5, // 초과 입력 감지 위해 여유
                decoration: InputDecoration(
                  counterText: '',
                  errorText: _nameError,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(20),
                    borderSide: const BorderSide(color: AppColors.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(20),
                    borderSide: const BorderSide(color: AppColors.border),
                  ),
                ),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: _ConfirmChip(label: '확인', onTap: _confirmName),
              ),

              // 2) 프레젠테이션 유형 — 팀 이름 확정 후 fade-in + slide-up
              if (_nameConfirmed)
                FadeSlideIn(
                  // key로 단계를 구분해 다시 build돼도 애니메이션이 유지되게 함.
                  key: const ValueKey('step-type'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: 24),
                      const Text('어떤 프레젠테이션인가요?',
                          style: TextStyle(fontSize: 16)),
                      const SizedBox(height: 12),
                      ...PresentationType.values.map(
                        (t) => _SelectableTile(
                          label: t.label,
                          selected: _type == t,
                          onTap: () => setState(() {
                            _type = t;
                            _typeConfirmed = false;
                          }),
                        ),
                      ),
                      Align(
                        alignment: Alignment.centerRight,
                        child: _ConfirmChip(
                          label: '확인',
                          onTap: _type == null
                              ? null
                              : () => setState(() => _typeConfirmed = true),
                        ),
                      ),
                    ],
                  ),
                ),

              // 3) 팀원 초대 + 팀 만들기 버튼 — 마지막 단계에서만 fade-in + slide-up
              if (_typeConfirmed)
                FadeSlideIn(
                  key: const ValueKey('step-invite'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: 24),
                      const Text('프레젠테이션을 함께할 팀원이 있나요?',
                          style: TextStyle(fontSize: 16)),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          ..._invitedMembers.map((m) => Chip(
                                label: Text(m),
                                onDeleted: () =>
                                    setState(() => _invitedMembers.remove(m)),
                              )),
                          _InviteButton(onTap: _showInviteDialog),
                        ],
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '팀원이 초대를 수락하면 자동으로 프레젠테이션 팀에 초대돼요.\n'
                        '프레젠테이션 팀을 만든 후에도 팀원을 초대할 수 있어요.',
                        style: TextStyle(
                            fontSize: 12, color: AppColors.textSecondary),
                      ),
                      const SizedBox(height: 48),
                      // "프레젠테이션 팀 만들기"는 마지막 단계에서만 등장.
                      SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: AppColors.primary,
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(28)),
                          ),
                          onPressed:
                              canSubmit && !_submitting ? _submit : null,
                          child: Text(
                              _submitting ? '만드는 중…' : '프레젠테이션 팀 만들기',
                              style: const TextStyle(
                                  fontSize: 17, fontWeight: FontWeight.w700)),
                        ),
                      ),
                      const SizedBox(height: 8),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showInviteDialog() async {
    final controller = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('팀원 초대하기'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(hintText: '초대할 팀원의 ID/닉네임'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('취소')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('초대'),
          ),
        ],
      ),
    );
    if (name != null && name.isNotEmpty) {
      setState(() => _invitedMembers.add(name));
    }
  }
}

class _ConfirmChip extends StatelessWidget {
  const _ConfirmChip({required this.label, this.onTap});
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: TextButton(
        style: TextButton.styleFrom(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.textPrimary,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
        ),
        onPressed: onTap,
        child: Text(label),
      ),
    );
  }
}

class _SelectableTile extends StatelessWidget {
  const _SelectableTile({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          decoration: BoxDecoration(
            color: selected ? AppColors.surface : Colors.transparent,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: AppColors.border,
              width: selected ? 2 : 1,
            ),
          ),
          child: Text(label, style: const TextStyle(fontSize: 15)),
        ),
      ),
    );
  }
}

class _InviteButton extends StatelessWidget {
  const _InviteButton({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return TextButton(
      style: TextButton.styleFrom(
        backgroundColor: AppColors.surface,
        foregroundColor: AppColors.textPrimary,
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
      ),
      onPressed: onTap,
      child: const Text('팀원 초대하기'),
    );
  }
}

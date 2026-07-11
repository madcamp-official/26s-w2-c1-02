import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/files/file_constraints.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/session.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 발표 만들기 (와이어프레임 d1) — spec §4.1 세션 생성.
/// 페르소나 다중 선택(5종) · 질문 수 · 제한시간 · 진행 방식 ·
/// 실제 PDF 업로드(20MB/50p 클라이언트 검증, spec §1.3).
class CreateSessionPage extends StatefulWidget {
  const CreateSessionPage({super.key, required this.teamId});
  final String teamId;

  @override
  State<CreateSessionPage> createState() => _CreateSessionPageState();
}

class _CreateSessionPageState extends State<CreateSessionPage> {
  final _nameController = TextEditingController();
  final _countController = TextEditingController(text: '5');
  final _durationController = TextEditingController(text: '10');

  final Set<QuestionerPersona> _personas = {QuestionerPersona.egen};
  SessionMode _mode = SessionMode.realtime;
  PlatformFile? _pdf; // 선택된 발표 자료 (bytes 포함)
  bool _submitting = false;

  Future<void> _pickPdf() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      withData: true, // 웹 호환: bytes로 받기
    );
    final file = result?.files.single;
    if (file == null || file.bytes == null) return;

    final error = FileConstraints.validatePdf(
      fileName: file.name,
      sizeBytes: file.size,
      bytes: file.bytes,
    );
    if (error != null) {
      _snack(error);
      return;
    }
    setState(() => _pdf = file);
  }

  @override
  void dispose() {
    _nameController.dispose();
    _countController.dispose();
    _durationController.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) return _snack('발표 이름을 입력해주세요');
    if (_personas.isEmpty) return _snack('질문자 성격을 1개 이상 선택해주세요');
    final count = int.tryParse(_countController.text) ?? 0;
    final minutes = int.tryParse(_durationController.text) ?? 0;
    if (count < 1 || count > 20) return _snack('질문 개수는 1~20개예요');
    if (minutes < 1) return _snack('발표 제한시간을 입력해주세요');

    setState(() => _submitting = true);
    try {
      final session = await context.read<SessionController>().create(
            widget.teamId,
            SessionCreateRequest(
              name: name,
              personas: _personas.toList(),
              questionCount: count,
              timeLimitMinutes: minutes,
              mode: _mode,
            ),
          );

      final pdf = _pdf;
      if (pdf != null && mounted) {
        // PDF 업로드(202) → 전처리 상태 폴링 화면으로.
        await context.read<SessionRepository>().uploadMaterial(
              session.id,
              fileName: pdf.name,
              bytes: pdf.bytes!,
            );
        if (!mounted) return;
        context.pushReplacement('/sessions/${session.id}/material');
      } else if (mounted) {
        final next = _mode == SessionMode.upload
            ? '/sessions/${session.id}/upload-recording'
            : '/sessions/${session.id}/present';
        context.pushReplacement(next);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  void _snack(String msg) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(msg)));

  @override
  Widget build(BuildContext context) {
    final teamName =
        context.watch<TeamController>().byId(widget.teamId)?.name ?? '';

    return Scaffold(
      appBar: AppBar(
        leading: AppBackButton(fallbackLocation: '/teams/${widget.teamId}'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.only(top: 8, bottom: 32),
            children: [
              TextField(
                controller: _nameController,
                style:
                    const TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                decoration: const InputDecoration(
                  hintText: '발표 이름을 입력해주세요',
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: EdgeInsets.zero,
                  hintStyle: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: AppColors.hint),
                ),
              ),
              Text(teamName,
                  style: const TextStyle(
                      fontSize: 14, color: AppColors.textSecondary)),
              const SizedBox(height: 20),

              // 발표 자료 (Step 2에서 실파일 선택으로 교체)
              const Text('발표 자료 (PDF · 선택)',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: _pickPdf,
                child: Container(
                  height: 92,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                        color: _pdf != null ? AppColors.accent : AppColors.hint,
                        width: 1.4),
                    color: _pdf != null
                        ? AppColors.accent.withValues(alpha: 0.08)
                        : null,
                  ),
                  child: Center(
                    child: _pdf == null
                        ? const Text('+ PDF를 업로드해주세요',
                            style: TextStyle(color: AppColors.hint))
                        : Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.picture_as_pdf,
                                  size: 20, color: AppColors.accent),
                              const SizedBox(width: 8),
                              Flexible(
                                child: Text(
                                  '${_pdf!.name} · ${(_pdf!.size / (1024 * 1024)).toStringAsFixed(1)}MB',
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                      color: AppColors.accent,
                                      fontWeight: FontWeight.w600),
                                ),
                              ),
                              IconButton(
                                icon: const Icon(Icons.close, size: 18),
                                onPressed: () => setState(() => _pdf = null),
                              ),
                            ],
                          ),
                  ),
                ),
              ),
              const SizedBox(height: 6),
              const Text('자료 없이 진행하면 발표 내용만으로 질문을 만들어요. (최대 20MB · 50페이지)',
                  style:
                      TextStyle(fontSize: 12, color: AppColors.textSecondary)),
              const SizedBox(height: 20),

              // 진행 방식
              const Text('진행 방식',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              SegmentedButton<SessionMode>(
                segments: SessionMode.values
                    .map((m) =>
                        ButtonSegment(value: m, label: Text(m.label)))
                    .toList(),
                selected: {_mode},
                onSelectionChanged: (s) => setState(() => _mode = s.first),
              ),
              const SizedBox(height: 20),

              // 질문자 성격 (중복 선택)
              const Text('질문자 성격 (중복 가능)',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: QuestionerPersona.values.map((p) {
                  final on = _personas.contains(p);
                  return FilterChip(
                    label: Text(p.label),
                    selected: on,
                    selectedColor: AppColors.accent.withValues(alpha: 0.2),
                    checkmarkColor: AppColors.accent,
                    onSelected: (v) => setState(() {
                      v ? _personas.add(p) : _personas.remove(p);
                    }),
                  );
                }).toList(),
              ),
              const SizedBox(height: 20),

              // 질문 개수 / 제한시간
              Row(
                children: [
                  Expanded(
                    child: _NumberField(
                        label: '질문 개수', controller: _countController, suffix: '개'),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _NumberField(
                        label: '발표 제한시간',
                        controller: _durationController,
                        suffix: '분'),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              const Text('꼬리질문은 질문 1개당 최대 1번 이어질 수 있어요.',
                  style:
                      TextStyle(fontSize: 12, color: AppColors.textSecondary)),
              const SizedBox(height: 32),

              SizedBox(
                height: 56,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(28)),
                  ),
                  onPressed: _submitting ? null : _start,
                  child: Text(_submitting ? '준비 중…' : '발표 시작하기',
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w700)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField(
      {required this.label, required this.controller, required this.suffix});
  final String label;
  final TextEditingController controller;
  final String suffix;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(fontSize: 13, color: AppColors.textSecondary)),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: InputDecoration(suffixText: suffix),
        ),
      ],
    );
  }
}

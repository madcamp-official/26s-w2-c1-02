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
import '../common/fade_slide_in.dart';
import '../common/responsive_page.dart';

/// 발표 만들기 (와이어프레임 d1) — spec §4.1 세션 생성.
/// 진행 방식을 먼저 고르면 나머지 설정(질문자 성격·질문 개수·[제한시간])이
/// fade-slide-in으로 나타난다. 실제 PDF 업로드(20MB/50p 검증, spec §1.3).
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

  /// 초기에는 진행 방식 미선택 → 선택해야 나머지 설정이 나타남.
  SessionMode? _mode;
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
    final mode = _mode;
    if (mode == null) return; // 버튼은 모드 선택 후에만 노출됨(방어)

    final name = _nameController.text.trim();
    if (name.isEmpty) return _snack('발표 이름을 입력해주세요');
    if (_personas.isEmpty) return _snack('질문자 성격을 1개 이상 선택해주세요');
    final count = int.tryParse(_countController.text) ?? 0;
    if (count < 1 || count > 20) return _snack('질문 개수는 1~20개예요');

    final rawMinutes = int.tryParse(_durationController.text) ?? 0;
    if (mode == SessionMode.realtime && rawMinutes < 1) {
      return _snack('발표 제한시간을 입력해주세요');
    }
    // 파일 업로드 모드는 제한시간이 무의미 → 유효 기본값으로 보정(모델/DB는 필수).
    final minutes = rawMinutes < 1 ? 10 : rawMinutes;

    setState(() => _submitting = true);
    try {
      final session = await context.read<SessionController>().create(
            widget.teamId,
            SessionCreateRequest(
              name: name,
              personas: _personas.toList(),
              questionCount: count,
              timeLimitMinutes: minutes,
              mode: mode,
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
        final next = mode == SessionMode.upload
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

              // 발표 자료 (선택)
              const Text('발표 자료 (PDF · 선택)',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              _PdfPicker(
                pdf: _pdf,
                onTap: _pickPdf,
                onClear: () => setState(() => _pdf = null),
              ),
              const SizedBox(height: 6),
              const Text('자료 없이 진행하면 발표 내용만으로 질문을 만들어요. (최대 20MB · 50페이지)',
                  style:
                      TextStyle(fontSize: 12, color: AppColors.textSecondary)),
              const SizedBox(height: 20),

              // 진행 방식 — 서로 떨어진 두 버튼, 초기 미선택
              const Text('진행 방식',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: _ModeButton(
                      label: '실시간 녹음',
                      selected: _mode == SessionMode.realtime,
                      onTap: () =>
                          setState(() => _mode = SessionMode.realtime),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _ModeButton(
                      label: '녹음 파일 업로드',
                      selected: _mode == SessionMode.upload,
                      onTap: () => setState(() => _mode = SessionMode.upload),
                    ),
                  ),
                ],
              ),

              // 모드를 처음 선택할 때만 fade+slide로 등장.
              // key를 주지 않아 모드를 바꿔도 FadeSlideIn은 재mount되지 않고
              // (element 재사용) 자식만 다시 그려지므로 애니메이션이 재생되지 않는다.
              if (_mode != null) FadeSlideIn(child: _buildSettings(_mode!)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSettings(SessionMode mode) {
    final isRealtime = mode == SessionMode.realtime;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 24),

        // 질문자 성격 — 한 줄 고정, 체크표시 없음, 색만 변함
        const Text('질문자 성격 (중복 가능)',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        Row(
          children: [
            for (final p in QuestionerPersona.values) ...[
              Expanded(
                child: _PersonaChip(
                  label: p.label,
                  selected: _personas.contains(p),
                  onTap: () => setState(() {
                    _personas.contains(p)
                        ? _personas.remove(p)
                        : _personas.add(p);
                  }),
                ),
              ),
              if (p != QuestionerPersona.values.last)
                const SizedBox(width: 6),
            ],
          ],
        ),
        const SizedBox(height: 20),

        // 질문 개수 (+ 실시간 모드에서만 발표 제한시간)
        if (isRealtime)
          Row(
            children: [
              Expanded(
                child: _NumberField(
                    label: '질문 개수',
                    controller: _countController,
                    suffix: '개'),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: _NumberField(
                    label: '발표 제한시간',
                    controller: _durationController,
                    suffix: '분'),
              ),
            ],
          )
        else
          Row(
            children: [
              Expanded(
                child: _NumberField(
                    label: '질문 개수',
                    controller: _countController,
                    suffix: '개'),
              ),
              const Spacer(),
            ],
          ),
        const SizedBox(height: 6),
        const Text('꼬리질문은 질문 1개당 최대 1번 이어질 수 있어요.',
            style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
        const SizedBox(height: 32),

        SizedBox(
          width: double.infinity,
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primary,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(28)),
            ),
            onPressed: _submitting ? null : _start,
            child: Text(_submitting ? '준비 중…' : '발표 시작하기',
                style:
                    const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          ),
        ),
      ],
    );
  }
}

/// 진행 방식 버튼 (서로 떨어진 개별 버튼).
class _ModeButton extends StatelessWidget {
  const _ModeButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: Container(
        height: 52,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected
              ? AppColors.accent.withValues(alpha: 0.15)
              : AppColors.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppColors.accent : Colors.transparent,
            width: 1.6,
          ),
        ),
        child: Text(label,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: selected ? AppColors.accent : AppColors.textSecondary,
            )),
      ),
    );
  }
}

/// 질문자 성격 토글 — 크기 고정(체크표시·리사이즈 없음), 선택 시 색만 변경.
class _PersonaChip extends StatelessWidget {
  const _PersonaChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(20),
      onTap: onTap,
      child: Container(
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected
              ? AppColors.accent.withValues(alpha: 0.18)
              : AppColors.surface,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: selected ? AppColors.accent : Colors.transparent,
            width: 1.4,
          ),
        ),
        child: Text(label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: selected ? AppColors.accent : AppColors.textSecondary,
            )),
      ),
    );
  }
}

class _PdfPicker extends StatelessWidget {
  const _PdfPicker({
    required this.pdf,
    required this.onTap,
    required this.onClear,
  });
  final PlatformFile? pdf;
  final VoidCallback onTap;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Container(
        height: 92,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
              color: pdf != null ? AppColors.accent : AppColors.hint,
              width: 1.4),
          color: pdf != null ? AppColors.accent.withValues(alpha: 0.08) : null,
        ),
        child: Center(
          child: pdf == null
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
                        '${pdf!.name} · ${(pdf!.size / (1024 * 1024)).toStringAsFixed(1)}MB',
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: AppColors.accent,
                            fontWeight: FontWeight.w600),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: onClear,
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

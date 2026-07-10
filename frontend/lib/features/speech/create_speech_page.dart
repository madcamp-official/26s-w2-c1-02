import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/audience_type.dart';
import '../../state/speech_controller.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 발표 만들기 화면 (Figma: 발표 만들기 화면).
/// 발표 이름 + 발표자료(PDF) + 청중/질문자 유형 + 질문 개수 + 발표 시간 → 발표 시작하기.
class CreateSpeechPage extends StatefulWidget {
  const CreateSpeechPage({super.key, required this.teamId});
  final String teamId;

  @override
  State<CreateSpeechPage> createState() => _CreateSpeechPageState();
}

class _CreateSpeechPageState extends State<CreateSpeechPage> {
  final _nameController = TextEditingController();
  final _detailController = TextEditingController();
  final _countController = TextEditingController(text: '3');
  final _durationController = TextEditingController(text: '5');

  String? _materialFileName;
  AudienceType _audience = AudienceType.teto;
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _detailController.dispose();
    _countController.dispose();
    _durationController.dispose();
    super.dispose();
  }

  Future<void> _pickPdf() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      withData: false,
    );
    if (result != null && result.files.isNotEmpty) {
      setState(() => _materialFileName = result.files.single.name);
    }
  }

  Future<void> _start() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      _snack('발표 이름을 입력해주세요');
      return;
    }
    final count = int.tryParse(_countController.text.trim()) ?? 0;
    final duration = int.tryParse(_durationController.text.trim()) ?? 0;
    if (count <= 0) {
      _snack('질문 개수를 입력해주세요');
      return;
    }
    if (duration <= 0) {
      _snack('발표 시간을 입력해주세요');
      return;
    }

    setState(() => _submitting = true);
    final speech = await context.read<SpeechController>().create(
          teamId: widget.teamId,
          name: name,
          materialFileName: _materialFileName,
          audienceType: _audience,
          audienceDetail:
              _audience == AudienceType.etc ? _detailController.text.trim() : null,
          questionCount: count,
          durationMinutes: duration,
        );
    if (!mounted) return;
    // 기능 명세 5): 발표 시작 버튼 = 녹음 시작. 발표중 화면으로 이동.
    context.go('/teams/${widget.teamId}');
    context.push('/speeches/${speech.id}/present');
  }

  void _snack(String msg) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

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
                style: const TextStyle(
                    fontSize: 22, fontWeight: FontWeight.w800),
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
                      fontSize: 15, color: AppColors.textSecondary)),
              const SizedBox(height: 24),

              // 발표 자료(PDF)
              const Text('발표 자료(PDF)',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              _PdfDropZone(
                fileName: _materialFileName,
                onTap: _pickPdf,
                onClear: () => setState(() => _materialFileName = null),
              ),
              const SizedBox(height: 24),

              // 청중/질문자 유형
              const Text('질문자 유형 선택',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              RadioGroup<AudienceType>(
                groupValue: _audience,
                onChanged: (v) => setState(() => _audience = v!),
                child: Column(
                  children: AudienceType.values
                      .map((a) => RadioListTile<AudienceType>(
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            value: a,
                            title: Text(a.label),
                          ))
                      .toList(),
                ),
              ),
              if (_audience == AudienceType.etc)
                Padding(
                  padding: const EdgeInsets.only(left: 16, top: 4),
                  child: TextField(
                    controller: _detailController,
                    maxLines: 3,
                    decoration: InputDecoration(
                      hintText: '최대한 자세하게 작성해주세요',
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ),
              const SizedBox(height: 24),

              // 질문 개수 + 발표 시간
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: _NumberField(
                      title: '질문 개수 입력',
                      controller: _countController,
                      suffix: '개',
                      helper: '꼬리물기 질문은 최대 3단계까지\n이어질 수 있어요.',
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _NumberField(
                      title: '발표 시간 입력',
                      controller: _durationController,
                      suffix: '분',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 40),

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

class _PdfDropZone extends StatelessWidget {
  const _PdfDropZone({
    required this.fileName,
    required this.onTap,
    required this.onClear,
  });
  final String? fileName;
  final VoidCallback onTap;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(20),
      onTap: onTap,
      child: Container(
        height: 150,
        width: double.infinity,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.border),
        ),
        child: Center(
          child: fileName == null
              ? Column(
                  mainAxisSize: MainAxisSize.min,
                  children: const [
                    Icon(Icons.add, size: 28),
                    SizedBox(height: 8),
                    Text('발표 자료를 추가해주세요',
                        style: TextStyle(color: AppColors.hint)),
                  ],
                )
              : Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.picture_as_pdf, size: 28),
                    const SizedBox(height: 8),
                    Text(fileName!,
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    TextButton(onPressed: onClear, child: const Text('다시 선택')),
                  ],
                ),
        ),
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField({
    required this.title,
    required this.controller,
    required this.suffix,
    this.helper,
  });
  final String title;
  final TextEditingController controller;
  final String suffix;
  final String? helper;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title,
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: InputDecoration(
                  border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(20)),
                  contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 12),
                ),
              ),
            ),
            const SizedBox(width: 6),
            Text(suffix,
                style: const TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
        if (helper != null) ...[
          const SizedBox(height: 6),
          Text(helper!,
              style: const TextStyle(
                  fontSize: 11, color: AppColors.textSecondary)),
        ],
      ],
    );
  }
}

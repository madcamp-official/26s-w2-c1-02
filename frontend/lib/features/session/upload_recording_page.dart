import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/files/file_constraints.dart';
import '../../core/theme/app_colors.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 녹음 파일 업로드 (와이어프레임 d3) — mode=upload 경로.
/// mp3 · wav · m4a (+webm) / 최대 200MB (spec §1.3). 길이(60분)는 서버 검증.
class UploadRecordingPage extends StatefulWidget {
  const UploadRecordingPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<UploadRecordingPage> createState() => _UploadRecordingPageState();
}

class _UploadRecordingPageState extends State<UploadRecordingPage> {
  PlatformFile? _file;
  bool _uploading = false;

  Future<void> _pick() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: FileConstraints.audioExtensions,
      withData: true,
    );
    final file = result?.files.single;
    if (file == null || file.bytes == null) return;

    final error = FileConstraints.validateAudio(
        fileName: file.name, sizeBytes: file.size);
    if (error != null) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error)));
      }
      return;
    }
    setState(() => _file = file);
  }

  Future<void> _upload() async {
    final file = _file;
    if (file == null) return;
    setState(() => _uploading = true);
    try {
      final now = DateTime.now();
      await context.read<SessionRepository>().uploadRecording(
            widget.sessionId,
            fileName: file.name,
            bytes: file.bytes!,
            startedAt: now, // 파일 모드: 실제 발표 시각은 알 수 없음 — 업로드 시각 기록
            endedAt: now,
            durationSeconds: 0, // 서버가 디코딩해서 실측 (클라이언트는 모름)
          );
      if (mounted) {
        context.pushReplacement('/sessions/${widget.sessionId}/processing');
      }
    } catch (e) {
      if (mounted) {
        setState(() => _uploading = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('업로드 실패: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final file = _file;
    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 8),
              const Text('녹음 파일로',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const Text('진행할게요',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const SizedBox(height: 24),
              InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: _pick,
                child: Container(
                  height: 130,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                        color: file != null ? AppColors.accent : AppColors.hint,
                        width: 1.4),
                    color: file != null
                        ? AppColors.accent.withValues(alpha: 0.08)
                        : null,
                  ),
                  child: Center(
                    child: file == null
                        ? Column(
                            mainAxisSize: MainAxisSize.min,
                            children: const [
                              Icon(Icons.upload, color: AppColors.hint),
                              SizedBox(height: 8),
                              Text('발표 녹음 파일을 올려주세요',
                                  style: TextStyle(color: AppColors.hint)),
                              Text('mp3 · wav · m4a · webm / 최대 60분 · 200MB',
                                  style: TextStyle(
                                      fontSize: 11.5, color: AppColors.hint)),
                            ],
                          )
                        : Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.audiotrack,
                                  size: 20, color: AppColors.accent),
                              const SizedBox(width: 8),
                              Flexible(
                                child: Text(
                                  '${file.name} · ${(file.size / (1024 * 1024)).toStringAsFixed(1)}MB',
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                      color: AppColors.accent,
                                      fontWeight: FontWeight.w600),
                                ),
                              ),
                              IconButton(
                                icon: const Icon(Icons.close, size: 18),
                                onPressed: () => setState(() => _file = null),
                              ),
                            ],
                          ),
                  ),
                ),
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: (file == null || _uploading) ? null : _upload,
                  child: Text(_uploading ? '업로드 중…' : '질의응답 만들기',
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}

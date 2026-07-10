import '../models/audience_type.dart';
import '../models/qna.dart';
import '../models/speech.dart';

abstract class SpeechRepository {
  Future<List<Speech>> fetchSpeeches(String teamId);
  Future<Speech> getSpeech(String id);
  Future<Speech> createSpeech({
    required String teamId,
    required String name,
    String? materialFileName,
    required AudienceType audienceType,
    String? audienceDetail,
    required int questionCount,
    required int durationMinutes,
  });

  /// 발표 종료 후 LLM이 생성하는 질의응답 목록.
  /// 지금은 목 데이터, 추후 백엔드 LLM(Gemini 등) 연동으로 교체.
  Future<List<QnaItem>> generateQna(String speechId);
}

class MockSpeechRepository implements SpeechRepository {
  final Map<String, List<Speech>> _byTeam = {
    't_1': const [
      Speech(id: 's_1', teamId: 't_1', name: 'speech1'),
      Speech(id: 's_2', teamId: 't_1', name: 'speech2'),
    ],
  };

  int _seq = 100;

  Speech? _find(String id) {
    for (final list in _byTeam.values) {
      for (final s in list) {
        if (s.id == id) return s;
      }
    }
    return null;
  }

  @override
  Future<List<Speech>> fetchSpeeches(String teamId) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return List.unmodifiable(_byTeam[teamId] ?? const []);
  }

  @override
  Future<Speech> getSpeech(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 100));
    final s = _find(id);
    if (s == null) throw StateError('speech $id not found');
    return s;
  }

  @override
  Future<Speech> createSpeech({
    required String teamId,
    required String name,
    String? materialFileName,
    required AudienceType audienceType,
    String? audienceDetail,
    required int questionCount,
    required int durationMinutes,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
    final speech = Speech(
      id: 's_${_seq++}',
      teamId: teamId,
      name: name,
      materialFileName: materialFileName,
      audienceType: audienceType,
      audienceDetail: audienceDetail,
      questionCount: questionCount,
      durationMinutes: durationMinutes,
    );
    _byTeam.putIfAbsent(teamId, () => []).add(speech);
    return speech;
  }

  @override
  Future<List<QnaItem>> generateQna(String speechId) async {
    // LLM 생성 지연 흉내.
    await Future<void>.delayed(const Duration(milliseconds: 400));
    final speech = _find(speechId);
    final count = speech?.questionCount ?? 3;
    return List.generate(
      count,
      (i) => QnaItem(
        index: i + 1,
        question: '(예시) 발표 내용 관련 질문 ${i + 1}입니다. 이 부분을 더 설명해 주시겠어요?',
      ),
    );
  }
}

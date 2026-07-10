import 'package:flutter/foundation.dart';

import '../data/models/audience_type.dart';
import '../data/models/speech.dart';
import '../data/repositories/speech_repository.dart';

class SpeechController extends ChangeNotifier {
  SpeechController(this._repo);

  final SpeechRepository _repo;

  /// teamId -> 스피치 목록 캐시.
  final Map<String, List<Speech>> _byTeam = {};
  bool _loading = false;

  bool get loading => _loading;

  List<Speech> speechesOf(String teamId) => _byTeam[teamId] ?? const [];

  Speech? byId(String id) {
    for (final list in _byTeam.values) {
      for (final s in list) {
        if (s.id == id) return s;
      }
    }
    return null;
  }

  Future<void> load(String teamId) async {
    _loading = true;
    notifyListeners();
    _byTeam[teamId] = await _repo.fetchSpeeches(teamId);
    _loading = false;
    notifyListeners();
  }

  Future<Speech> ensureLoaded(String speechId) async {
    final cached = byId(speechId);
    if (cached != null) return cached;
    final speech = await _repo.getSpeech(speechId);
    _byTeam.putIfAbsent(speech.teamId, () => []).add(speech);
    return speech;
  }

  Future<Speech> create({
    required String teamId,
    required String name,
    String? materialFileName,
    required AudienceType audienceType,
    String? audienceDetail,
    required int questionCount,
    required int durationMinutes,
  }) async {
    final speech = await _repo.createSpeech(
      teamId: teamId,
      name: name,
      materialFileName: materialFileName,
      audienceType: audienceType,
      audienceDetail: audienceDetail,
      questionCount: questionCount,
      durationMinutes: durationMinutes,
    );
    await load(teamId);
    return speech;
  }
}

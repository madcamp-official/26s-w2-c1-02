import 'package:flutter/foundation.dart';

import '../data/models/presentation_type.dart';
import '../data/models/team.dart';
import '../data/repositories/team_repository.dart';

class TeamController extends ChangeNotifier {
  TeamController(this._repo);

  final TeamRepository _repo;

  List<Team> _teams = [];
  bool _loading = false;

  List<Team> get teams => _teams;
  bool get loading => _loading;

  Team? byId(String id) {
    for (final t in _teams) {
      if (t.id == id) return t;
    }
    return null;
  }

  Future<void> load() async {
    _loading = true;
    notifyListeners();
    _teams = await _repo.fetchTeams();
    _loading = false;
    notifyListeners();
  }

  Future<Team> create({
    required String name,
    required PresentationType type,
    required List<String> memberNames,
  }) async {
    final team = await _repo.createTeam(
      name: name,
      type: type,
      memberNames: memberNames,
    );
    await load();
    return team;
  }

  Future<void> leave(String id) async {
    await _repo.leaveTeam(id);
    await load();
  }
}

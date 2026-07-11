import 'package:flutter/foundation.dart';

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
    try {
      _teams = await _repo.fetchTeams();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<Team> create(String name) async {
    final team = await _repo.createTeam(name);
    await load();
    return team;
  }

  Future<void> leave(String id) async {
    await _repo.leaveTeam(id);
    await load();
  }

  Future<void> deleteTeam(String id) async {
    await _repo.deleteTeam(id);
    await load();
  }
}

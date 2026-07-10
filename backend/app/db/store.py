"""아주 단순한 인메모리 저장소.

지금은 DB 대신 프로세스 메모리에 데이터를 담는다.
추후 SQLModel/SQLAlchemy + Postgres 등으로 교체하기 쉽도록
접근을 이 모듈로 한정한다.
"""

from itertools import count

from app.schemas.common import PresentationType
from app.schemas.speech import Speech
from app.schemas.team import Team


class InMemoryStore:
    def __init__(self) -> None:
        self._team_seq = count(100)
        self._speech_seq = count(100)

        # Figma 시안과 동일한 시드 데이터.
        self.teams: dict[str, Team] = {
            "t_1": Team(
                id="t_1",
                name="teamname1",
                type=PresentationType.schoolTeamProject,
                member_names=["user", "user2"],
            ),
            "t_2": Team(
                id="t_2",
                name="teamname2",
                type=PresentationType.companyPtInterview,
                member_names=["user", "user3", "user4"],
            ),
            "t_3": Team(
                id="t_3",
                name="teamname3",
                type=PresentationType.executiveReport,
                member_names=["user", "user3", "user5"],
            ),
        }
        self.speeches: dict[str, Speech] = {
            "s_1": Speech(id="s_1", team_id="t_1", name="speech1"),
            "s_2": Speech(id="s_2", team_id="t_1", name="speech2"),
        }

    # --- teams ---
    def list_teams(self) -> list[Team]:
        return list(self.teams.values())

    def get_team(self, team_id: str) -> Team | None:
        return self.teams.get(team_id)

    def add_team(self, team: Team) -> Team:
        self.teams[team.id] = team
        return team

    def remove_team(self, team_id: str) -> None:
        self.teams.pop(team_id, None)

    def next_team_id(self) -> str:
        return f"t_{next(self._team_seq)}"

    # --- speeches ---
    def list_speeches(self, team_id: str) -> list[Speech]:
        return [s for s in self.speeches.values() if s.team_id == team_id]

    def get_speech(self, speech_id: str) -> Speech | None:
        return self.speeches.get(speech_id)

    def add_speech(self, speech: Speech) -> Speech:
        self.speeches[speech.id] = speech
        return speech

    def next_speech_id(self) -> str:
        return f"s_{next(self._speech_seq)}"


store = InMemoryStore()

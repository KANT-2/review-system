from dataclasses import dataclass


class TeamQueryError(ValueError):
    """팀 조회 원본 데이터가 올바르지 않을 때 발생한다."""


class RoundParticipantNotFoundError(TeamQueryError):
    """사용자가 해당 회차 참가자가 아닐 때 발생한다."""


@dataclass(frozen=True)
class ParticipantSnapshot:
    participant_id: int
    user_id: int
    student_number: str
    display_name: str


@dataclass(frozen=True)
class StoredTeam:
    team_number: int
    name: str
    participant_ids: tuple[int, ...]


@dataclass(frozen=True)
class TeamQueryData:
    round_id: int
    round_status: str
    lock_version: int
    participants: tuple[ParticipantSnapshot, ...]
    teams: tuple[StoredTeam, ...]


@dataclass(frozen=True)
class TeamMemberView:
    participant_id: int
    student_number: str
    display_name: str


@dataclass(frozen=True)
class TeamView:
    team_number: int
    name: str
    members: tuple[TeamMemberView, ...]


@dataclass(frozen=True)
class ManagementTeamView:
    round_id: int
    round_status: str
    lock_version: int
    is_configured: bool
    is_read_only: bool
    teams: tuple[TeamView, ...]
    unassigned_members: tuple[TeamMemberView, ...]


@dataclass(frozen=True)
class StudentTeamView:
    round_id: int
    is_configured: bool
    team: TeamView | None
    teams: tuple[TeamView, ...] = ()
    participant_id: int | None = None


def build_management_team_view(data: TeamQueryData) -> ManagementTeamView:
    """튜터용 전체 팀 구성과 미배정 참가자 목록을 만든다."""
    participant_by_id = _participant_map(data.participants)
    assigned_participant_ids: set[int] = set()
    team_views = []

    for team in sorted(data.teams, key=lambda item: item.team_number):
        members = []
        for participant_id in team.participant_ids:
            if participant_id in assigned_participant_ids:
                raise TeamQueryError(f"participant is assigned more than once: {participant_id}")
            participant = participant_by_id.get(participant_id)
            if participant is None:
                raise TeamQueryError(f"unknown participant in team: {participant_id}")
            assigned_participant_ids.add(participant_id)
            members.append(_to_member_view(participant))
        team_views.append(TeamView(team.team_number, team.name, tuple(members)))

    unassigned_members = tuple(
        _to_member_view(participant)
        for participant in data.participants
        if participant.participant_id not in assigned_participant_ids
    )
    return ManagementTeamView(
        round_id=data.round_id,
        round_status=data.round_status,
        lock_version=data.lock_version,
        is_configured=bool(team_views),
        is_read_only=data.round_status != "DRAFT",
        teams=tuple(team_views),
        unassigned_members=unassigned_members,
    )


def build_student_team_view(data: TeamQueryData, user_id: int) -> StudentTeamView:
    """학생 본인의 현재 팀과 같은 팀원을 반환한다."""
    matching_participants = [
        participant for participant in data.participants if participant.user_id == user_id
    ]
    if not matching_participants:
        raise RoundParticipantNotFoundError("user is not a participant in this round")
    if len(matching_participants) > 1:
        raise TeamQueryError(f"user has duplicate round participants: {user_id}")

    management_view = build_management_team_view(data)
    participant_id = matching_participants[0].participant_id
    matching_teams = [
        team
        for team in management_view.teams
        if any(member.participant_id == participant_id for member in team.members)
    ]
    if not matching_teams:
        return StudentTeamView(
            data.round_id,
            False,
            None,
            management_view.teams,
            participant_id,
        )
    return StudentTeamView(
        data.round_id,
        True,
        matching_teams[0],
        management_view.teams,
        participant_id,
    )


def _participant_map(
    participants: tuple[ParticipantSnapshot, ...],
) -> dict[int, ParticipantSnapshot]:
    participant_by_id = {participant.participant_id: participant for participant in participants}
    if len(participant_by_id) != len(participants):
        raise TeamQueryError("participant IDs must be unique")
    return participant_by_id


def _to_member_view(participant: ParticipantSnapshot) -> TeamMemberView:
    # 과거 회차 표시는 현재 User 이름이 아니라 회차 참가자 스냅샷을 사용한다.
    return TeamMemberView(
        participant_id=participant.participant_id,
        student_number=participant.student_number,
        display_name=participant.display_name,
    )

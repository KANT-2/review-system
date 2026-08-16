from dataclasses import dataclass, replace


class TeamEditingError(ValueError):
    """수동 팀 편집 요청을 적용할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class TeamDraft:
    """저장 전 화면에서 편집하는 한 팀의 데이터다."""

    team_number: int
    name: str
    participant_ids: tuple[int, ...]


@dataclass(frozen=True)
class TeamBoard:
    """특정 회차의 저장 전 팀 편집 상태다."""

    round_id: int
    lock_version: int
    teams: tuple[TeamDraft, ...]


def move_participant(
    board: TeamBoard,
    participant_id: int,
    target_team_number: int,
) -> TeamBoard:
    """참가자를 현재 팀에서 대상 팀으로 이동한 새 편집 상태를 반환한다."""
    source_team = _find_participant_team(board, participant_id)
    target_team = _find_team(board, target_team_number)
    if source_team.team_number == target_team.team_number:
        return board

    updated_teams = []
    for team in board.teams:
        if team.team_number == source_team.team_number:
            updated_teams.append(
                replace(
                    team,
                    participant_ids=tuple(
                        member_id
                        for member_id in team.participant_ids
                        if member_id != participant_id
                    ),
                )
            )
        elif team.team_number == target_team.team_number:
            updated_teams.append(
                replace(
                    team,
                    participant_ids=(*team.participant_ids, participant_id),
                )
            )
        else:
            updated_teams.append(team)

    # 화면의 변경 취소와 저장 전 비교가 가능하도록 원본 board는 수정하지 않는다.
    return replace(board, teams=tuple(updated_teams))


def swap_participants(
    board: TeamBoard,
    first_participant_id: int,
    second_participant_id: int,
) -> TeamBoard:
    """서로 다른 팀의 두 참가자를 맞교환한 새 편집 상태를 반환한다."""
    if first_participant_id == second_participant_id:
        raise TeamEditingError("two different participants are required")

    first_team = _find_participant_team(board, first_participant_id)
    second_team = _find_participant_team(board, second_participant_id)
    if first_team.team_number == second_team.team_number:
        raise TeamEditingError("participants must belong to different teams")

    updated_teams = []
    for team in board.teams:
        if team.team_number == first_team.team_number:
            updated_teams.append(
                replace(
                    team,
                    participant_ids=tuple(
                        second_participant_id if member_id == first_participant_id else member_id
                        for member_id in team.participant_ids
                    ),
                )
            )
        elif team.team_number == second_team.team_number:
            updated_teams.append(
                replace(
                    team,
                    participant_ids=tuple(
                        first_participant_id if member_id == second_participant_id else member_id
                        for member_id in team.participant_ids
                    ),
                )
            )
        else:
            updated_teams.append(team)

    return replace(board, teams=tuple(updated_teams))


def _find_team(board: TeamBoard, team_number: int) -> TeamDraft:
    matching_teams = [team for team in board.teams if team.team_number == team_number]
    if not matching_teams:
        raise TeamEditingError(f"team does not exist: {team_number}")
    if len(matching_teams) > 1:
        raise TeamEditingError(f"team number is duplicated: {team_number}")
    return matching_teams[0]


def _find_participant_team(board: TeamBoard, participant_id: int) -> TeamDraft:
    matching_teams = [team for team in board.teams if participant_id in team.participant_ids]
    if not matching_teams:
        raise TeamEditingError(f"participant is not assigned: {participant_id}")
    if len(matching_teams) > 1:
        raise TeamEditingError(f"participant is assigned more than once: {participant_id}")
    return matching_teams[0]

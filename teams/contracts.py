from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from teams.application import AutoTeamBoardResult
from teams.domain import TeamBoard, TeamDraft
from teams.queries import ManagementTeamView, StudentTeamView, TeamMemberView, TeamView


class TeamContractError(ValueError):
    """Teams 요청 데이터의 모양이나 타입이 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class AutoAssignmentRequest:
    team_count: int
    lock_version: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AutoAssignmentRequest":
        return cls(
            team_count=_required_integer(payload, "team_count"),
            lock_version=_required_integer(payload, "lock_version"),
        )


@dataclass(frozen=True)
class TeamSaveRequest:
    board: TeamBoard
    imbalance_confirmed: bool

    @classmethod
    def from_payload(
        cls,
        round_id: int,
        payload: Mapping[str, object],
    ) -> "TeamSaveRequest":
        lock_version = _required_integer(payload, "lock_version")
        raw_teams = payload.get("teams")
        if not isinstance(raw_teams, list):
            raise TeamContractError("teams must be a list")

        teams = tuple(_parse_team(raw_team, index) for index, raw_team in enumerate(raw_teams))
        team_numbers = [team.team_number for team in teams]
        if len(team_numbers) != len(set(team_numbers)):
            raise TeamContractError("team_number must be unique")

        imbalance_confirmed = payload.get("imbalance_confirmed", False)
        if type(imbalance_confirmed) is not bool:
            raise TeamContractError("imbalance_confirmed must be a boolean")
        return cls(
            board=TeamBoard(
                round_id=round_id,
                lock_version=lock_version,
                teams=teams,
            ),
            imbalance_confirmed=imbalance_confirmed,
        )


def auto_team_board_response(result: AutoTeamBoardResult) -> dict[str, Any]:
    """자동편성 결과를 JSON 직렬화가 가능한 응답으로 변환한다."""
    return {
        "round_id": result.board.round_id,
        "lock_version": result.board.lock_version,
        "teams": [_team_draft_response(team) for team in result.board.teams],
        "quality": {
            "initial_standard_deviation": _decimal_response(result.initial_standard_deviation),
            "final_standard_deviation": _decimal_response(result.final_standard_deviation),
            "seeded_participant_count": result.seeded_participant_count,
            "initial_repeated_pair_count": result.initial_repeated_pair_count,
            "final_repeated_pair_count": result.final_repeated_pair_count,
            "optimization_count": result.optimization_count,
        },
    }


def saved_team_board_response(board: TeamBoard) -> dict[str, Any]:
    return {
        "round_id": board.round_id,
        "lock_version": board.lock_version,
        "teams": [_team_draft_response(team) for team in board.teams],
    }


def management_team_response(view: ManagementTeamView) -> dict[str, Any]:
    return {
        "round_id": view.round_id,
        "round_status": view.round_status,
        "lock_version": view.lock_version,
        "is_configured": view.is_configured,
        "is_read_only": view.is_read_only,
        "teams": [_team_view_response(team) for team in view.teams],
        "unassigned_members": [_member_response(member) for member in view.unassigned_members],
    }


def student_team_response(view: StudentTeamView) -> dict[str, Any]:
    return {
        "round_id": view.round_id,
        "is_configured": view.is_configured,
        "team": _team_view_response(view.team) if view.team is not None else None,
        # 기존 team 필드는 호환성을 위해 유지하고 전체 편성 조회를 추가한다.
        "teams": [_team_view_response(team) for team in view.teams],
        "my_participant_id": view.participant_id,
    }


def _parse_team(raw_team: object, index: int) -> TeamDraft:
    if not isinstance(raw_team, Mapping):
        raise TeamContractError(f"teams[{index}] must be an object")
    team_number = _required_integer(raw_team, "team_number", prefix=f"teams[{index}].")
    if team_number < 1:
        raise TeamContractError(f"teams[{index}].team_number must be at least 1")

    name = raw_team.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TeamContractError(f"teams[{index}].name must not be blank")

    raw_participant_ids = raw_team.get("participant_ids")
    if not isinstance(raw_participant_ids, list):
        raise TeamContractError(f"teams[{index}].participant_ids must be a list")
    participant_ids = []
    for participant_index, participant_id in enumerate(raw_participant_ids):
        if type(participant_id) is not int:
            raise TeamContractError(
                f"teams[{index}].participant_ids[{participant_index}] must be an integer"
            )
        participant_ids.append(participant_id)

    return TeamDraft(team_number, name.strip(), tuple(participant_ids))


def _required_integer(
    payload: Mapping[str, object],
    field_name: str,
    *,
    prefix: str = "",
) -> int:
    value = payload.get(field_name)
    if type(value) is not int:
        raise TeamContractError(f"{prefix}{field_name} must be an integer")
    return value


def _decimal_response(value: Decimal | None) -> str | None:
    # JSON float 변환으로 계산 정밀도가 손실되지 않도록 Decimal은 문자열로 보낸다.
    return str(value) if value is not None else None


def _team_draft_response(team: TeamDraft) -> dict[str, Any]:
    return {
        "team_number": team.team_number,
        "name": team.name,
        "participant_ids": list(team.participant_ids),
    }


def _team_view_response(team: TeamView) -> dict[str, Any]:
    return {
        "team_number": team.team_number,
        "name": team.name,
        "members": [_member_response(member) for member in team.members],
    }


def _member_response(member: TeamMemberView) -> dict[str, Any]:
    return {
        "participant_id": member.participant_id,
        "student_number": member.student_number,
        "display_name": member.display_name,
    }

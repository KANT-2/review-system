from dataclasses import dataclass, replace
from typing import Protocol, Self

from teams.domain import TeamBoard
from teams.services import validate_assignment


class TeamSaveError(ValueError):
    """팀 구성을 저장할 수 없을 때 발생한다."""


class RoundNotEditableError(TeamSaveError):
    """DRAFT가 아닌 회차를 수정하려 할 때 발생한다."""


class TeamVersionConflictError(TeamSaveError):
    """화면 버전보다 서버의 팀 구성이 새로울 때 발생한다."""


@dataclass(frozen=True)
class RoundForTeamEditing:
    round_id: int
    status: str
    lock_version: int
    participant_ids: tuple[int, ...]


class TeamSaveUnitOfWork(Protocol):
    """향후 Django transaction.atomic 구현이 따라야 하는 저장 경계다."""

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

    def get_round_for_update(self, round_id: int) -> RoundForTeamEditing: ...

    def replace_team_configuration(self, board: TeamBoard) -> None: ...

    def increase_lock_version(self, round_id: int) -> None: ...

    def record_team_configuration_saved(self, round_id: int) -> None: ...

    def commit(self) -> None: ...


def save_team_configuration(
    board: TeamBoard,
    unit_of_work: TeamSaveUnitOfWork,
    *,
    imbalance_confirmed: bool = False,
) -> TeamBoard:
    """팀 구성 전체를 검증하고 하나의 원자적 작업으로 교체한다."""
    with unit_of_work:
        current_round = unit_of_work.get_round_for_update(board.round_id)
        if current_round.status != "DRAFT":
            raise RoundNotEditableError("only DRAFT rounds can edit teams")
        if current_round.lock_version != board.lock_version:
            raise TeamVersionConflictError(
                "team configuration changed; reload the latest configuration"
            )

        validate_assignment(
            [team.participant_ids for team in board.teams],
            current_round.participant_ids,
            imbalance_confirmed=imbalance_confirmed,
        )
        unit_of_work.replace_team_configuration(board)
        unit_of_work.increase_lock_version(board.round_id)
        unit_of_work.record_team_configuration_saved(board.round_id)
        unit_of_work.commit()

    # DB 버전 증가와 같은 값을 반환해 다음 편집 요청이 최신 버전을 사용하게 한다.
    return replace(board, lock_version=board.lock_version + 1)

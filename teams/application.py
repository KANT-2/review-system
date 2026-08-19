import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Protocol, Self

from teams.domain import TeamBoard, TeamDraft
from teams.services import create_seed_balanced_assignment, validate_assignment


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


@dataclass(frozen=True)
class AutoTeamBoardResult:
    """화면에 표시할 자동편성 보드와 개선 정보를 전달한다."""

    board: TeamBoard
    initial_standard_deviation: Decimal | None
    final_standard_deviation: Decimal | None
    seeded_participant_count: int
    initial_repeated_pair_count: int
    final_repeated_pair_count: int
    optimization_count: int
    seed_scores: Mapping[int, Decimal | None] = field(default_factory=dict)


class TeamSaveUnitOfWork(Protocol):
    """향후 Django transaction.atomic 구현이 따라야 하는 저장 경계다."""

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

    def get_round_for_update(self, round_id: int) -> RoundForTeamEditing: ...

    def replace_team_configuration(self, board: TeamBoard) -> None: ...

    def increase_lock_version(self, round_id: int) -> None: ...

    def record_team_configuration_saved(self, round_id: int, actor_id: int) -> None: ...

    def commit(self) -> None: ...


def create_auto_team_board(
    *,
    round_id: int,
    lock_version: int,
    participant_ids: Sequence[int],
    seed_scores: Mapping[int, Decimal | None],
    team_count: int,
    previous_teammate_pairs: Collection[tuple[int, int]] = (),
    rng: random.Random | None = None,
) -> AutoTeamBoardResult:
    """자동편성 계산 결과를 같은 화면에서 수정할 수 있는 보드로 변환한다."""
    assignment = create_seed_balanced_assignment(
        participant_ids,
        seed_scores,
        team_count,
        previous_teammate_pairs=previous_teammate_pairs,
        rng=rng,
    )
    board = TeamBoard(
        round_id=round_id,
        lock_version=lock_version,
        teams=tuple(
            TeamDraft(
                team_number=team_index,
                name=f"{team_index}팀",
                participant_ids=tuple(team_participant_ids),
            )
            for team_index, team_participant_ids in enumerate(
                assignment.teams,
                start=1,
            )
        ),
    )
    return AutoTeamBoardResult(
        board=board,
        initial_standard_deviation=(assignment.initial_metrics.population_standard_deviation),
        final_standard_deviation=assignment.final_metrics.population_standard_deviation,
        seeded_participant_count=assignment.final_metrics.seeded_participant_count,
        initial_repeated_pair_count=assignment.initial_repeated_pair_count,
        final_repeated_pair_count=assignment.final_repeated_pair_count,
        optimization_count=assignment.optimization_count,
        seed_scores=seed_scores,
    )


def save_team_configuration(
    board: TeamBoard,
    unit_of_work: TeamSaveUnitOfWork,
    *,
    actor_id: int,
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
        unit_of_work.record_team_configuration_saved(board.round_id, actor_id)
        unit_of_work.commit()

    # DB 버전 증가와 같은 값을 반환해 다음 편집 요청이 최신 버전을 사용하게 한다.
    return replace(board, lock_version=board.lock_version + 1)

import random
from collections.abc import Collection, Mapping
from decimal import Decimal
from typing import Callable, Protocol

from teams.application import (
    AutoTeamBoardResult,
    RoundForTeamEditing,
    RoundNotEditableError,
    TeamSaveUnitOfWork,
    TeamVersionConflictError,
    create_auto_team_board,
    save_team_configuration,
)
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.domain import TeamBoard
from teams.queries import (
    ManagementTeamView,
    StudentRoundOption,
    StudentTeamView,
    TeamQueryData,
    build_management_team_view,
    build_student_team_view,
)


class TeamsDataSource(Protocol):
    """rounds·results·teams ORM 조회가 제공해야 하는 최소 데이터 경계다."""

    def get_student_round_data(
        self, user_id: int, round_id: int | None = None
    ) -> TeamQueryData: ...

    def get_student_round_options(self, user_id: int) -> tuple[StudentRoundOption, ...]: ...

    def get_round_team_data(self, round_id: int) -> TeamQueryData: ...

    def get_round_for_auto_assignment(self, round_id: int) -> RoundForTeamEditing: ...

    def get_seed_scores(
        self,
        round_id: int,
        participant_ids: tuple[int, ...],
    ) -> Mapping[int, Decimal | None]: ...

    def get_previous_teammate_pairs(
        self,
        round_id: int,
        participant_ids: tuple[int, ...],
    ) -> Collection[tuple[int, int]]: ...


class ServiceTeamsBackend:
    """HTTP View와 기존 Teams 업무 서비스를 연결하는 오케스트레이터다."""

    def __init__(
        self,
        data_source: TeamsDataSource,
        unit_of_work_factory: Callable[[], TeamSaveUnitOfWork],
        *,
        rng_factory: Callable[[], random.Random] = random.Random,
    ):
        self.data_source = data_source
        self.unit_of_work_factory = unit_of_work_factory
        self.rng_factory = rng_factory

    def get_student_team(self, user_id: int, round_id: int | None = None) -> StudentTeamView:
        data = self.data_source.get_student_round_data(user_id, round_id)
        return build_student_team_view(data, user_id)

    def get_student_round_options(self, user_id: int) -> tuple[StudentRoundOption, ...]:
        return self.data_source.get_student_round_options(user_id)

    def get_management_team(self, round_id: int) -> ManagementTeamView:
        data = self.data_source.get_round_team_data(round_id)
        participant_ids = tuple(participant.participant_id for participant in data.participants)
        seed_scores = self.data_source.get_seed_scores(round_id, participant_ids)
        return build_management_team_view(data, seed_scores)

    def create_auto_assignment(
        self,
        round_id: int,
        request_data: AutoAssignmentRequest,
    ) -> AutoTeamBoardResult:
        current_round = self.data_source.get_round_for_auto_assignment(round_id)
        if current_round.status != "DRAFT":
            raise RoundNotEditableError("only DRAFT rounds can edit teams")
        if current_round.lock_version != request_data.lock_version:
            raise TeamVersionConflictError(
                "team configuration changed; reload the latest configuration"
            )

        # 화면에서 이미 '미배정'으로 빼놓은 참가자는 자동배치 대상에서 제외한다 -
        # 그러지 않으면 자동배치를 누를 때마다 수동으로 뺀 사람이 다시 섞여 들어와
        # 평균 계산이 매번 달라진다.
        excluded_ids = set(request_data.excluded_participant_ids)
        assignable_participant_ids = tuple(
            participant_id
            for participant_id in current_round.participant_ids
            if participant_id not in excluded_ids
        )
        # 전원이 제외로 넘어왔다면 그건 "다 빼 달라"가 아니라 아직 아무도 배정되지 않은
        # 보드라는 뜻이다(새 회차가 그렇다). 그대로 두면 배치할 사람이 0명이라 실패하므로
        # 제외를 무시하고 전원을 대상으로 삼는다.
        if not assignable_participant_ids:
            assignable_participant_ids = tuple(current_round.participant_ids)
        # 시드 점수는 화면에 계속 표시해야 하므로 제외된 참가자를 포함해 전원 조회한다.
        seed_scores = self.data_source.get_seed_scores(round_id, current_round.participant_ids)
        previous_pairs = self.data_source.get_previous_teammate_pairs(
            round_id,
            assignable_participant_ids,
        )
        return create_auto_team_board(
            round_id=round_id,
            lock_version=current_round.lock_version,
            participant_ids=assignable_participant_ids,
            seed_scores=seed_scores,
            team_count=request_data.team_count,
            previous_teammate_pairs=previous_pairs,
            rng=self.rng_factory(),
        )

    def save_team_configuration(
        self,
        round_id: int,
        actor_id: int,
        request_data: TeamSaveRequest,
    ) -> TeamBoard:
        if request_data.board.round_id != round_id:
            raise ValueError("request round does not match URL round")
        return save_team_configuration(
            request_data.board,
            self.unit_of_work_factory(),
            actor_id=actor_id,
            imbalance_confirmed=request_data.imbalance_confirmed,
            unassigned_confirmed=request_data.unassigned_confirmed,
        )

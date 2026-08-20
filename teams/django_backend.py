from django.db import transaction

from audit.services import record_event
from results.models import EvaluationResult
from results.services import calculate_seed
from rounds.models import EvaluationRound
from teams.application import RoundForTeamEditing
from teams.backends import ServiceTeamsBackend
from teams.domain import TeamBoard
from teams.models import Team, TeamMembership
from teams.queries import ParticipantSnapshot, StoredTeam, StudentRoundOption, TeamQueryData


class DjangoTeamsDataSource:
    def _query_data(self, round_obj):
        participants = tuple(
            ParticipantSnapshot(
                participant_id=participant.pk,
                user_id=participant.user_id,
                student_number=participant.student_number_snapshot,
                display_name=participant.display_name_snapshot,
            )
            for participant in round_obj.participants.all()
        )
        teams = tuple(
            StoredTeam(
                team_number=team.team_number,
                name=team.name,
                participant_ids=tuple(
                    membership.participant_id for membership in team.memberships.all()
                ),
            )
            for team in round_obj.teams.all()
        )
        return TeamQueryData(
            round_id=round_obj.pk,
            round_status=round_obj.status,
            lock_version=round_obj.lock_version,
            participants=participants,
            teams=teams,
        )

    def get_student_round_data(self, user_id, round_id=None):
        """학생 본인의 팀 화면에 쓸 회차 데이터.

        round_id가 없으면 "가장 최근에 팀이 편성된 회차"를 고른다 - 진행 중인 회차가
        끝나도 그 팀 구성을 계속 보여주고, 다음 회차 팀이 새로 나오면 자동으로 그쪽으로
        넘어가야 하기 때문에(요구사항) 상태(IN_PROGRESS)가 아니라 회차 생성 순서로 고른다.
        """
        base_queryset = EvaluationRound.objects.prefetch_related(
            "participants", "teams__memberships"
        )
        if round_id is not None:
            round_obj = base_queryset.filter(pk=round_id, participants__user_id=user_id).first()
            if not round_obj:
                raise LookupError("회차가 없습니다.")
            return self._query_data(round_obj)

        round_obj = (
            base_queryset.filter(teams__memberships__participant__user_id=user_id)
            .distinct()
            .order_by("-created_at")
            .first()
        )
        if not round_obj:
            raise LookupError("배정된 팀이 없습니다.")
        return self._query_data(round_obj)

    def get_student_round_options(self, user_id):
        rounds = (
            EvaluationRound.objects.filter(teams__memberships__participant__user_id=user_id)
            .distinct()
            .order_by("-created_at")
        )
        return tuple(
            StudentRoundOption(round_id=round_obj.pk, round_title=round_obj.title)
            for round_obj in rounds
        )

    def get_round_team_data(self, round_id):
        try:
            round_obj = EvaluationRound.objects.prefetch_related(
                "participants", "teams__memberships"
            ).get(pk=round_id)
        except EvaluationRound.DoesNotExist as error:
            raise LookupError("회차가 없습니다.") from error
        return self._query_data(round_obj)

    def get_round_for_auto_assignment(self, round_id):
        try:
            round_obj = EvaluationRound.objects.prefetch_related("participants").get(pk=round_id)
        except EvaluationRound.DoesNotExist as error:
            raise LookupError("회차가 없습니다.") from error
        return RoundForTeamEditing(
            round_id=round_obj.pk,
            status=round_obj.status,
            lock_version=round_obj.lock_version,
            participant_ids=tuple(round_obj.participants.values_list("pk", flat=True)),
        )

    def get_seed_scores(self, round_id, participant_ids):
        participants = {
            participant.pk: participant.user_id
            for participant in EvaluationRound.objects.get(pk=round_id).participants.filter(
                pk__in=participant_ids
            )
        }
        scores = {}
        for participant_id, user_id in participants.items():
            history = list(
                EvaluationResult.objects.filter(
                    result_type=EvaluationResult.ResultType.INDIVIDUAL,
                    participant__user_id=user_id,
                    calculation_run__is_active=True,
                    calculation_run__round__status=EvaluationRound.Status.COMPLETED,
                    final_score_raw__isnull=False,
                )
                .exclude(calculation_run__round_id=round_id)
                .order_by("-calculation_run__round__completed_at")
                .values_list("final_score_raw", flat=True)[:3]
            )
            scores[participant_id] = calculate_seed(list(reversed(history)))
        return scores

    def get_previous_teammate_pairs(self, round_id, participant_ids):
        current_participants = {
            participant.user_id: participant.pk
            for participant in EvaluationRound.objects.get(pk=round_id).participants.filter(
                pk__in=participant_ids
            )
        }
        previous_round = (
            EvaluationRound.objects.filter(status=EvaluationRound.Status.COMPLETED)
            .exclude(pk=round_id)
            .order_by("-completed_at")
            .prefetch_related("teams__memberships__participant")
            .first()
        )
        if not previous_round:
            return set()
        pairs = set()
        for team in previous_round.teams.all():
            current_ids = sorted(
                current_participants[membership.participant.user_id]
                for membership in team.memberships.all()
                if membership.participant.user_id in current_participants
            )
            for index, first in enumerate(current_ids):
                for second in current_ids[index + 1 :]:
                    pairs.add((first, second))
        return pairs


class DjangoTeamSaveUnitOfWork:
    def __enter__(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.atomic.__exit__(exc_type, exc_value, traceback)

    def get_round_for_update(self, round_id):
        round_obj = EvaluationRound.objects.select_for_update().get(pk=round_id)
        self.round_obj = round_obj
        return RoundForTeamEditing(
            round_id=round_obj.pk,
            status=round_obj.status,
            lock_version=round_obj.lock_version,
            participant_ids=tuple(round_obj.participants.values_list("pk", flat=True)),
        )

    def replace_team_configuration(self, board: TeamBoard):
        Team.objects.filter(round=self.round_obj).delete()
        participant_by_id = {
            participant.pk: participant for participant in self.round_obj.participants.all()
        }
        for team_draft in board.teams:
            team = Team.objects.create(
                round=self.round_obj,
                team_number=team_draft.team_number,
                name=team_draft.name,
            )
            TeamMembership.objects.bulk_create(
                [
                    TeamMembership(team=team, participant=participant_by_id[participant_id])
                    for participant_id in team_draft.participant_ids
                ]
            )

    def increase_lock_version(self, round_id):
        self.round_obj.lock_version += 1
        self.round_obj.save(update_fields=("lock_version", "updated_at"))

    def record_team_configuration_saved(self, round_id, actor_id):
        record_event(
            action="TEAM_CONFIGURATION_SAVED",
            target=self.round_obj,
            actor_id=actor_id,
            round_obj=self.round_obj,
            summary={"team_count": self.round_obj.teams.count()},
        )

    def commit(self):
        return None


def build_django_teams_backend():
    return ServiceTeamsBackend(DjangoTeamsDataSource(), DjangoTeamSaveUnitOfWork)

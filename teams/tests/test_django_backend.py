from datetime import timedelta
from decimal import Decimal
from random import Random

from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from results.models import CalculationRun, EvaluationResult
from rounds.models import EvaluationRound, RoundParticipant
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.django_backend import build_django_teams_backend
from teams.models import Team, TeamMembership


class DjangoTeamsBackendTests(TestCase):
    def setUp(self):
        self.tutor = User.objects.create_user(
            email="team-backend-tutor@example.com",
            password="strong-test-password",
            first_name="튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="팀 저장 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        self.participants = []
        for index in range(1, 7):
            user = User.objects.create_user(
                email=f"team-backend-{index}@example.com",
                password="strong-test-password",
                first_name=f"학생{index}",
                student_number=f"T{index:03d}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
            )
            self.participants.append(
                RoundParticipant.objects.create(
                    round=self.round,
                    user=user,
                    student_number_snapshot=user.student_number,
                    display_name_snapshot=user.first_name,
                )
            )

    def _create_completed_round(self, *, days_ago):
        completed_at = timezone.now() - timedelta(days=days_ago)
        round_obj = EvaluationRound.objects.create(
            title=f"{days_ago}일 전 완료 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=completed_at - timedelta(days=2),
            evaluation_end_at=completed_at - timedelta(days=1),
            completed_at=completed_at,
            target_team_count=2,
            created_by=self.tutor,
        )
        participants_by_user_id = {}
        for current_participant in self.participants:
            previous_participant = RoundParticipant.objects.create(
                round=round_obj,
                user=current_participant.user,
                student_number_snapshot=current_participant.student_number_snapshot,
                display_name_snapshot=current_participant.display_name_snapshot,
            )
            participants_by_user_id[current_participant.user_id] = previous_participant
        return round_obj, participants_by_user_id

    def test_auto_board_can_be_saved_and_queried(self):
        backend = build_django_teams_backend()
        backend.rng_factory = lambda: Random(7)
        proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        saved = backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=proposal.board, imbalance_confirmed=False),
        )
        self.assertEqual(saved.lock_version, 1)
        view = backend.get_management_team(self.round.pk)
        self.assertEqual(len(view.teams), 2)
        self.assertEqual(sum(len(team.members) for team in view.teams), 6)
        self.assertTrue(AuditEvent.objects.filter(action="TEAM_CONFIGURATION_SAVED").exists())

    def test_saved_configuration_can_be_replaced(self):
        backend = build_django_teams_backend()
        backend.rng_factory = lambda: Random(7)
        first_proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=first_proposal.board, imbalance_confirmed=False),
        )

        second_proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=3, lock_version=1),
        )
        saved = backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=second_proposal.board, imbalance_confirmed=False),
        )

        self.assertEqual(saved.lock_version, 2)
        self.assertEqual(Team.objects.filter(round=self.round).count(), 3)
        self.assertEqual(
            TeamMembership.objects.filter(team__round=self.round).count(),
            6,
        )

    def test_team_delete_is_protected_while_memberships_exist(self):
        backend = build_django_teams_backend()
        backend.rng_factory = lambda: Random(7)
        proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=proposal.board, imbalance_confirmed=False),
        )

        with self.assertRaises(ProtectedError):
            Team.objects.filter(round=self.round).first().delete()

    def test_seed_scores_use_recent_active_completed_individual_results(self):
        score_history = (
            (30, Decimal("2.000000")),
            (20, Decimal("3.000000")),
            (10, Decimal("4.000000")),
        )
        seeded_user_id = self.participants[0].user_id
        for days_ago, score in score_history:
            previous_round, participants_by_user_id = self._create_completed_round(
                days_ago=days_ago
            )
            run = CalculationRun.objects.create(
                round=previous_round,
                version=1,
                status=CalculationRun.Status.SUCCEEDED,
                is_active=True,
                formula_version="score-v1",
                executed_by=self.tutor,
                finished_at=previous_round.completed_at,
            )
            EvaluationResult.objects.create(
                calculation_run=run,
                result_type=EvaluationResult.ResultType.INDIVIDUAL,
                participant=participants_by_user_id[seeded_user_id],
                final_score_raw=score,
                display_score=score,
                expected_count=1,
                valid_count=1,
                data_status=EvaluationResult.DataStatus.COMPLETE,
            )

        participant_ids = (self.participants[0].pk, self.participants[1].pk)
        scores = build_django_teams_backend().data_source.get_seed_scores(
            self.round.pk,
            participant_ids,
        )

        self.assertEqual(scores[self.participants[0].pk], Decimal("3.300000"))
        self.assertIsNone(scores[self.participants[1].pk])

    def test_previous_teammate_pairs_map_to_current_participant_ids(self):
        previous_round, participants_by_user_id = self._create_completed_round(days_ago=10)
        previous_team = Team.objects.create(
            round=previous_round,
            team_number=1,
            name="1팀",
        )
        TeamMembership.objects.bulk_create(
            [
                TeamMembership(
                    team=previous_team,
                    participant=participants_by_user_id[current_participant.user_id],
                )
                for current_participant in self.participants[:2]
            ]
        )

        pairs = build_django_teams_backend().data_source.get_previous_teammate_pairs(
            self.round.pk,
            tuple(participant.pk for participant in self.participants),
        )

        self.assertEqual(
            pairs,
            {(self.participants[0].pk, self.participants[1].pk)},
        )

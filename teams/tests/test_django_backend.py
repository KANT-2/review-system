from datetime import timedelta
from random import Random

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from results.models import CalculationRun, EvaluationResult
from rounds.models import EvaluationRound, RoundParticipant
from teams.contracts import AutoAssignmentRequest, TeamSaveRequest
from teams.django_backend import build_django_teams_backend
from teams.models import Team
from teams.views import _student_team_result_summary


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

    def test_student_team_survives_round_completion_and_moves_to_the_newest_team(self):
        """회차가 끝나도 마지막으로 배정된 팀을 계속 보여주고, 새 회차 팀이 생기면
        그쪽으로 자동으로 넘어가야 한다(다시 IN_PROGRESS 상태만 찾지 않는다)."""
        backend = build_django_teams_backend()
        student_user_id = self.participants[0].user_id
        proposal = backend.create_auto_assignment(
            self.round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        backend.save_team_configuration(
            self.round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=proposal.board, imbalance_confirmed=False),
        )
        self.round.status = EvaluationRound.Status.COMPLETED
        self.round.completed_at = timezone.now()
        self.round.save(update_fields=["status", "completed_at"])

        view = backend.get_student_team(student_user_id)
        self.assertEqual(view.round_id, self.round.pk)
        self.assertEqual(view.round_status, EvaluationRound.Status.COMPLETED)
        self.assertTrue(view.is_configured)

        options = backend.get_student_round_options(student_user_id)
        self.assertEqual([option.round_id for option in options], [self.round.pk])

        now = timezone.now()
        next_round = EvaluationRound.objects.create(
            title="다음 회차",
            evaluation_start_at=now,
            evaluation_end_at=now + timedelta(days=1),
            target_team_count=2,
            created_by=self.tutor,
        )
        for participant in self.participants:
            RoundParticipant.objects.create(
                round=next_round,
                user_id=participant.user_id,
                student_number_snapshot=participant.student_number_snapshot,
                display_name_snapshot=participant.display_name_snapshot,
            )
        next_proposal = backend.create_auto_assignment(
            next_round.pk,
            AutoAssignmentRequest(team_count=2, lock_version=0),
        )
        backend.save_team_configuration(
            next_round.pk,
            self.tutor.pk,
            TeamSaveRequest(board=next_proposal.board, imbalance_confirmed=False),
        )

        updated_view = backend.get_student_team(student_user_id)
        self.assertEqual(updated_view.round_id, next_round.pk)

        old_round_view = backend.get_student_team(student_user_id, round_id=self.round.pk)
        self.assertEqual(old_round_view.round_id, self.round.pk)

        options_after = backend.get_student_round_options(student_user_id)
        self.assertEqual(
            [option.round_id for option in options_after],
            [next_round.pk, self.round.pk],
        )


class StudentTeamResultSummaryTests(TestCase):
    """'내 팀' 화면 상단 결과 요약 - 튜터가 공개한 항목만 보여야 한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="result-summary-tutor@example.com",
            password="strong-test-password",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        now = timezone.now()
        self.round = EvaluationRound.objects.create(
            title="결과 요약 테스트 회차",
            status=EvaluationRound.Status.COMPLETED,
            evaluation_start_at=now - timedelta(days=7),
            evaluation_end_at=now,
            completed_at=now,
            created_by=self.tutor,
        )
        self.winner_team = Team.objects.create(round=self.round, team_number=1, name="1팀")
        self.my_team = Team.objects.create(round=self.round, team_number=2, name="2팀")
        self.run = CalculationRun.objects.create(
            round=self.round,
            version=1,
            status=CalculationRun.Status.SUCCEEDED,
            is_active=True,
            formula_version="v1",
            executed_by=self.tutor,
        )
        EvaluationResult.objects.create(
            calculation_run=self.run,
            result_type=EvaluationResult.ResultType.TEAM,
            team=self.winner_team,
            primary_rank=1,
            data_status=EvaluationResult.DataStatus.COMPLETE,
        )
        EvaluationResult.objects.create(
            calculation_run=self.run,
            result_type=EvaluationResult.ResultType.TEAM,
            team=self.my_team,
            primary_rank=2,
            data_status=EvaluationResult.DataStatus.COMPLETE,
        )

    def test_nothing_published_yields_no_summary(self):
        self.assertIsNone(_student_team_result_summary(self.round.pk, self.my_team.team_number))

    def test_only_winner_published_hides_my_team_rank(self):
        self.run.winner_published_at = timezone.now()
        self.run.save(update_fields=["winner_published_at"])

        summary = _student_team_result_summary(self.round.pk, self.my_team.team_number)

        self.assertEqual(summary["winner"]["name"], "1팀")
        self.assertIsNone(summary["my_team"])

    def test_team_ranking_published_shows_my_team_rank(self):
        self.run.team_ranking_published_at = timezone.now()
        self.run.save(update_fields=["team_ranking_published_at"])

        summary = _student_team_result_summary(self.round.pk, self.my_team.team_number)

        self.assertIsNone(summary["winner"])
        self.assertEqual(summary["my_team"]["rank"], 2)
        self.assertEqual(summary["my_team"]["team_name"], "2팀")

    def test_no_team_number_never_shows_my_team_rank(self):
        """튜터·미배정 학생처럼 팀이 없는 경우 - 1위 팀만 보일 수 있다."""
        self.run.winner_published_at = timezone.now()
        self.run.team_ranking_published_at = timezone.now()
        self.run.save(update_fields=["winner_published_at", "team_ranking_published_at"])

        summary = _student_team_result_summary(self.round.pk, None)

        self.assertIsNotNone(summary["winner"])
        self.assertIsNone(summary["my_team"])

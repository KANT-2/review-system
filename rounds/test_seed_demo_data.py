from io import StringIO

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import User
from results.models import CalculationRun
from reviews.models import ReviewAnswer, ReviewSubmission
from rounds.models import EvaluationRound, QuestionTemplate, RoundParticipant
from teams.models import Team, TeamMembership


class SeedDemoDataCommandTestCase(TestCase):
    """운영 DB에 시드 데이터를 채우는 명령이 사용자를 건드리지 않는지 확인한다."""

    def setUp(self):
        self.tutor = User.objects.create_user(
            email="tutor@example.com",
            password="password",
            first_name="박튜터",
            role=User.Role.TUTOR,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.students = [
            User.objects.create_user(
                email=f"student{index}@example.com",
                password="password",
                first_name=f"학생{index}",
                role=User.Role.STUDENT,
                approval_status=User.ApprovalStatus.APPROVED,
                student_number=f"AX{index:04d}",
            )
            for index in range(1, 9)
        ]
        # 승인 대기 수강생은 참가자에서 빠져야 한다.
        self.pending = User.objects.create_user(
            email="pending@example.com",
            password="password",
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.PENDING,
        )

    def run_command(self, **options):
        out = StringIO()
        call_command("seed_demo_data", stdout=out, **options)
        return out.getvalue()

    def test_creates_rounds_teams_and_reviews_without_touching_users(self):
        before = set(User.objects.values_list("pk", "email", "role", "approval_status"))

        self.run_command(completed=2)

        self.assertEqual(
            set(User.objects.values_list("pk", "email", "role", "approval_status")),
            before,
            "명령이 사용자를 만들거나 수정하면 안 된다.",
        )
        # 완료 2 + 진행 중 1 + 준비 중 1
        self.assertEqual(EvaluationRound.objects.count(), 4)
        self.assertEqual(
            EvaluationRound.objects.filter(status=EvaluationRound.Status.COMPLETED).count(), 2
        )
        self.assertEqual(
            EvaluationRound.objects.filter(status=EvaluationRound.Status.IN_PROGRESS).count(), 1
        )
        self.assertEqual(
            EvaluationRound.objects.filter(status=EvaluationRound.Status.DRAFT).count(), 1
        )
        self.assertEqual(QuestionTemplate.objects.count(), 2)

        for round_obj in EvaluationRound.objects.all():
            participant_users = set(
                RoundParticipant.objects.filter(round=round_obj).values_list("user_id", flat=True)
            )
            self.assertEqual(participant_users, {student.pk for student in self.students})
            self.assertNotIn(self.pending.pk, participant_users)
            self.assertNotIn(self.tutor.pk, participant_users)
            self.assertGreaterEqual(round_obj.teams.count(), 2)

        self.assertEqual(TeamMembership.objects.count(), 8 * EvaluationRound.objects.count())
        self.assertTrue(ReviewSubmission.objects.exists())
        self.assertTrue(ReviewAnswer.objects.exists())

    def test_does_not_score_publish_or_send_mail(self):
        self.run_command(completed=1)

        self.assertFalse(CalculationRun.objects.exists(), "채점은 하지 않아야 한다.")
        self.assertEqual(len(mail.outbox), 0, "메일을 보내면 안 된다.")

    def test_peer_reviews_stay_inside_the_team_and_skip_self(self):
        self.run_command(completed=1, no_in_progress=True, no_draft=True)

        peer_reviews = ReviewSubmission.objects.filter(
            review_type=ReviewSubmission.ReviewType.PEER
        ).select_related("evaluator__team_membership__team", "target_participant")
        self.assertTrue(peer_reviews.exists())
        for submission in peer_reviews:
            self.assertNotEqual(submission.evaluator_id, submission.target_participant_id)
            self.assertEqual(
                submission.evaluator.team_membership.team_id,
                submission.target_participant.team_membership.team_id,
            )

    def test_team_reviews_never_target_the_evaluators_own_team(self):
        self.run_command(completed=1, no_in_progress=True, no_draft=True)

        team_reviews = ReviewSubmission.objects.filter(
            review_type=ReviewSubmission.ReviewType.TEAM
        ).select_related("evaluator__team_membership")
        self.assertTrue(team_reviews.exists())
        for submission in team_reviews:
            self.assertNotEqual(
                submission.target_team_id,
                submission.evaluator.team_membership.team_id,
            )

    def test_rerun_is_idempotent(self):
        self.run_command(completed=2)
        counts = (
            EvaluationRound.objects.count(),
            RoundParticipant.objects.count(),
            Team.objects.count(),
            TeamMembership.objects.count(),
            ReviewSubmission.objects.count(),
            ReviewAnswer.objects.count(),
            QuestionTemplate.objects.count(),
        )

        self.run_command(completed=2)

        self.assertEqual(
            (
                EvaluationRound.objects.count(),
                RoundParticipant.objects.count(),
                Team.objects.count(),
                TeamMembership.objects.count(),
                ReviewSubmission.objects.count(),
                ReviewAnswer.objects.count(),
                QuestionTemplate.objects.count(),
            ),
            counts,
            "다시 실행해도 데이터가 중복으로 쌓이면 안 된다.",
        )

    def test_dry_run_writes_nothing(self):
        output = self.run_command(completed=2, dry_run=True)

        self.assertIn("롤백", output)
        self.assertEqual(EvaluationRound.objects.count(), 0)
        self.assertEqual(QuestionTemplate.objects.count(), 0)
        self.assertEqual(ReviewSubmission.objects.count(), 0)

    def test_skips_in_progress_round_when_another_one_is_already_running(self):
        self.run_command(completed=0, no_draft=True)
        running = EvaluationRound.objects.get(status=EvaluationRound.Status.IN_PROGRESS)

        output = self.run_command(completed=1, no_draft=True, title_prefix="[시드2]")

        self.assertIn("진행 중 회차 건너뜀", output)
        self.assertEqual(
            EvaluationRound.objects.filter(status=EvaluationRound.Status.IN_PROGRESS).count(), 1
        )
        self.assertEqual(
            EvaluationRound.objects.get(status=EvaluationRound.Status.IN_PROGRESS).pk, running.pk
        )

    def test_requires_enough_approved_students(self):
        User.objects.filter(role=User.Role.STUDENT).update(
            approval_status=User.ApprovalStatus.PENDING
        )

        with self.assertRaises(CommandError):
            self.run_command(completed=1)

    def test_requires_a_tutor_or_admin(self):
        User.objects.filter(pk=self.tutor.pk).delete()

        with self.assertRaises(CommandError):
            self.run_command(completed=1)

    def test_falls_back_to_a_generated_student_number_snapshot(self):
        User.objects.filter(pk=self.students[0].pk).update(student_number=None)

        self.run_command(completed=1, no_in_progress=True, no_draft=True)

        participant = RoundParticipant.objects.get(user=self.students[0])
        self.assertEqual(participant.student_number_snapshot, f"U{self.students[0].pk:06d}")
